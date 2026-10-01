#!/usr/bin/env python3
"""Write the synthetic project and its questions (plan RE, `cameo_ingest.evaluation.synthetic`).

    uv run python scripts/make_synthetic_project.py out/eval/synthetic

Writes DIR/Kestrel_Orchard_Irrigation.mdzip (the same bytes every time) and DIR/questions.jsonl.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from cameo_ingest.evaluation.synthetic import QUESTIONS, make_mdzip


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("dir", type=Path)
    args = ap.parse_args()
    args.dir.mkdir(parents=True, exist_ok=True)
    (args.dir / "Kestrel_Orchard_Irrigation.mdzip").write_bytes(make_mdzip())
    with (args.dir / "questions.jsonl").open("w", encoding="utf-8") as f:
        for q in QUESTIONS:
            f.write(json.dumps(q) + "\n")
    print(f"wrote the project and {len(QUESTIONS)} questions to {args.dir}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
