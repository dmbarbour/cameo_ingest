#!/usr/bin/env python3
"""Check the embedding endpoints of the retrieval evaluation (plan RE-02).

    uv run --group eval python scripts/embedding_check.py --env .env out/tmt-dv --n 300

For a random sample of chunks from an output tree:
- each model's token counts, and the share of chunks longer than its limit;
- each model's speed, embedding the sample from an empty cache.

(Local and DeepInfra copies of MiniLM gave identical vectors on 300 TMT chunks; the local
containers have since been dropped, plan RE decision 8.)

Vectors are cached in DIR/.cache/embeddings.sqlite (default: the tree's .cache).
"""

from __future__ import annotations

import argparse
import json
import random
import statistics
import time
from pathlib import Path

from cameo_ingest.cli import load_env
from cameo_ingest.evaluation.embed import MODELS, Embedder, EmbeddingCache, count_tokens


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("tree", type=Path)
    ap.add_argument("--env", type=Path)
    ap.add_argument("--n", type=int, default=300)
    ap.add_argument("--cache", type=Path, help="embedding cache (default: TREE/.cache/embeddings.sqlite)")
    args = ap.parse_args()
    if args.env:
        load_env(args.env)
    chunks = [json.loads(line) for line in (args.tree / "chunks.jsonl").open(encoding="utf-8")]
    texts = [c["text"] for c in random.Random(1).sample(chunks, min(args.n, len(chunks)))]
    cache = EmbeddingCache(args.cache or args.tree / ".cache" / "embeddings.sqlite")

    print(f"{len(texts)} chunks sampled from {len(chunks):,} in {args.tree}\n")
    print("| model | limit | tokens (median) | over the limit | seconds for the sample | texts per second |")
    print("|---|---|---|---|---|---|")
    for key, m in MODELS.items():
        counts = count_tokens(m.name, [m.prefixed(t, "passage") for t in texts])
        e = Embedder(m, cache)
        t0 = time.perf_counter()
        try:
            e.embed(texts)
        except Exception as ex:  # an endpoint that isn't running
            print(f"| {key} | {m.limit} | {statistics.median(counts):.0f} | "
                  f"{sum(c > m.limit for c in counts) / len(counts):.0%} | unavailable: {type(ex).__name__} | |")
            continue
        dt = time.perf_counter() - t0
        speed = f"{len(texts) / dt:.0f}" if e.calls else "(cached)"
        print(f"| {key} | {m.limit} | {statistics.median(counts):.0f} | {sum(c > m.limit for c in counts) / len(counts):.0%} "
              f"| {dt:.1f} | {speed} |")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
