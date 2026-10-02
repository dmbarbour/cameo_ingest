#!/usr/bin/env python3
"""Write the retrieval evaluation's questions about the samples (plan RE-04).

    uv run python scripts/write_questions.py out/all --env .env --model deepseek-ai/DeepSeek-V3.2 --out out/eval/questions

Writes OUT/structural.jsonl (from the models' structure, no LLM), OUT/natural.jsonl (one question
per sampled chunk, written by --model and kept only if its quote is in the chunk), and
OUT/spot-check.md: a random sample of both, with their answers, for the maintainer to check
for sense.
"""

from __future__ import annotations

import argparse
import json
import random
from pathlib import Path

from cameo_ingest.cli import load_env
from cameo_ingest.evaluation.provider import chat_config
from cameo_ingest.evaluation.questions import natural, structural
from cameo_ingest.llm import EnrichmentSession, connect


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("tree", type=Path)
    ap.add_argument("--env", type=Path)
    ap.add_argument("--model", default="deepseek-ai/DeepSeek-V3.2")
    ap.add_argument("--out", type=Path, required=True)
    ap.add_argument("--per-project", type=int, default=6)
    ap.add_argument("--sample", type=int, default=30, help="questions in the spot-check page")
    args = ap.parse_args()
    if args.env:
        load_env(args.env)
    args.out.mkdir(parents=True, exist_ok=True)
    cfg = chat_config(args.model)
    llm = EnrichmentSession(cfg, args.out / ".cache", connect(cfg))
    sets = {"structural": structural(args.tree), "natural": natural(args.tree, llm, args.per_project)}
    for name, qs in sets.items():
        with (args.out / f"{name}.jsonl").open("w", encoding="utf-8") as f:
            for q in qs:
                f.write(json.dumps(q, ensure_ascii=False) + "\n")
        print(f"{name}: {len(qs)} questions")

    chunks = {}
    for line in (args.tree / "chunks.jsonl").open(encoding="utf-8"):
        c = json.loads(line)
        chunks[c["id"]] = c
        if c["metadata"].get("element_id"):
            chunks.setdefault(c["metadata"]["element_id"], c)
    rng = random.Random(1)
    picked = rng.sample(sets["structural"], min(args.sample // 2, len(sets["structural"])))
    picked += rng.sample(sets["natural"], min(args.sample - len(picked), len(sets["natural"])))
    lines = ["# Questions to spot-check", "",
             ("For each question: does it make sense, would someone plausibly ask it, and does the answer below "
             "answer it? Mark any that fail with a note; they point to faults in the generators."), ""]
    for n, q in enumerate(picked, 1):
        source = chunks.get((q.get("answer_chunks") or q["answers"])[0], {})
        lines += [f"## {n}. {q['question']}", "",
                  f"- **Kind:** {q['template']}; project `{q['project'][:23]}`; answer: {source.get('title', '?')}"]
        if q.get("quote"):
            lines.append(f"- **Answering quote:** \"{q['quote']}\"")
        lines += ["", "```", source.get("text", "")[:700], "```", "", "Makes sense? Comment:", ""]
    (args.out / "spot-check.md").write_text("\n".join(lines), encoding="utf-8")
    print(f"spot-check page: {args.out / 'spot-check.md'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
