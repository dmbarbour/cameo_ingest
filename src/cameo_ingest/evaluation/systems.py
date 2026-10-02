"""The retrieval systems an evaluation compares (AR-020R1): BM25, each dense model, each fused
with BM25 (plainly, and at other weights), and, with a reranker, each of those with its top
reranked. Each system ranks the windows for every question; a ranking is a list of window
indexes, best first.
"""

from __future__ import annotations

import time
from collections.abc import Callable
from pathlib import Path

from .embed import MODELS, Embedder, EmbeddingCache
from .harness import BM25, Unit, fuse, top
from .rerank import Reranker

Rankings = list[list[int]]  # per question


def build(windows: list[Unit], questions: list[dict], models: list[str], cache: EmbeddingCache, *,
          concurrency: int = 8, bm25_weights: list[float] = (), rerank: str | None = None, rerank_depth: int = 30,
          rerank_cache: Path = Path("out/eval/rerank.sqlite"),
          say: Callable[[str], None] = print) -> dict[str, Rankings]:
    """Every system's rankings, by name, in the order the report lists them."""
    texts = [u.text for u in windows]
    bm25 = BM25(texts)
    lexical = [top(bm25.scores(q["question"]), 100) for q in questions]
    say(f"{len(windows):,} windows")
    systems: dict[str, Rankings] = {"bm25": lexical}
    for key in models:
        t0 = time.perf_counter()
        e = Embedder(MODELS[key], cache, concurrency=concurrency)
        docs = e.embed(texts, "passage")
        qv = e.embed([q["question"] for q in questions], "query")
        say(f"{key}: embedded in {time.perf_counter() - t0:.0f} s ({e.calls} requests, {e.tokens:,} tokens)")
        dense = [top(docs @ qv[i], 100) for i in range(len(questions))]
        systems[key] = dense
        systems[f"{key} + bm25"] = [fuse([d, w]) for d, w in zip(dense, lexical, strict=True)]
        for weight in bm25_weights:
            systems[f"{key} + bm25×{weight:g}"] = [fuse([d, w], weights=[1.0, weight])
                                                   for d, w in zip(dense, lexical, strict=True)]
    if rerank:
        t0 = time.perf_counter()
        reranker = Reranker(rerank, rerank_cache, concurrency=concurrency)
        reranker.scores(list({(q["question"], texts[j]) for ranked in systems.values()  # every pair at once
                              for q, r in zip(questions, ranked, strict=True) for j in r[:rerank_depth]}))
        for name in list(systems):
            systems[f"{name} → {rerank}"] = [reranker.rerank(q["question"], r, texts, rerank_depth)
                                             for q, r in zip(questions, systems[name], strict=True)]
        say(f"{reranker.model}: {reranker.calls} requests, {reranker.tokens:,} tokens, "
            f"{time.perf_counter() - t0:.0f} s")
    return systems
