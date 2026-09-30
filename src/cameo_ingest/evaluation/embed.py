"""Text embeddings from OpenAI-style endpoints: a local text-embeddings-inference (TEI)
container, or DeepInfra. Vectors are cached in SQLite by model, endpoint, role and the text's
sha256, so a text is embedded once whatever the experiment.

Both kinds of endpoint cut an input longer than the model's limit without notice, as a
production stack left at its defaults would (MiniLM 256 tokens, MPNet 384, the e5 models 512).
"""

from __future__ import annotations

import functools
import hashlib
import json
import logging
import os
import sqlite3
import threading
import time
import urllib.error
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

import numpy as np

log = logging.getLogger(__name__)

DEEPINFRA = "https://api.deepinfra.com/v1/openai"
Role = Literal["query", "passage"]


@dataclass(frozen=True)
class EmbeddingModel:
    name: str  # the model's Hugging Face id, as the endpoint knows it
    endpoint: str  # base URL of the OpenAI-style API, without /embeddings
    limit: int  # tokens the model reads; the endpoint cuts longer inputs
    query_prefix: str = ""  # the e5 models are trained with "query: " and "passage: "
    passage_prefix: str = ""
    batch: int = 32  # texts per request (TEI allows at most 32 by default)
    key_env: str | None = None  # environment variable holding the API key

    def prefixed(self, text: str, role: Role) -> str:
        return (self.query_prefix if role == "query" else self.passage_prefix) + text


# The maintainer's target models (plan RE, "The target models"), by where they run.
MODELS = {
    "minilm-local": EmbeddingModel("sentence-transformers/all-MiniLM-L6-v2", "http://localhost:8083/v1", 256),
    "minilm": EmbeddingModel("sentence-transformers/all-MiniLM-L6-v2", DEEPINFRA, 256, key_env="OPENAI_API_KEY"),
    "mpnet": EmbeddingModel("sentence-transformers/all-mpnet-base-v2", DEEPINFRA, 384, key_env="OPENAI_API_KEY"),
    "e5-large": EmbeddingModel("intfloat/multilingual-e5-large", DEEPINFRA, 512, "query: ", "passage: ",
                               key_env="OPENAI_API_KEY"),
    "e5-large-bare": EmbeddingModel("intfloat/multilingual-e5-large", DEEPINFRA, 512, key_env="OPENAI_API_KEY"),
    "e5-small-local": EmbeddingModel("intfloat/multilingual-e5-small", "http://localhost:8082/v1", 512, "query: ",
                                     "passage: "),
    "ember-local": EmbeddingModel("llmrails/ember-v1", "http://localhost:8084/v1", 512),
}
# Local TEI containers, one at a time on this machine (plan RE, "This machine"):
#   docker run -d --name cameo-embed-<short name> -p 127.0.0.1:<port>:80 \
#       ghcr.io/huggingface/text-embeddings-inference:cpu-latest --model-id <model>
# with ports 8082 (e5-small), 8083 (MiniLM), 8084 (ember-v1) and 8085 (the reranker).


@functools.cache
def tokenizer(model_name: str):
    """The model's own tokenizer, downloaded from Hugging Face once."""
    from tokenizers import Tokenizer

    return Tokenizer.from_pretrained(model_name)


def count_tokens(model_name: str, texts: list[str]) -> list[int]:
    """Tokens each text takes, special tokens included, as the model sees it before any cut."""
    tok = tokenizer(model_name)
    tok.no_truncation()
    return [len(e.ids) for e in tok.encode_batch(texts)]


class EmbeddingCache:
    """SQLite store of vectors (float32), keyed by model, endpoint, role and text hash."""

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

    def __init__(self, path: Path):
        path.parent.mkdir(parents=True, exist_ok=True)
        self._db = sqlite3.connect(path, check_same_thread=False)
        self._db.execute("PRAGMA journal_mode=WAL")
        self._db.executescript(self.SCHEMA)
        self._lock = threading.Lock()

    def get(self, m: EmbeddingModel, role: Role, keys: list[str]) -> dict[str, np.ndarray]:
        out: dict[str, np.ndarray] = {}
        with self._lock:
            for i in range(0, len(keys), 500):
                part = keys[i:i + 500]
                rows = self._db.execute(
                    f"SELECT text_sha256, vector FROM vectors WHERE model = ? AND endpoint = ? AND role = ? "
                    f"AND text_sha256 IN ({','.join('?' * len(part))})", (m.name, m.endpoint, role, *part))
                out.update((k, np.frombuffer(v, dtype=np.float32)) for k, v in rows)
        return out

    def put(self, m: EmbeddingModel, role: Role, items: list[tuple[str, np.ndarray]]) -> None:
        with self._lock:
            self._db.executemany("INSERT OR REPLACE INTO vectors VALUES (?, ?, ?, ?, ?)",
                                 [(m.name, m.endpoint, role, k, v.astype(np.float32).tobytes()) for k, v in items])
            self._db.commit()


def text_key(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


class Embedder:
    """Embeds texts with one model, through the cache; vectors come back normalized, so that
    a dot product is the cosine similarity."""

    def __init__(self, model: EmbeddingModel, cache: EmbeddingCache, concurrency: int = 4, retries: int = 4):
        self.model = model
        self.cache = cache
        self.concurrency = concurrency
        self.retries = retries
        self.calls = 0
        self.tokens = 0

    def _post(self, inputs: list[str]) -> list[list[float]]:
        m = self.model
        headers = {"Content-Type": "application/json"}
        if m.key_env:
            headers["Authorization"] = f"Bearer {os.environ[m.key_env]}"
        body = json.dumps({"model": m.name, "input": inputs}).encode()
        for attempt in range(self.retries + 1):
            try:
                req = urllib.request.Request(f"{m.endpoint}/embeddings", data=body, headers=headers)
                r = json.load(urllib.request.urlopen(req, timeout=120))
                self.calls += 1
                self.tokens += (r.get("usage") or {}).get("prompt_tokens", 0)
                return [d["embedding"] for d in sorted(r["data"], key=lambda d: d["index"])]
            except (urllib.error.URLError, TimeoutError, ConnectionError) as e:
                if attempt == self.retries:
                    raise
                log.debug("embedding request failed (%s); retrying", e)
                time.sleep(2 ** attempt)
        raise AssertionError("unreachable")

    def embed(self, texts: list[str], role: Role = "passage") -> np.ndarray:
        """One row per text, normalized to length 1."""
        keys = [text_key(self.model.prefixed(t, role)) for t in texts]  # with and without a prefix differ
        known = self.cache.get(self.model, role, list(dict.fromkeys(keys)))
        todo = list(dict.fromkeys(k for k in keys if k not in known))
        if todo:
            text_of = dict(zip(keys, texts, strict=True))
            batches = [todo[i:i + self.model.batch] for i in range(0, len(todo), self.model.batch)]

            def run(batch: list[str]) -> None:
                vectors = self._post([self.model.prefixed(text_of[k], role) for k in batch])  # text_of: unprefixed
                items = [(k, np.asarray(v, dtype=np.float32)) for k, v in zip(batch, vectors, strict=True)]
                self.cache.put(self.model, role, items)
                known.update(items)

            with ThreadPoolExecutor(self.concurrency) as pool:
                list(pool.map(run, batches))
        out = np.stack([known[k] for k in keys]) if keys else np.zeros((0, 1), dtype=np.float32)
        norms = np.linalg.norm(out, axis=1, keepdims=True)
        return out / np.where(norms == 0, 1, norms)
