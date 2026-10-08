#!/usr/bin/env python3
"""Topics across models (plan SB-08b, SB-08c): gather a tree's subjects into topics by words and
by the LLM, on the whole tree and on subsets of its families, then judge them with the panel.

    uv run --extra eval python scripts/topic_splits.py TREE --env .env --out out/sb/topics \\
        [--model google/gemma-4-31B-it] [--store out/sb/llm-splits-store] [--collections 9]

The methods, on each collection:
- **W:** `topics.words_view`, words and shared elements between families;
- **L:** `topics.llm_view`, the tree's text model proposing topics and placing each subject;
- **R:** random topics, as many as W's, for sanity (E1 at chance);
- **M:** each model its own topic: coherent but no use across models, to see what E1 rewards.

Writes OUT/topics.json (every collection's splits), OUT/topics.md (the whole tree's topics by
each method), OUT/judgments.jsonl and OUT/report.md.
"""

from __future__ import annotations

import argparse
import json
import random
from collections import Counter
from pathlib import Path

from cameo_ingest import subjects, topics
from cameo_ingest.cli import load_env
from cameo_ingest.evaluation import records
from cameo_ingest.evaluation.judge import PANEL, kappa_lines
from cameo_ingest.evaluation.provider import chat_config
from cameo_ingest.evaluation.topic_judges import (
    as_split,
    collections,
    intruder_tasks,
    measures,
    preference_tasks,
    run,
    verdicts,
)
from cameo_ingest.llm import EnrichmentSession, connect
from cameo_ingest.state import State

METHODS = ["W", "L", "R", "M"]


def random_split(subs: list[topics.Subject], k: int, seed: str) -> dict:
    rng = random.Random(seed)
    ids = [s.id for s in subs]
    rng.shuffle(ids)
    groups: dict[str, list[str]] = {}
    for n, i in enumerate(ids):
        groups.setdefault(str(n % k), []).append(i)
    return {"labels": {t: f"Group {int(t) + 1}" for t in groups}, "groups": groups, "unsorted": []}


def model_split(subs: list[topics.Subject]) -> dict:
    groups: dict[str, list[str]] = {}
    labels: dict[str, str] = {}
    for s in subs:
        fam = s.family
        t = labels.setdefault(fam, str(len(labels)))
        groups.setdefault(t, []).append(s.id)
    names = {s.family: s.model for s in subs}
    return {"labels": {t: names[f] for f, t in labels.items()}, "groups": groups, "unsorted": []}


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("tree", type=Path)
    ap.add_argument("--env", type=Path)
    ap.add_argument("--out", type=Path, required=True)
    ap.add_argument("--model", default="google/gemma-4-31B-it")
    ap.add_argument("--store", type=Path, default=Path("out/sb/llm-splits-store"))
    ap.add_argument("--collections", type=int, default=9)
    ap.add_argument("--judges", nargs="+", default=PANEL)
    ap.add_argument("--no-judges", action="store_true")
    ap.add_argument("--concurrency", type=int, default=8)
    args = ap.parse_args()
    if args.env:
        load_env(args.env)
    args.out.mkdir(parents=True, exist_ok=True)
    st = State(args.tree)
    try:
        fams = subjects.families(st, args.tree)
    finally:
        st.close()
    subs = topics.subjects(fams, subjects.load(args.tree))
    cfg = chat_config(args.model, timeout=300, retries=8)
    proposer = EnrichmentSession(cfg, args.store, connect(cfg), max_failures=None)
    colls = {}
    for c in collections(subs, args.collections):
        ss = c["subjects"]
        by_id = {s.id: s for s in ss}
        w = as_split(topics.words_view(ss))
        lv = topics.llm_view(proposer, ss, args.concurrency)
        splits = {"W": w, "R": random_split(ss, len(w["groups"]), c["name"]), "M": model_split(ss)}
        if lv is not None:
            splits["L"] = as_split(lv)
        colls[c["name"]] = {"subjects": ss, "by_id": by_id, "splits": splits,
                            "measures": {n: measures(s, by_id) for n, s in splits.items()}}
        print(c["name"], len(ss), "subjects:", ", ".join(f"{n} {m['topics']} topics, {m['across']:.0%} across"
                                                         for n, m in colls[c["name"]]["measures"].items()), flush=True)
    (args.out / "topics.json").write_text(json.dumps(
        {n: {"subjects": [s.id for s in c["subjects"]], "splits": c["splits"], "measures": c["measures"]}
         for n, c in colls.items()}, ensure_ascii=False, indent=1), encoding="utf-8")
    page = ["# Topics across models: the whole study tree (plan SB-08b)", ""]
    whole = colls["all"]
    for name in ("L", "W"):
        if name not in whole["splits"]:
            continue
        s, m = whole["splits"][name], whole["measures"][name]
        page += [(f"## {name}: {m['topics']} topics, the largest {m['largest']:.0%}, {m['across']:.0%} of subjects in a "
                  f"topic across models, {m['families_per_topic']:.1f} models a topic"), ""]
        for t, ids in sorted(s["groups"].items(), key=lambda kv: -len(kv[1])):
            page.append(f"- **{s['labels'][t]}** ({len(ids)}): "
                        + "; ".join(f"{whole['by_id'][i].label} ({whole['by_id'][i].model})" for i in ids))
        if s["unsorted"]:
            page.append(f"- Not sorted yet: {len(s['unsorted'])}")
        page.append("")
    (args.out / "topics.md").write_text("\n".join(page), encoding="utf-8")
    if args.no_judges:
        return 0
    tasks = []
    for n, c in colls.items():
        for name, s in c["splits"].items():
            tasks += intruder_tasks(n, name, s)
        tasks += preference_tasks(n, [m for m in ("L", "W", "M") if m in c["splits"]])
    print(f"{len(tasks):,} tasks a judge: {dict(Counter(t['test'] for t in tasks))}")
    results = []
    for model in args.judges:
        jc = chat_config(model, timeout=180, retries=8)
        llm = EnrichmentSession(jc, args.out / "store", connect(jc), max_failures=None)
        results += [{**r, "judge": model} for r in run(llm, colls, tasks, args.concurrency)]
        print(f"{model}: done", flush=True)
    records.write_jsonl(args.out / "judgments.jsonl", results)
    report = summarize(results, colls, args.judges)
    (args.out / "report.md").write_text(report, encoding="utf-8")
    print(report)
    return 0


def summarize(results: list[dict], colls: dict, judges: list[str]) -> str:
    lines = ["# Topics across models, judged (plan SB-08c)", "", "## Measures, mean over collections", "",
             "| Method | Topics | Largest | Subjects in a topic across models | Models a topic | Unsorted |",
             "|---|---|---|---|---|---|"]
    for name in METHODS:
        ms = [c["measures"][name] for c in colls.values() if name in c["measures"]]
        if ms:
            mean = {k: sum(m[k] for m in ms) / len(ms) for k in ms[0]}
            lines.append(f"| {name} | {mean['topics']:.1f} | {mean['largest']:.0%} | {mean['across']:.0%} | "
                         f"{mean['families_per_topic']:.1f} | {mean['unsorted']:.1f} |")
    rows = [r for r in results if r["test"] == "E1"]
    lines += ["", "## E1, intruder: share found (chance 17%)", "",
              "| Method | " + " | ".join(j.split("/")[-1] for j in judges) + " | All | Unread |",
              "|---|" + "---|" * (len(judges) + 2)]
    for name in METHODS:
        cells, every = [], []
        for j in judges:
            got = [r for r in rows if r["split"] == name and r["judge"] == j and r["correct"] is not None]
            cells.append(_pct(got))
            every += got
        unread = sum(1 for r in rows if r["split"] == name and r["correct"] is None)
        lines.append(f"| {name} | " + " | ".join(cells) + f" | {_pct(every)} | {unread} |")
    lines += ["", "Agreement between judges (kappa):", "", *kappa_lines(rows, judges, _key)]
    rows = [r for r in results if r["test"] == "E3"]
    lines += ["", "## E3, preference: verdicts given in both orders, every judge and collection", "",
              "| Pair | First preferred | Second preferred | Tie | Inconsistent |", "|---|---|---|---|---|"]
    for pair in sorted({r["pair"] for r in rows}):
        a, b = pair.split("-")
        c = verdicts([r for r in rows if r["pair"] == pair])
        lines.append(f"| {a} vs {b} | {c[a]} | {c[b]} | {c['tie']} | {c['inconsistent']} |")
    if rows:
        first = sum(r["better"] == r["A"] for r in rows) / len(rows)
        lines += ["", f"The way shown first was preferred in {first:.0%} of answers."]
    return "\n".join(lines) + "\n"


def _key(r: dict) -> tuple:
    return (r["collection"], r["split"], r["group"], r["trial"])


def _pct(rows: list[dict]) -> str:
    return f"{sum(r['correct'] for r in rows) / len(rows):.0%} ({len(rows)})" if rows else "-"


if __name__ == "__main__":
    raise SystemExit(main())
