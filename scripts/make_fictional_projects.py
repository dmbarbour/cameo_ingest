#!/usr/bin/env python3
"""Write the fictional projects and their questions (plan RE-10, `cameo_ingest.evaluation.fiction`).

    uv run python scripts/make_fictional_projects.py out/eval/fiction
    uv run python scripts/make_fictional_projects.py --versions out/sb/versions   # plan SB

Writes one .mdzip per project (the same bytes every time) and DIR/questions.jsonl, every
project's questions, for `scripts/retrieval_eval.py --questions DIR/questions.jsonl`. Their
answers are known by construction, so they need no judging.
"""

from __future__ import annotations

import argparse
from collections import Counter
from pathlib import Path

from cameo_ingest.evaluation import records
from cameo_ingest.evaluation.fiction import ACROSS, PROJECTS
from cameo_ingest.evaluation.fiction.versions import VERSIONS, shared


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("dir", type=Path)
    ap.add_argument("--only", nargs="+", choices=sorted(PROJECTS), help="only these projects (by prefix)")
    ap.add_argument("--versions", action="store_true",
                    help="write the versions of fictional projects instead (plan SB): no questions")
    args = ap.parse_args()
    args.dir.mkdir(parents=True, exist_ok=True)
    if args.versions:
        for name, (base, build) in VERSIONS.items():
            v = build()
            (args.dir / v.path).parent.mkdir(parents=True, exist_ok=True)
            (args.dir / v.path).write_bytes(v.mdzip())
            a, b = shared(PROJECTS[base](), v)
            print(f"{v.path}: {name}, a version of {base}: {a:.0%} of its ids, {b:.0%} of the version's, shared")
        return 0
    questions = []
    for prefix in args.only or PROJECTS:
        project = PROJECTS[prefix]()
        (args.dir / project.path).parent.mkdir(parents=True, exist_ok=True)  # same-named files, in folders
        (args.dir / project.path).write_bytes(project.mdzip())
        qs = project.questions()
        questions += qs
        levels = Counter(q["difficulty"] for q in qs if q["style"] == "literal")
        print(f"{project.path}: {len(project.mdzip()) // 1024} KB, {len(project.layouts)} diagrams, "
              f"{len(qs)} questions ({', '.join(f'{n} {d}' for d, n in sorted(levels.items()))} facts)")
    if not args.only:
        questions += ACROSS()
    records.write_jsonl(args.dir / "questions.jsonl", questions)
    print(f"{len(questions)} questions in {args.dir / 'questions.jsonl'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
