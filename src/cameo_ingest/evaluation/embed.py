"""Text embeddings from DeepInfra's OpenAI-compatible API, through the OpenAI SDK (AR-017R1).
Vectors are cached in SQLite by model, endpoint, role and the text's sha256, so a text is
embedded once whatever the experiment.

DeepInfra cuts an input longer than the model's limit without notice, as a production stack
left at its defaults would (MiniLM 256 tokens, MPNet 384, the others 512).
"""

from __future__ import annotations

import functools
import hashlib
import threading
from collections.abc import Iterable
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from typing import Any, Literal

from ..sqlite_cache import SqliteCache
from . import provider, require

np = require("numpy")

Role = Literal["query", "passage"]


@dataclass(frozen=True)
class EmbeddingModel:
    name: str  # the model's Hugging Face id, as the endpoint knows it
    limit: int  # tokens the model reads; the endpoint cuts longer inputs
    query_prefix: str = ""  # the e5 models are trained with "query: " and "passage: "
    passage_prefix: str = ""
    batch: int = 32  # texts per request
    cut_here: bool = False  # the endpoint rejects inputs over the limit, rather than cutting them

    def prefixed(self, text: str, role: Role) -> str:
        return (self.query_prefix if role == "query" else self.passage_prefix) + text


# The models evaluated, all on DeepInfra (plan RE, decisions 7 and 8): local containers were
# too slow for this machine, and tied to two crashes. ember-v1 and e5-small are not on DeepInfra;
# bge-large-en-v1.5 stands in for ember-v1 (the same BERT-large shape, CLS pooling, 1,024
# dimensions and 512 tokens, and nearly the same benchmark score), and is reported as a stand-in.
MODELS = {
    "e5-large": EmbeddingModel("intfloat/multilingual-e5-large", 512, "query: ", "passage: "),
    "e5-large-bare": EmbeddingModel("intfloat/multilingual-e5-large", 512),
    "bge-large": EmbeddingModel("BAAI/bge-large-en-v1.5", 512, cut_here=True),
    "mpnet": EmbeddingModel("sentence-transformers/all-mpnet-base-v2", 384),
    "minilm": EmbeddingModel("sentence-transformers/all-MiniLM-L6-v2", 256),
}


@functools.cache
def tokenizer(model_name: str):
    """The model's own tokenizer, downloaded from Hugging Face once."""
    return require("tokenizers").Tokenizer.from_pretrained(model_name)


def cut(model_name: str, text: str, limit: int) -> str:
    """`text` cut to what fits in `limit` tokens with the model's two special tokens, as an
    endpoint that cuts long inputs would."""
    tok = tokenizer(model_name)
    tok.no_truncation()
    offsets = tok.encode(text, add_special_tokens=False).offsets
    return text if len(offsets) <= limit - 2 else text[:offsets[limit - 3][1]]


def count_tokens(model_name: str, texts: list[str]) -> list[int]:
    """Tokens each text takes, special tokens included, as the model sees it before any cut."""
    tok = tokenizer(model_name)
    tok.no_truncation()
    out: list[int] = []
    for i in range(0, len(texts), 256):  # in batches: encodings hold every token's offsets
        out += [len(e.ids) for e in tok.encode_batch(texts[i:i + 256])]
    return out


class EmbeddingCache(SqliteCache):
    """SQLite store of vectors (float32), keyed by model, endpoint, role and text hash. The
    endpoint is the provider's API, so that vectors cached before the provider was configured in
    one place still match."""

    WAL = True
    WHAT = "embedding cache"
    SCHEMA = """
        CREATE TABLE IF NOT EXISTS vectors (
            model TEXT NOT NULL,
            endpoint TEXT NOT NULL,
            role TEXT NOT NULL,          -- query or passage
            text_sha256 TEXT NOT NULL,   -- of the text as sent, prefix included
            vector BLOB NOT NULL,        -- float32, as returned (not normalized)
            PRIMARY KEY (model, endpoint, role, text_sha256)
        );
    """

    def get(self, m: EmbeddingModel, role: Role, keys: list[str]) -> dict[str, np.ndarray]:
        out: dict[str, np.ndarray] = {}
        with self._lock:
            for i in range(0, len(keys), 500):
                part = keys[i:i + 500]
                rows = self._db.execute(
                    f"SELECT text_sha256, vector FROM vectors WHERE model = ? AND endpoint = ? AND role = ? "
                    f"AND text_sha256 IN ({','.join('?' * len(part))})", (m.name, provider.OPENAI_API, role, *part))
                out.update((k, np.frombuffer(v, dtype=np.float32)) for k, v in rows)
        return out

    def put(self, m: EmbeddingModel, role: Role, items: list[tuple[str, np.ndarray]]) -> None:
        with self._lock:
            self._db.executemany("INSERT OR REPLACE INTO vectors VALUES (?, ?, ?, ?, ?)",
                                 [(m.name, provider.OPENAI_API, role, k, v.astype(np.float32).tobytes())
                                  for k, v in items])
            self._db.commit()


def text_key(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


class Embedder:
    """Embeds texts with one model, through the cache; vectors come back normalized, so that
    a dot product is the cosine similarity."""

    def __init__(self, model: EmbeddingModel, cache: EmbeddingCache, concurrency: int = 4, retries: int = 4,
                 client: Any = None):
        self.model = model
        self.cache = cache
        self.concurrency = concurrency
        self.client = client or provider.openai_client(retries)  # the SDK retries busy and failed requests
        self.calls = 0
        self.tokens = 0
        self._lock = threading.Lock()  # the counters, updated from the request threads

    def _post(self, inputs: list[str]) -> list[list[float]]:
        r = self.client.embeddings.create(model=self.model.name, input=inputs, encoding_format="float")
        with self._lock:
            self.calls += 1
            self.tokens += r.usage.prompt_tokens if r.usage else 0
        return [d.embedding for d in sorted(r.data, key=lambda d: d.index)]

    def embed(self, texts: list[str], role: Role = "passage") -> np.ndarray:
        """One row per text, normalized to length 1. The rows are filled into one matrix as they
        come, from the cache a slice at a time, so that a large corpus is held once (plan RM-06)."""
        keys = [text_key(self.model.prefixed(t, role)) for t in texts]  # with and without a prefix differ
        rows: dict[str, list[int]] = {}
        for i, k in enumerate(keys):
            rows.setdefault(k, []).append(i)
        out: np.ndarray | None = None
        placed: set[str] = set()

        def place(items: Iterable[tuple[str, np.ndarray]]) -> None:
            nonlocal out
            for k, v in items:
                if out is None:
                    out = np.empty((len(keys), len(v)), dtype=np.float32)
                out[rows[k]] = v
                placed.add(k)

        unique = list(rows)
        for i in range(0, len(unique), 5000):
            place(self.cache.get(self.model, role, unique[i:i + 5000]).items())
        todo = [k for k in unique if k not in placed]
        if todo:
            text_of = dict(zip(keys, texts, strict=True))
            batches = [todo[i:i + self.model.batch] for i in range(0, len(todo), self.model.batch)]

            def run(batch: list[str]) -> None:
                sent = [self.model.prefixed(text_of[k], role) for k in batch]  # text_of: unprefixed
                if self.model.cut_here:  # keyed on the whole text, sent cut
                    sent = [cut(self.model.name, s, self.model.limit) for s in sent]
                vectors = self._post(sent)
                items = [(k, np.asarray(v, dtype=np.float32)) for k, v in zip(batch, vectors, strict=True)]
                self.cache.put(self.model, role, items)
                with self._lock:
                    place(items)

            with ThreadPoolExecutor(self.concurrency) as pool:
                list(pool.map(run, batches))
        if out is None:
            return np.zeros((0, 1), dtype=np.float32)
        norms = np.linalg.norm(out, axis=1, keepdims=True)
        out /= np.where(norms == 0, 1, norms)
        return out
