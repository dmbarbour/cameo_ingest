"""Rerankers (cross-encoders) on DeepInfra, to reorder the top of a ranking (plan RF, RF-02).

A reranker reads the question and a passage together and scores how well the passage answers
it, so it can reorder a keyword search's candidates by meaning. The maintainer's stack lists
`BAAI/bge-reranker-v2-m3` and two ms-marco cross-encoders, none of which DeepInfra serves;
Qwen3-Reranker stands in (plan RF, decision 3): its 0.6B model is about the size of
bge-reranker-v2-m3. Scores are cached in SQLite by model and the sha256 of query and passage.
"""

from __future__ import annotations

import json
import logging
import os
import sqlite3
import threading
import time
import urllib.error
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from .embed import text_key

log = logging.getLogger(__name__)

INFERENCE = "https://api.deepinfra.com/v1/inference"
RERANKERS = {  # short name -> model on DeepInfra
    "qwen3-0.6b": "Qwen/Qwen3-Reranker-0.6B",
    "qwen3-4b": "Qwen/Qwen3-Reranker-4B",
    "qwen3-8b": "Qwen/Qwen3-Reranker-8B",
}


class Reranker:
    """Scores (query, passage) pairs with one model, through a cache."""

    SCHEMA = """
        CREATE TABLE IF NOT EXISTS scores (
            model TEXT NOT NULL,
            query_sha256 TEXT NOT NULL,
            passage_sha256 TEXT NOT NULL,
            score REAL NOT NULL,
            PRIMARY KEY (model, query_sha256, passage_sha256)
        );
    """

    def __init__(self, model: str, cache: Path, concurrency: int = 8, batch: int = 16, retries: int = 6,
                 key_env: str = "OPENAI_API_KEY"):
        self.model = RERANKERS.get(model, model)
        cache.parent.mkdir(parents=True, exist_ok=True)
        self._db = sqlite3.connect(cache, check_same_thread=False)
        self._db.execute("PRAGMA journal_mode=WAL")
        self._db.executescript(self.SCHEMA)
        self._lock = threading.Lock()
        self.concurrency, self.batch, self.retries, self.key_env = concurrency, batch, retries, key_env
        self.calls = 0
        self.tokens = 0

    def _post(self, query: str, passages: list[str]) -> list[float]:
        body = json.dumps({"queries": [query], "documents": passages}).encode()
        headers = {"Content-Type": "application/json", "Authorization": f"Bearer {os.environ[self.key_env]}"}
        for attempt in range(self.retries + 1):
            try:
                req = urllib.request.Request(f"{INFERENCE}/{self.model}", data=body, headers=headers)
                r = json.load(urllib.request.urlopen(req, timeout=120))
                with self._lock:
                    self.calls += 1
                    self.tokens += r.get("input_tokens") or 0
                return [float(s) for s in r["scores"]]
            except urllib.error.HTTPError as e:
                detail = e.read()[:300].decode("utf-8", "replace")
                if e.code != 429 and e.code < 500 or attempt == self.retries:  # retrying won't fix a bad request
                    raise RuntimeError(f"{self.model}: HTTP {e.code}: {detail}") from e
                time.sleep(2 ** attempt)
            except (urllib.error.URLError, TimeoutError, ConnectionError):
                if attempt == self.retries:
                    raise
                time.sleep(2 ** attempt)
        raise AssertionError("unreachable")

    def scores(self, pairs: list[tuple[str, str]]) -> list[float]:
        """A score per (query, passage) pair, higher for a better answer."""
        keys = [(text_key(q), text_key(p)) for q, p in pairs]
        known: dict[tuple[str, str], float] = {}
        with self._lock:
            for q in {k[0] for k in keys}:
                rows = self._db.execute("SELECT passage_sha256, score FROM scores WHERE model = ? AND query_sha256 = ?",
                                        (self.model, q))
                known.update(((q, p), s) for p, s in rows)
        todo: dict[str, dict[str, str]] = {}  # query -> passage key -> passage, for what isn't cached
        query_of = {}
        for (qk, pk), (q, p) in zip(keys, pairs, strict=True):
            if (qk, pk) not in known:
                todo.setdefault(qk, {})[pk] = p
                query_of[qk] = q
        jobs = [(qk, list(ps.items())[i:i + self.batch]) for qk, ps in todo.items()
                for i in range(0, len(ps), self.batch)]

        def run(job: tuple[str, list[tuple[str, str]]]) -> None:
            qk, items = job
            got = self._post(query_of[qk], [p for _, p in items])
            rows = [(self.model, qk, pk, s) for (pk, _), s in zip(items, got, strict=True)]
            with self._lock:
                self._db.executemany("INSERT OR REPLACE INTO scores VALUES (?, ?, ?, ?)", rows)
                self._db.commit()
                known.update(((qk, pk), s) for _, _, pk, s in rows)

        with ThreadPoolExecutor(self.concurrency) as pool:
            list(pool.map(run, jobs))
        return [known[k] for k in keys]

    def rerank(self, query: str, ranking: list[int], texts: list[str], depth: int) -> list[int]:
        """`ranking` (indexes into `texts`) with its top `depth` reordered by score."""
        head = ranking[:depth]
        s = self.scores([(query, texts[i]) for i in head])
        order = sorted(range(len(head)), key=lambda k: -s[k])
        return [head[k] for k in order] + ranking[depth:]
