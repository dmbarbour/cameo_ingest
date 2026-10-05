#!/usr/bin/env python3
"""Run retrieval over an output tree for a set of questions, and report how often the answers
come back (plan RE-05).

    uv run --extra eval python scripts/retrieval_eval.py out/all --env .env --models e5-large minilm \\
        --questions out/eval/fiction/questions.jsonl --out out/eval/retrieval/fiction

The questions (`--questions`) are the structural ones about the samples
(`cameo_ingest.evaluation.questions`), or a JSONL file of any form: the fictional projects'
(`scripts/make_fictional_projects.py`), or written questions (`scripts/write_questions.py`).
All are graded by construction, each by its rule (`cameo_ingest.evaluation.grading`), and the
judge panel's grades override construction where it judged (`--judgments`).

Each model's windows are embedded through the cache (`--cache`), so a rerun, or a run cut off,
costs only what is missing. Writes OUT/report.md, OUT/rankings.jsonl (each question's top 10 per
system, for inspection), OUT/per_question.jsonl (every measure) and OUT/run.json (how the
windows were cut, for `judge_pools`). The work is the library's (`cameo_ingest.evaluation`:
`systems`, `grading`, `report`, `records`); this script holds the arguments.
"""

from __future__ import annotations

import argparse
from pathlib import Path

from cameo_ingest.cli import load_env
from cameo_ingest.evaluation import records, report, systems
from cameo_ingest.evaluation.embed import MODELS, EmbeddingCache
from cameo_ingest.evaluation.grading import Corpus, grade_all
from cameo_ingest.evaluation.judge import panel
from cameo_ingest.evaluation.rerank import RERANKERS


def say(text: str) -> None:
    print(text, flush=True)


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
    ap.add_argument("--bm25-weights", nargs="*", type=float, default=[],
                    help="also fuse each dense model with BM25 at these weights (1 is the plain hybrid)")
    ap.add_argument("--rerank", choices=list(RERANKERS), help="also rerank every system's top --rerank-depth with "
                                                               "this reranker on DeepInfra (plan RF-02)")
    ap.add_argument("--rerank-depth", type=int, default=30)
    ap.add_argument("--rerank-cache", type=Path, default=Path("out/eval/rerank.sqlite"))
    ap.add_argument("--rag", action="store_true",
                    help="the chunks as rag/ presents them (each file's text, its source line included), not as "
                         "chunks.jsonl holds them")
    ap.add_argument("--without-details", action="store_true",
                    help="leave the plain style's details chunks out of the index, as if they were in a file apart")
    ap.add_argument("--pages", action="store_true",
                    help="the tree's Markdown pages, cut into windows as a stack pointed at the tree would cut them; "
                         "with --rag, beside rag/'s files, as a stack pointed at the whole tree reads its text (plan RM-05)")
    ap.add_argument("--without", nargs="+", default=[], metavar="KIND",
                    help="leave chunks of these kinds out of the index, as globs: ledger:* generated:* (plan RM-01)")
    ap.add_argument("--questions", required=True, help="structural, or a JSONL file of questions")
    ap.add_argument("--judgments", type=Path, help="the judge panel's grades (scripts/judge_pools.py), which override "
                                                   "construction")
    ap.add_argument("--judges", nargs=2, default=["deepseek-ai/DeepSeek-V3.2", "Qwen/Qwen3-235B-A22B-Instruct-2507"])
    ap.add_argument("--tiebreak", default="moonshotai/Kimi-K2-Instruct-0905",
                    help="the judge that settles the main judges' disagreements; none: take the lower grade")
    args = ap.parse_args()
    if args.env:
        load_env(args.env)
    run = records.Run(str(args.tree), args.questions, args.rag, args.project, args.without_details,
                      args.window_tokenizer, args.window, args.overlap, tuple(args.without), args.pages)
    units = run.units()
    questions = records.questions(args.questions, args.tree)
    print(f"{len(units):,} chunks from {args.tree}" + (f", without {' '.join(run.without)}" if run.without else "")
          + f"; {len(questions)} questions")
    judged = {}
    if args.judgments:
        judged = panel(records.read_jsonl(args.judgments), records.set_name(args.questions), tuple(args.judges),
                       None if args.tiebreak == "none" else args.tiebreak)
        print(f"judged grades for {len(judged)} questions")

    ws = run.windows(units)
    ranked = systems.build(ws, questions, args.models, EmbeddingCache(args.cache), concurrency=args.concurrency,
                           bm25_weights=args.bm25_weights, rerank=args.rerank, rerank_depth=args.rerank_depth,
                           rerank_cache=args.rerank_cache, say=say)
    results, rankings = report.per_question(ranked, questions, ws, grade_all(questions, Corpus(ws), judged))

    run.write(args.out)  # how the windows were cut, for the judges (AR-020R2)
    records.write_jsonl(args.out / records.RANKINGS, rankings)
    records.write_jsonl(args.out / records.PER_QUESTION, report.rows(results))
    text = report.render(results, questions, run, len(units))
    (args.out / records.REPORT).write_text(text, encoding="utf-8")
    print(text)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
