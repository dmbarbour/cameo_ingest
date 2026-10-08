#!/usr/bin/env python3
"""Judge splits into subjects with a panel (plan SB-03, SB-04).

    uv run --extra eval python scripts/judge_subjects.py out/sb/splits --env .env --out out/sb/judged \\
        [--splits R P G T] [--families 12] [--tests E1 E2 E3]

Reads OUT/splits.json from `subject_splits.py`, picks the families to judge (the largest, then
every other by size, so that sizes vary), asks each judge, and writes OUT/judgments.jsonl and
OUT/report.md: E1's accuracy and E2's chance-corrected accuracy by split and judge, the judges'
agreement, and E3's preferences by pair.
"""

from __future__ import annotations

import argparse
import json
from collections import Counter
from pathlib import Path

from cameo_ingest.cli import load_env
from cameo_ingest.evaluation import records
from cameo_ingest.evaluation.judge import PANEL, both_orders, kappa_lines
from cameo_ingest.evaluation.provider import chat_config
from cameo_ingest.evaluation.subject_judges import intruder_tasks, label_tasks, pick, preference_tasks, run
from cameo_ingest.llm import EnrichmentSession, connect


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("splits_dir", type=Path)
    ap.add_argument("--env", type=Path)
    ap.add_argument("--out", type=Path, required=True)
    ap.add_argument("--splits", nargs="+", default=["R", "P", "G", "T"])
    ap.add_argument("--families", type=int, default=12)
    ap.add_argument("--tests", nargs="+", default=["E1", "E2", "E3"])
    ap.add_argument("--e3-splits", nargs="+", help="the splits E3 pairs (default: --splits)")
    ap.add_argument("--judges", nargs="+", default=PANEL)
    ap.add_argument("--concurrency", type=int, default=8)
    args = ap.parse_args()
    if args.env:
        load_env(args.env)
    args.out.mkdir(parents=True, exist_ok=True)
    recs = pick(json.loads((args.splits_dir / "splits.json").read_text()), args.families)
    by_family = {r["family"]: r for r in recs}
    tasks = []
    for r in recs:
        for s in args.splits:
            if "E1" in args.tests:
                tasks += intruder_tasks(r, s)
            if "E2" in args.tests:
                tasks += label_tasks(r, s)
        if "E3" in args.tests:
            tasks += preference_tasks(r, args.e3_splits or args.splits)
    print(f"{len(recs)} families: {', '.join(r['family'] for r in recs)}")
    print(f"{len(tasks):,} tasks a judge: {dict(Counter(t['test'] for t in tasks))}")
    results = []
    for model in args.judges:
        cfg = chat_config(model, timeout=180, retries=8)
        llm = EnrichmentSession(cfg, args.out / "store", connect(cfg), max_failures=None)
        for j in run(llm, by_family, tasks, args.concurrency):
            results.append({**j, "judge": model})
        print(f"{model}: done")
    records.write_jsonl(args.out / "judgments.jsonl", results)
    report = summarize(results, args.splits, args.judges)
    (args.out / "report.md").write_text(report, encoding="utf-8")
    print(report)
    return 0


def summarize(results: list[dict], splits: list[str], judges: list[str]) -> str:
    lines = ["# Splits judged (plan SB)", ""]
    for test, title, chance in (("E1", "E1, intruder: share found (chance 17%)", True),
                                ("E2", "E2, label fit: chance-corrected agreement", False)):
        rows = [r for r in results if r["test"] == test]
        if not rows:
            continue
        lines += [f"## {title}", "", "| Split | " + " | ".join(j.split("/")[-1] for j in judges) + " | All | Unread |",
                  "|---|" + "---|" * (len(judges) + 2)]
        for s in splits:
            cells, every = [], []
            for j in judges:
                got = [r for r in rows if r["split"] == s and r["judge"] == j and r["correct"] is not None]
                cells.append(_score(got, test))
                every += got
            unread = sum(1 for r in rows if r["split"] == s and r["correct"] is None)
            lines.append(f"| {s} | " + " | ".join(cells) + f" | {_score(every, test)} | {unread} |")
        lines += ["", "Agreement between judges on each task's outcome (kappa):", ""]
        lines += kappa_lines(rows, judges, _key)
        lines.append("")
    rows = [r for r in results if r["test"] == "E3"]
    if rows:
        lines += ["## E3, preference: verdicts given in both orders, every judge and family", "",
                  "| Pair | First preferred | Second preferred | Tie | Inconsistent (the order decided) |",
                  "|---|---|---|---|---|"]
        for pair in sorted({r["pair"] for r in rows}):
            a, b = pair.split("-")
            c = both_orders([r for r in rows if r["pair"] == pair], lambda r: (r["judge"], r["family"]))
            lines.append(f"| {a} vs {b} | {c[a]} | {c[b]} | {c['tie']} | {c['inconsistent']} |")
        first = sum(1 for r in rows if r["better"] == r["A"]) / len(rows)
        lines += ["", f"The split shown first was preferred in {first:.0%} of answers."]
        for j in judges:
            rr = [r for r in rows if r["judge"] == j]
            if rr:
                lines.append(f"- {j.split('/')[-1]}: {sum(1 for r in rr if r['better'] == r['A']) / len(rr):.0%}")
        lines.append("")
    return "\n".join(lines)


def _key(r: dict) -> tuple:
    return (r["test"], r["family"], r["split"], r.get("group"), r.get("trial"), r.get("key"))


def _score(rows: list[dict], test: str) -> str:
    if not rows:
        return "-"
    acc = sum(r["correct"] for r in rows) / len(rows)
    if test == "E1":
        return f"{acc:.0%} ({len(rows)})"
    chance = sum(1 / r["groups"] for r in rows) / len(rows)
    return f"{(acc - chance) / (1 - chance):.2f} ({len(rows)})"


if __name__ == "__main__":
    raise SystemExit(main())
