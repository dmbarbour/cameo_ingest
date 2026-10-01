#!/usr/bin/env python3
"""Run retrieval over an output tree for a set of questions, and report how often the answers
come back (plan RE-05).

    uv run --group eval python scripts/retrieval_eval.py out/all --env .env --models e5-large minilm \\
        --out out/eval/retrieval/synthetic

The questions are the synthetic project's (`cameo_ingest.evaluation.synthetic`), graded by
construction:
- **2:** a window of a chunk about an answering element;
- **1:** a window of a chunk about a related element, or a window of the synthetic project that
  holds the planted fact (a package summary quoting it, say).

Each model's windows are embedded through the cache (`--cache`), so a rerun, or a run cut off,
costs only what is missing. Writes OUT/report.md and OUT/rankings.jsonl (each question's top 10
per system, for inspection).
"""

from __future__ import annotations

import argparse
import json
import time
from collections import defaultdict
from pathlib import Path

from cameo_ingest.cli import load_env
from cameo_ingest.evaluation.embed import MODELS, Embedder, EmbeddingCache
from cameo_ingest.evaluation.harness import BM25, Unit, chunk_units, fuse, mean_ci, measures, top, windowed
from cameo_ingest.evaluation.synthetic import QUESTIONS

SYNTHETIC = "_kois_"  # the synthetic project's element ids start so
MEASURES = ("hit@1", "hit@5", "hit@10", "hit@20", "mrr@10", "ndcg@10")


def grades(q: dict, units: list[Unit]) -> dict[int, int]:
    out = {}
    for i, u in enumerate(units):
        if u.element_id in q["answers"]:
            out[i] = 2
        elif u.element_id in q["related"] or (
                (u.element_id or "").startswith(SYNTHETIC) and q["evidence"] in u.text):
            out[i] = 1
    return out


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("tree", type=Path)
    ap.add_argument("--env", type=Path)
    ap.add_argument("--models", nargs="+", default=list(MODELS), choices=list(MODELS))
    ap.add_argument("--out", type=Path, required=True)
    ap.add_argument("--cache", type=Path, default=Path("out/eval/embeddings.sqlite"))
    ap.add_argument("--window", type=int, default=512)
    ap.add_argument("--overlap", type=int, default=64)
    ap.add_argument("--window-tokenizer", default="intfloat/multilingual-e5-large",
                    help="the tokens windows are cut on: one set of windows for every model, so that all rank "
                         "the same candidates (models with smaller limits are cut by the endpoint)")
    ap.add_argument("--concurrency", type=int, default=8)
    ap.add_argument("--project", help="only the chunks of projects whose element ids start so (a smoke test)")
    args = ap.parse_args()
    if args.env:
        load_env(args.env)
    units = chunk_units(args.tree)
    if args.project:
        units = [u for u in units if (u.element_id or "").startswith(args.project)]
    cache = EmbeddingCache(args.cache)
    questions = QUESTIONS
    print(f"{len(units):,} chunks from {args.tree}; {len(questions)} questions")

    results: dict[str, list[dict]] = {}  # system -> per-question measures
    rankings = []
    ws = windowed(units, args.window_tokenizer, args.window, args.overlap)
    bm25 = BM25([u.text for u in ws])
    lexical = [top(bm25.scores(q["question"]), 100) for q in questions]
    print(f"{len(ws):,} windows", flush=True)
    for key in args.models:
        m = MODELS[key]
        t0 = time.perf_counter()
        e = Embedder(m, cache, concurrency=args.concurrency)
        docs = e.embed([u.text for u in ws], "passage")
        qv = e.embed([q["question"] for q in questions], "query")
        print(f"{key}: embedded in {time.perf_counter() - t0:.0f} s "
              f"({e.calls} requests, {e.tokens:,} tokens)", flush=True)
        dense = [top(docs @ qv[i], 100) for i in range(len(questions))]
        systems = {key: dense, f"{key} + bm25": [fuse([d, w]) for d, w in zip(dense, lexical, strict=True)]}
        if "bm25" not in results:
            systems["bm25"] = lexical
        for name, ranked in systems.items():
            per_q = []
            for q, ranking in zip(questions, ranked, strict=True):
                g = grades(q, ws)
                per_q.append({"id": q["id"], "style": q["style"], **measures(ranking, g)})
                rankings.append({"system": name, "question": q["id"], "text": q["question"],
                                 "top": [{"unit": ws[j].id, "kind": ws[j].kind, "grade": g.get(j, 0),
                                          "text": ws[j].text[:200]} for j in ranking[:10]]})
            results[name] = per_q

    args.out.mkdir(parents=True, exist_ok=True)
    with (args.out / "rankings.jsonl").open("w", encoding="utf-8") as f:
        for r in rankings:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")
    lines = [f"# Retrieval: synthetic questions on {args.tree}", "",
             (f"{len(units):,} chunks, windows of {args.window} tokens with {args.overlap} of overlap; "
              f"{len(questions)} questions ({len(questions) // 2} literal, {len(questions) // 2} paraphrased)."), ""]
    for style in ("all", "literal", "paraphrase"):
        lines += [f"## {style.capitalize()} questions", "",
                  "| System | " + " | ".join(MEASURES) + " |", "|---|" + "---|" * len(MEASURES)]
        for name, per_q in results.items():
            rows = [r for r in per_q if style == "all" or r["style"] == style]
            cells = []
            for mname in MEASURES:
                mean, lo, hi = mean_ci([r[mname] for r in rows])
                cells.append(f"{mean:.2f} ({lo:.2f}–{hi:.2f})" if mname in ("hit@10", "mrr@10") else f"{mean:.2f}")
            lines.append(f"| {name} | " + " | ".join(cells) + " |")
        lines.append("")
    misses = defaultdict(list)
    for name, per_q in results.items():
        for r in per_q:
            if not r["hit@10"]:
                misses[r["id"]].append(name)
    lines += ["## Questions missed in the top 10", ""] + [
        f"- {qid}: {', '.join(names)}" for qid, names in sorted(misses.items())] + [""]
    (args.out / "report.md").write_text("\n".join(lines), encoding="utf-8")
    print("\n".join(lines))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
