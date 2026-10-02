#!/usr/bin/env python3
"""Run retrieval over an output tree for a set of questions, and report how often the answers
come back (plan RE-05).

    uv run --group eval python scripts/retrieval_eval.py out/all --env .env --models e5-large minilm \\
        --out out/eval/retrieval/synthetic

The questions (`--questions`) are the synthetic project's (`cameo_ingest.evaluation.synthetic`),
the structural ones about the samples (`cameo_ingest.evaluation.questions`), or a JSONL file of
any form, such as written questions (`scripts/write_questions.py`). All are graded by
construction (written questions only for their source chunk, until the judges grade the rest):
- **2:** a window of a chunk about an answering element, or, for the synthetic project, a window
  of it that holds the planted fact (a ledger or summary quoting it, say): what RAG needs;
- **1:** a window of a chunk about a related element.

Each model's windows are embedded through the cache (`--cache`), so a rerun, or a run cut off,
costs only what is missing. Writes OUT/report.md and OUT/rankings.jsonl (each question's top 10
per system, for inspection).
"""

from __future__ import annotations

import argparse
import json
import re
import time
from collections import Counter, defaultdict
from pathlib import Path

from cameo_ingest.cli import load_env
from cameo_ingest.evaluation.embed import MODELS, Embedder, EmbeddingCache
from cameo_ingest.evaluation.harness import (
    BM25,
    Unit,
    chunk_units,
    fuse,
    group_measures,
    mean_ci,
    measures,
    top,
    windowed,
)
from cameo_ingest.evaluation.judge import consensus
from cameo_ingest.evaluation.questions import _plain, structural
from cameo_ingest.evaluation.rerank import RERANKERS, Reranker
from cameo_ingest.evaluation.synthetic import QUESTIONS, holds

SYNTHETIC = "_kois_"  # the synthetic project's element ids start so
MEASURES = ("hit@1", "hit@5", "hit@10", "hit@20", "mrr@10", "ndcg@10", "coverage@10", "complete@10")


def _norm(text: str) -> str:
    """Letters and digits only, in lower case: a quote and a window compared whatever their
    markup (Markdown on the pages, the plain chunk style)."""
    return re.sub(r"[^a-z0-9]+", " ", text.lower()).strip()


def grades(q: dict, units: list[Unit], judged: dict[str, int] | None = None) -> dict[int, int]:
    """Grades by construction, overridden by the judge panel's where it judged (`judged`: unit ->
    grade, for this question)."""
    out = {}
    quote = _norm(q.get("quote", ""))
    sources = set(q.get("answer_chunks", ()))
    if sources and not any(u.id.split("#w")[0] in sources for u in units):
        # Another corpus (another chunk style): the source element's chunks stand in for the source chunk.
        sources = {u.id.split("#w")[0] for u in units if u.element_id and u.element_id == q.get("source_element")}
    for i, u in enumerate(units):
        if u.id.split("#w")[0] in sources:  # a written question's source chunk
            out[i] = 2 if quote and quote in _norm(_plain(u.text)) else 1  # the window with the quote
        elif "evidence_groups" in q:  # an answer in parts (one per model): a window with any part answers
            if any(holds(g, u.text) for g in q["evidence_groups"]):
                out[i] = 2
        elif "prefix" in q:  # a fictional project's: only a window that holds the fact answers
            # (an index entry, which spans projects, too: the fictional phrases occur nowhere else)
            if ((u.element_id or "").startswith(q["prefix"]) or u.kind == "index:id") and (
                    holds(q["evidence"], u.text)
                    or holds(q.get("evidence_by_element", {}).get(u.element_id, []), u.text)):
                out[i] = 2
            elif u.element_id in q["answers"] or u.element_id in q["related"]:
                out[i] = 1
        elif u.element_id in q["answers"] or (
                "evidence" in q and (u.element_id or "").startswith(SYNTHETIC) and holds(q["evidence"], u.text)):
            out[i] = 2  # about an answering element, or holding the planted fact (a ledger quoting it, say)
        elif u.element_id in q["related"]:
            out[i] = 1
    if judged:
        for i, u in enumerate(units):
            if u.id in judged:
                out[i] = judged[u.id]
                if not out[i]:
                    del out[i]
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
    ap.add_argument("--bm25-weights", nargs="*", type=float, default=[],
                    help="also fuse each dense model with BM25 at these weights (1 is the plain hybrid)")
    ap.add_argument("--rerank", choices=list(RERANKERS), help="also rerank every system's top --rerank-depth with "
                                                               "this reranker on DeepInfra (plan RF-02)")
    ap.add_argument("--rerank-depth", type=int, default=30)
    ap.add_argument("--rerank-cache", type=Path, default=Path("out/eval/rerank.sqlite"))
    ap.add_argument("--without-details", action="store_true",
                    help="leave the plain style's details chunks out of the index, as if they were in a file apart")
    ap.add_argument("--questions", default="synthetic", help="synthetic, structural, or a JSONL file of questions")
    ap.add_argument("--judgments", type=Path, help="the judge panel's grades (scripts/judge_pools.py), which override "
                                                   "construction except for the synthetic questions")
    ap.add_argument("--judges", nargs=2, default=["deepseek-ai/DeepSeek-V3.2", "Qwen/Qwen3-235B-A22B-Instruct-2507"])
    ap.add_argument("--tiebreak", default="moonshotai/Kimi-K2-Instruct-0905",
                    help="the judge that settles the main judges' disagreements; none: take the lower grade")
    args = ap.parse_args()
    if args.env:
        load_env(args.env)
    units = chunk_units(args.tree)
    if args.project:
        units = [u for u in units if (u.element_id or "").startswith(args.project)]
    if args.without_details:
        units = [u for u in units if not u.kind.endswith(":details")]
    cache = EmbeddingCache(args.cache)
    if args.questions == "synthetic":
        questions = QUESTIONS
    elif args.questions == "structural":
        questions = structural(args.tree)
    else:
        questions = [json.loads(line) for line in Path(args.questions).read_text(encoding="utf-8").splitlines()]
    print(f"{len(units):,} chunks from {args.tree}; {len(questions)} questions")
    judged_of: dict[str, dict[str, int]] = defaultdict(dict)  # question -> unit -> grade
    if args.judgments and args.questions != "synthetic":
        name = Path(args.questions).stem if args.questions != "structural" else "structural"
        panel = consensus([json.loads(line) for line in args.judgments.read_text(encoding="utf-8").splitlines()],
                          tuple(args.judges), None if args.tiebreak == "none" else args.tiebreak)
        for (s, qid, unit), grade in panel.items():
            if s == name:
                judged_of[qid][unit] = grade
        print(f"judged grades for {len(judged_of)} questions")

    results: dict[str, list[dict]] = {}  # system -> per-question measures
    rankings = []
    ws = windowed(units, args.window_tokenizer, args.window, args.overlap)
    bm25 = BM25([u.text for u in ws])
    lexical = [top(bm25.scores(q["question"]), 100) for q in questions]
    print(f"{len(ws):,} windows", flush=True)
    systems: dict[str, list[list[int]]] = {"bm25": lexical}
    for key in args.models:
        m = MODELS[key]
        t0 = time.perf_counter()
        e = Embedder(m, cache, concurrency=args.concurrency)
        docs = e.embed([u.text for u in ws], "passage")
        qv = e.embed([q["question"] for q in questions], "query")
        print(f"{key}: embedded in {time.perf_counter() - t0:.0f} s "
              f"({e.calls} requests, {e.tokens:,} tokens)", flush=True)
        dense = [top(docs @ qv[i], 100) for i in range(len(questions))]
        systems[key] = dense
        systems[f"{key} + bm25"] = [fuse([d, w]) for d, w in zip(dense, lexical, strict=True)]
        for weight in args.bm25_weights:
            systems[f"{key} + bm25×{weight:g}"] = [fuse([d, w], weights=[1.0, weight])
                                                   for d, w in zip(dense, lexical, strict=True)]
    if args.rerank:
        t0 = time.perf_counter()
        reranker = Reranker(args.rerank, args.rerank_cache, concurrency=args.concurrency)
        texts = [u.text for u in ws]
        reranker.scores(list({(q["question"], texts[j]) for ranked in systems.values()  # every pair at once
                              for q, r in zip(questions, ranked, strict=True) for j in r[:args.rerank_depth]}))
        for name in list(systems):
            systems[f"{name} → {args.rerank}"] = [reranker.rerank(q["question"], r, texts, args.rerank_depth)
                                                  for q, r in zip(questions, systems[name], strict=True)]
        print(f"{reranker.model}: {reranker.calls} requests, {reranker.tokens:,} tokens, "
              f"{time.perf_counter() - t0:.0f} s", flush=True)
    for name, ranked in systems.items():
        per_q = []
        for q, ranking in zip(questions, ranked, strict=True):
            g = grades(q, ws, judged_of.get(q["id"]))
            if "evidence_groups" in q:
                parts = q["evidence_groups"]
                covers = {i: frozenset(k for k, grp in enumerate(parts) if holds(grp, ws[i].text)) for i in g}
            else:
                parts, covers = [[]], {i: frozenset([0]) for i, v in g.items() if v == 2}
            per_q.append({"id": q["id"], "style": q["style"], "difficulty": q.get("difficulty"),
                          "project_name": q.get("project_name"), **measures(ranking, g),
                          **group_measures(ranking, covers, len(parts))})
            rankings.append({"system": name, "question": q["id"], "text": q["question"],
                             "top": [{"unit": ws[j].id, "kind": ws[j].kind, "grade": g.get(j, 0),
                                      "text": ws[j].text[:200]} for j in ranking[:10]]})
        results[name] = per_q

    args.out.mkdir(parents=True, exist_ok=True)
    with (args.out / "rankings.jsonl").open("w", encoding="utf-8") as f:
        for r in rankings:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")
    with (args.out / "per_question.jsonl").open("w", encoding="utf-8") as f:  # every measure, for analysis
        for name, per_q in results.items():
            for r in per_q:
                f.write(json.dumps({"system": name, **r}, ensure_ascii=False) + "\n")
    styles = Counter(q["style"] for q in questions)
    lines = [f"# Retrieval: {args.questions} questions on {args.tree}", "",
             (f"{len(units):,} chunks, windows of {args.window} tokens with {args.overlap} of overlap; "
              f"{len(questions)} questions ({', '.join(f'{n} {s}' for s, n in sorted(styles.items()))})."), ""]
    groups = [("all", None)]  # all questions, then by style, difficulty and project where they differ
    for field in ("style", "difficulty", "project_name"):
        values = sorted({str(q.get(field)) for q in questions if q.get(field)})
        groups += [(v, field) for v in values] if len(values) > 1 else []
    for group, field in groups:
        lines += [f"## {group.capitalize() if field != 'project_name' else group} questions", "",
                  "| System | " + " | ".join(MEASURES) + " |", "|---|" + "---|" * len(MEASURES)]
        for name, per_q in results.items():
            rows = [r for r in per_q if field is None or str(r.get(field)) == group]
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
