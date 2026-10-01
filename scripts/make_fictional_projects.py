#!/usr/bin/env python3
"""Write the fictional projects and their questions (plan RE-10, `cameo_ingest.evaluation.fiction`).

    uv run python scripts/make_fictional_projects.py out/eval/fiction

Writes one .mdzip per project (the same bytes every time) and DIR/questions.jsonl, every
project's questions, for `scripts/retrieval_eval.py --questions DIR/questions.jsonl`. Their
answers are known by construction, so they need no judging.
"""

from __future__ import annotations

import argparse
import json
from collections import Counter
from pathlib import Path

from cameo_ingest.evaluation.fiction import PROJECTS


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("dir", type=Path)
    ap.add_argument("--only", nargs="+", choices=sorted(PROJECTS), help="only these projects (by prefix)")
    args = ap.parse_args()
    args.dir.mkdir(parents=True, exist_ok=True)
    questions = []
    for prefix in args.only or PROJECTS:
        project = PROJECTS[prefix]()
        (args.dir / project.file_name).write_bytes(project.mdzip())
        qs = project.questions()
        questions += qs
        levels = Counter(q["difficulty"] for q in qs if q["style"] == "literal")
        print(f"{project.file_name}: {len(project.mdzip()) // 1024} KB, {len(project.layouts)} diagrams, "
              f"{len(qs)} questions ({', '.join(f'{n} {d}' for d, n in sorted(levels.items()))} facts)")
    with (args.dir / "questions.jsonl").open("w", encoding="utf-8") as f:
        for q in questions:
            f.write(json.dumps(q, ensure_ascii=False) + "\n")
    print(f"{len(questions)} questions in {args.dir / 'questions.jsonl'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
