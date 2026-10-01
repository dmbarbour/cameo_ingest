#!/usr/bin/env python3
"""Inventory an output tree's chunks against the target embedding models (plan RE-01).

    uv run --group eval python scripts/chunk_inventory.py out/all

Prints, in Markdown:
- per chunk kind: how many, their median length in each model's tokens, and the share longer
  than each model's limit;
- what fills the chunks: link targets, qualified names and trace lines, as shares of the text;
- the windows the production stack is thought to make (512 tokens, 64 of overlap), from
  chunks.jsonl and from the Markdown pages, in each model's tokens.
"""

from __future__ import annotations

import argparse
import json
import re
import statistics
from collections import defaultdict
from pathlib import Path

from cameo_ingest.evaluation.embed import count_tokens
from cameo_ingest.evaluation.windows import windows

MODELS = {  # name: limit, for the models evaluated (plan RE, decision 8); bge-large stands in for ember-v1
    "intfloat/multilingual-e5-large": 512,
    "BAAI/bge-large-en-v1.5": 512,
    "sentence-transformers/all-mpnet-base-v2": 384,
    "sentence-transformers/all-MiniLM-L6-v2": 256,
}
SHORT = {"intfloat/multilingual-e5-large": "e5-large", "BAAI/bge-large-en-v1.5": "bge-large",
         "sentence-transformers/all-mpnet-base-v2": "mpnet", "sentence-transformers/all-MiniLM-L6-v2": "minilm"}
FILLERS = {
    "link targets": re.compile(r"\]\([^)]*\)"),
    "qualified names": re.compile(r"\*\*Qualified name:\*\* `[^`]*`"),
    "trace lines": re.compile(r"<sub>trace: `[^`]*`</sub>"),
}


def kind_of(chunk: dict) -> str:
    k = chunk["metadata"]["kind"]
    return k if k.startswith("generated:") else k.split(":")[0]


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("tree", type=Path)
    ap.add_argument("--window", type=int, default=512)
    ap.add_argument("--overlap", type=int, default=64)
    args = ap.parse_args()
    chunks = [json.loads(line) for line in (args.tree / "chunks.jsonl").open(encoding="utf-8")]
    texts = [c["text"] for c in chunks]
    tokens = {m: count_tokens(m, texts) for m in MODELS}

    print(f"{len(chunks):,} chunks in {args.tree}, from "
          f"{len({c['metadata'].get('content') for c in chunks} - {None}):,} projects\n")
    by_kind: dict[str, list[int]] = defaultdict(list)
    for i, c in enumerate(chunks):
        by_kind[kind_of(c)].append(i)
    head = " | ".join(f"{SHORT[m]} median | over {lim}" for m, lim in MODELS.items())
    print(f"| kind | chunks | {head} |")
    print("|---|---|" + "---|---|" * len(MODELS))
    for kind, idx in sorted(by_kind.items(), key=lambda kv: -len(kv[1])):
        cells = []
        for m, lim in MODELS.items():
            ts = [tokens[m][i] for i in idx]
            cells.append(f"{statistics.median(ts):.0f} | {sum(t > lim for t in ts) / len(ts):.0%}")
        print(f"| {kind} | {len(idx):,} | " + " | ".join(cells) + " |")

    total = sum(len(t) for t in texts)
    print("\nWhat fills the chunks, as shares of their characters: " + "; ".join(
        f"{name} {sum(len(m) for t in texts for m in rx.findall(t)) / total:.0%}" for name, rx in FILLERS.items()))

    pages = sorted(args.tree.glob("by-sha256/*/**/*.md"))
    print(f"\nWindows of {args.window} tokens with {args.overlap} of overlap:")
    print("| model | from chunks.jsonl | from the pages |")
    print("|---|---|---|")
    for m in ("intfloat/multilingual-e5-large", "BAAI/bge-large-en-v1.5"):
        from_chunks = sum(len(windows(t, m, args.window, args.overlap)) for t in texts)
        # One page at a time: the largest run to several megabytes.
        from_pages = sum(len(windows(p.read_text(encoding="utf-8"), m, args.window, args.overlap)) for p in pages)
        print(f"| {SHORT[m]} | {from_chunks:,} | {from_pages:,} ({len(pages):,} pages) |")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
