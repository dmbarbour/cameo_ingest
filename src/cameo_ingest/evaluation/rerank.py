"""Rerankers (cross-encoders) on DeepInfra, to reorder the top of a ranking (plan RF, RF-02).

A reranker reads the question and a passage together and scores how well the passage answers
it, so it can reorder a keyword search's candidates by meaning. The maintainer's stack lists
`BAAI/bge-reranker-v2-m3` and two ms-marco cross-encoders, none of which DeepInfra serves;
Qwen3-Reranker stands in (plan RF, decision 3): its 0.6B model is about the size of
bge-reranker-v2-m3. Scores are cached in SQLite by model and the sha256 of query and passage.
"""

from __future__ import annotations

import threading
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from ..sqlite_cache import SqliteCache
from . import provider
from .embed import text_key

RERANKERS = {  # short name -> model on DeepInfra
    "qwen3-0.6b": "Qwen/Qwen3-Reranker-0.6B",
    "qwen3-4b": "Qwen/Qwen3-Reranker-4B",
    "qwen3-8b": "Qwen/Qwen3-Reranker-8B",
}


class ScoreCache(SqliteCache):
    """SQLite store of scores, keyed by model and the sha256 of query and passage."""

    WAL = True
    WHAT = "rerank cache"
    SCHEMA = """
        CREATE TABLE IF NOT EXISTS scores (
            model TEXT NOT NULL,
            query_sha256 TEXT NOT NULL,
            passage_sha256 TEXT NOT NULL,
            score REAL NOT NULL,
            PRIMARY KEY (model, query_sha256, passage_sha256)
        );
    """

    def get(self, model: str, queries: set[str]) -> dict[tuple[str, str], float]:
        """The scores known for these queries (by key), by (query key, passage key)."""
        out: dict[tuple[str, str], float] = {}
        with self._lock:
            for q in queries:
                rows = self._db.execute("SELECT passage_sha256, score FROM scores WHERE model = ? AND query_sha256 = ?",
                                        (model, q))
                out.update(((q, p), s) for p, s in rows)
        return out

    def put(self, model: str, rows: list[tuple[str, str, float]]) -> None:
        """(query key, passage key, score) rows."""
        with self._lock:
            self._db.executemany("INSERT OR REPLACE INTO scores VALUES (?, ?, ?, ?)",
                                 [(model, q, p, s) for q, p, s in rows])
            self._db.commit()


class Reranker:
    """Scores (query, passage) pairs with one model, through a cache."""

    def __init__(self, model: str, cache: Path, concurrency: int = 8, batch: int = 16, retries: int = 6,
                 post: Callable[..., dict] = provider.post_json):
        self.model = RERANKERS.get(model, model)
        self.cache = ScoreCache(cache)
        self.concurrency, self.batch, self.retries, self.post = concurrency, batch, retries, post
        self.calls = 0
        self.tokens = 0
        self._lock = threading.Lock()  # the counters, updated from the request threads

    def _post(self, query: str, passages: list[str]) -> list[float]:
        r = self.post(f"{provider.INFERENCE_API}/{self.model}", {"queries": [query], "documents": passages},
                      self.retries)
        with self._lock:
            self.calls += 1
            self.tokens += r.get("input_tokens") or 0
        return [float(s) for s in r["scores"]]

    def scores(self, pairs: list[tuple[str, str]]) -> list[float]:
        """A score per (query, passage) pair, higher for a better answer."""
        keys = [(text_key(q), text_key(p)) for q, p in pairs]
        known = self.cache.get(self.model, {k[0] for k in keys})
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
            rows = [(qk, pk, s) for (pk, _), s in zip(items, got, strict=True)]
            self.cache.put(self.model, rows)
            with self._lock:
                known.update(((qk, pk), s) for _, pk, s in rows)

        with ThreadPoolExecutor(self.concurrency) as pool:
            list(pool.map(run, jobs))
        return [known[k] for k in keys]

    def rerank(self, query: str, ranking: list[int], texts: list[str], depth: int) -> list[int]:
        """`ranking` (indexes into `texts`) with its top `depth` reordered by score."""
        head = ranking[:depth]
        s = self.scores([(query, texts[i]) for i in head])
        order = sorted(range(len(head)), key=lambda k: -s[k])
        return [head[k] for k in order] + ranking[depth:]
