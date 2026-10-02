#!/usr/bin/env python3
"""Judge the pooled search results of the retrieval evaluation (plan RE-06).

    uv run --extra eval python scripts/judge_pools.py out/all --env .env \\
        --judges deepseek-ai/DeepSeek-V3.2 Qwen/Qwen3-235B-A22B-Instruct-2507

Pools every question's top 10 from every system (OUT_RETRIEVAL/<set>/rankings.jsonl), and has each
judge grade each pair once (answers cached in --cache). `--only-disagreements A B` judges only the
pairs that judges A and B graded differently (a tie-breaker). Writes --out (judgments.jsonl, all
judges so far) and prints, per judge: unreadable replies, agreement with the other judges
(Cohen's kappa), and two checks against what is known by construction:
- **known answers** (graded 2 by construction, in every set): how many the judge grades 2;
- **other projects** (passages from a project other than the question's, which can't answer it):
  how many the judge credits at all.
"""

from __future__ import annotations

import argparse
import json
from collections import Counter
from pathlib import Path

from cameo_ingest.cli import load_env
from cameo_ingest.evaluation.harness import chunk_units, windowed
from cameo_ingest.evaluation.judge import judge, kappa
from cameo_ingest.llm import LLM, LLMConfig


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("tree", type=Path)
    ap.add_argument("--env", type=Path)
    ap.add_argument("--retrieval", type=Path, default=Path("out/eval/retrieval"))
    ap.add_argument("--sets", nargs="+", default=["synthetic", "structural", "natural"])
    ap.add_argument("--judges", nargs="+", required=True)
    ap.add_argument("--only-disagreements", nargs=2, metavar=("A", "B"))
    ap.add_argument("--out", type=Path, default=Path("out/eval/judge/judgments.jsonl"))
    ap.add_argument("--cache", type=Path, default=Path("out/eval/judge/.cache"))
    ap.add_argument("--window-tokenizer", default="intfloat/multilingual-e5-large")
    ap.add_argument("--concurrency", type=int, default=6)
    ap.add_argument("--limit", type=int, help="only this many pairs (a trial)")
    args = ap.parse_args()
    if args.env:
        load_env(args.env)

    pairs: dict[tuple[str, str, str], dict] = {}
    for s in args.sets:
        for line in (args.retrieval / s / "rankings.jsonl").open(encoding="utf-8"):
            r = json.loads(line)
            for t in r["top"]:
                key = (s, r["question"], t["unit"])
                pairs.setdefault(key, {"set": s, "qid": r["question"], "question": r["text"], "unit": t["unit"],
                                       "known": t["grade"]})
    windows = windowed(chunk_units(args.tree), args.window_tokenizer)
    texts = {u.id: u.text for u in windows}
    project_of_unit = {u.id: u.project for u in windows}
    project_of_question = {}  # the synthetic project's, or as the question names it
    synthetic = next((u.project for u in windows if (u.element_id or "").startswith("_kois_")), None)
    for s in args.sets:
        if s == "synthetic":
            continue
        path = Path("out/eval/questions") / f"{s}.jsonl"
        if path.is_file():
            for line in path.read_text(encoding="utf-8").splitlines():
                q = json.loads(line)
                project_of_question[q["id"]] = q.get("project")
    todo = [{**p, "text": texts[p["unit"]]} for p in pairs.values()]
    if args.limit:
        todo = todo[:args.limit]

    old = [json.loads(line) for line in args.out.open(encoding="utf-8")] if args.out.is_file() else []
    grade_of = {(j["judge"], j["set"], j["qid"], j["unit"]): j["grade"] for j in old}
    if args.only_disagreements:
        a, b = args.only_disagreements
        todo = [p for p in todo if grade_of.get((a, p["set"], p["qid"], p["unit"]))
                != grade_of.get((b, p["set"], p["qid"], p["unit"]))]
    print(f"{len(pairs):,} pairs pooled; {len(todo):,} to judge")

    for model in args.judges:
        # Patient: a busy endpoint (HTTP 429) is waited out with retries, never a reason to stop.
        llm = LLM(LLMConfig.from_env(model, None, timeout=180, retries=8), args.cache, max_failures=10**9)
        done = [p for p in todo if grade_of.get((model, p["set"], p["qid"], p["unit"])) is None]
        redo = {(model, p["set"], p["qid"], p["unit"]) for p in done}
        old = [j for j in old if (j["judge"], j["set"], j["qid"], j["unit"]) not in redo]  # failed before
        for j in judge(llm, done, args.concurrency):
            j["judge"] = model
            old.append(j)
            grade_of[(model, j["set"], j["qid"], j["unit"])] = j["grade"]
        print(f"{model}: judged {len(done):,} ({llm.calls} requests, "
              f"{sum(1 for j in old if j['judge'] == model and j['grade'] is None)} without a grade)", flush=True)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    with args.out.open("w", encoding="utf-8") as f:
        for j in old:
            f.write(json.dumps(j, ensure_ascii=False) + "\n")

    judges = sorted({j["judge"] for j in old})
    by_pair: dict[tuple[str, str, str], dict[str, int | None]] = {}
    for j in old:
        by_pair.setdefault((j["set"], j["qid"], j["unit"]), {})[j["judge"]] = j["grade"]
    def question_project(j: dict) -> str | None:
        return synthetic if j["set"] == "synthetic" else project_of_question.get(j["qid"])

    print("\n| judge | judged | unreadable | grades 0/1/2 | known answers graded 2 | other projects credited |")
    print("|---|---|---|---|---|---|")
    for m in judges:
        mine = [j for j in old if j["judge"] == m and j["grade"] is not None]
        counts = Counter(j["grade"] for j in old if j["judge"] == m)
        known = [j["grade"] for j in mine if pairs.get((j["set"], j["qid"], j["unit"]), {}).get("known") == 2]
        other = [j["grade"] for j in mine if question_project(j)
                 and project_of_unit.get(j["unit"]) not in (None, question_project(j))]
        print(f"| {m} | {sum(counts.values()):,} | {counts[None]} | {counts[0]}/{counts[1]}/{counts[2]} "
              f"| {sum(g == 2 for g in known) / max(1, len(known)):.0%} of {len(known)} "
              f"| {sum(g > 0 for g in other) / max(1, len(other)):.1%} of {len(other)} |")
    for i, a in enumerate(judges):
        for b in judges[i + 1:]:
            both = [(g[a], g[b]) for g in by_pair.values() if g.get(a) is not None and g.get(b) is not None]
            if both:
                print(f"{a} vs {b}: {len(both):,} pairs, agree {sum(x == y for x, y in both) / len(both):.0%}, "
                      f"kappa {kappa([x for x, _ in both], [y for _, y in both]):.2f}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
