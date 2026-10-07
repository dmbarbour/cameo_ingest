#!/usr/bin/env python3
"""Add the LLM's splits, L1 and L2 (plan SB-05), to a `subject_splits.py` output.

    uv run --extra eval python scripts/llm_splits.py out/sb/splits --env .env \\
        --model google/gemma-4-31B-it --store out/sb/llm-splits-store [--families 12]

Adds, to each judged family of OUT/splits.json (the same pick as `judge_subjects.py`), the splits
L1 (G's groups labelled by the model, alike merged) and L2a, L2b, L2c (the model's proposed ways,
every diagram assigned), with their measures; writes OUT/llm.md, each way's principle and groups.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from judge_subjects import pick

from cameo_ingest.cli import load_env
from cameo_ingest.evaluation.provider import chat_config
from cameo_ingest.evaluation.subject_llm import label_groups, propose
from cameo_ingest.evaluation.subjects import measures
from cameo_ingest.llm import EnrichmentSession, connect


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("splits_dir", type=Path)
    ap.add_argument("--env", type=Path)
    ap.add_argument("--model", default="google/gemma-4-31B-it")
    ap.add_argument("--store", type=Path, required=True)
    ap.add_argument("--families", type=int, default=12)
    args = ap.parse_args()
    if args.env:
        load_env(args.env)
    path = args.splits_dir / "splits.json"
    recs = json.loads(path.read_text())
    chosen = {r["family"] for r in pick(recs, args.families)}
    cfg = chat_config(args.model, timeout=300, retries=8)
    llm = EnrichmentSession(cfg, args.store, connect(cfg), max_failures=None)
    page = ["# The LLM's splits (plan SB-05)", ""]
    for rec in recs:
        if rec["family"] not in chosen:
            continue
        new = {"L1": label_groups(llm, rec), **propose(llm, rec)}
        for name, s in new.items():
            flat = {k: g for g, ks in s["groups"].items() for k in ks}
            s["measures"] = measures(flat)
            rec["splits"][name] = s
        page += [f"## {rec['family']}: {len(rec['items'])} diagrams, about {rec['k']} subjects", ""]
        for name, s in new.items():
            m = s["measures"]
            page.append(f"**{name}**" + (f", {s['principle']}" if s.get("principle") else "")
                        + f": {m['groups']} groups, the largest {m['largest']:.0%}"
                        + (f", {s['unassigned']} not assigned" if s.get("unassigned") else ""))
            for g, ks in sorted(s["groups"].items(), key=lambda kv: -len(kv[1])):
                page.append(f"- {s['labels'][g]} ({len(ks)})")
            page.append("")
        print(f"{rec['family']}: {', '.join(f'{n} {s['measures']['groups']}' for n, s in new.items())}", flush=True)
    path.write_text(json.dumps(recs, ensure_ascii=False, indent=1), encoding="utf-8")
    (args.splits_dir / "llm.md").write_text("\n".join(page), encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
