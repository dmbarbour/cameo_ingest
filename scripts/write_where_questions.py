#!/usr/bin/env python3
"""Write questions about where something is described, by a panel of writers (plan GS-08).

    uv run python scripts/write_where_questions.py out/v020/on --env .env --out out/eval/where

Picks targets from the tree's extracted chunks (`evaluation.questions.where_targets`: packages,
diagrams and behaviors, from the fiction and the samples, mostly undocumented ones), and has each
writer (`--writers`) write a literal question and a paraphrase for every target, from its
extracted text only. Writes OUT/questions-where.jsonl (graded by element), OUT/targets.jsonl and
OUT/spot-check.md, each target with its questions, for reading. Answers are cached in OUT/.cache.
"""

from __future__ import annotations

import argparse
from collections import defaultdict
from pathlib import Path

from cameo_ingest.cli import load_env
from cameo_ingest.evaluation import records
from cameo_ingest.evaluation.provider import chat_config
from cameo_ingest.evaluation.questions import where_questions, where_targets
from cameo_ingest.llm import EnrichmentSession, connect

WRITERS = ["deepseek-ai/DeepSeek-V3.2", "Qwen/Qwen3-235B-A22B-Instruct-2507", "openai/gpt-oss-120b"]


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("tree", type=Path)
    ap.add_argument("--env", type=Path)
    ap.add_argument("--writers", nargs="+", default=WRITERS)
    ap.add_argument("--fiction", type=int, default=20)
    ap.add_argument("--samples", type=int, default=40)
    ap.add_argument("--seed", type=int, default=1)
    ap.add_argument("--out", type=Path, required=True)
    args = ap.parse_args()
    if args.env:
        load_env(args.env)
    args.out.mkdir(parents=True, exist_ok=True)
    targets = where_targets(args.tree, args.fiction, args.samples, args.seed)
    questions = []
    for writer in args.writers:
        cfg = chat_config(writer, timeout=180, retries=8)
        qs = where_questions(targets, EnrichmentSession(cfg, args.out / ".cache", connect(cfg), max_failures=None), writer)
        print(f"{writer}: {len(qs)} questions for {len({q['fact'] for q in qs})} of {len(targets)} targets", flush=True)
        questions += qs
    records.write_jsonl(args.out / "questions-where.jsonl", questions)
    records.write_jsonl(args.out / "targets.jsonl", [{k: v for k, v in t.items() if k != "text"} for t in targets])
    by_target = defaultdict(list)
    for q in questions:
        by_target[q["fact"]].append(q)
    lines = [f"# Questions about where something is described ({len(questions)}, {len(targets)} targets)", ""]
    for t in targets:
        state = "documented" if t["documented"] else "undocumented"
        lines += [f"## {t['kind']} {t['qualified_name']} ({t['project']}; {t['origin']}; {state})", ""]
        lines += [f"- {q['writer'].split('/')[-1]}, {q['style']}: {q['question']}" for q in by_target[f"wq-{t['element_id']}"]]
        lines.append("")
    (args.out / "spot-check.md").write_text("\n".join(lines), encoding="utf-8")
    print(f"{len(questions)} questions in {args.out / 'questions-where.jsonl'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
