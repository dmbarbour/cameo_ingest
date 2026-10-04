#!/usr/bin/env python3
"""Compare two retrieval runs question by question: each measure's change, with a paired
bootstrap interval, for every system both ran.

    uv run --extra eval python scripts/compare_retrieval.py out/sk/retrieval-ref out/sk/retrieval-new \\
        --out out/sk/comparison.md

BEFORE and AFTER are `retrieval_eval.py` output directories (their `per_question.jsonl`). Prints
the comparison as Markdown, and writes it to `--out` when given. Exits 1 when a measure changed
significantly, so that a release check can stop on it. The work is the library's
(`cameo_ingest.evaluation.report.compare`); this script holds the arguments.
"""

from __future__ import annotations

import argparse
from pathlib import Path

from cameo_ingest.evaluation import records, report


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("before", type=Path, help="the reference run's directory")
    ap.add_argument("after", type=Path, help="the new run's directory")
    ap.add_argument("--out", type=Path, help="also write the comparison here")
    ap.add_argument("--rounds", type=int, default=4000, help="bootstrap rounds (default 4000)")
    args = ap.parse_args()
    c = report.compare(records.read_jsonl(args.before / records.PER_QUESTION),
                       records.read_jsonl(args.after / records.PER_QUESTION), args.rounds)
    text = report.render_comparison(c, str(args.before), str(args.after))
    print(text)
    if args.out:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(text, encoding="utf-8")
    return 1 if c.significant() else 0


if __name__ == "__main__":
    raise SystemExit(main())
