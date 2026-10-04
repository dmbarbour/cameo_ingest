#!/usr/bin/env python3
"""Measure how evenly a text model reads inputs of rising length (plan TC-04), on the reading
cards of `cameo_ingest.textcal`: the summary probe (the real part request) and the facts probe.

    uv run python scripts/measure_text_reading.py --env .env --model google/gemma-4-31B-it \\
        --cache-dir out/tc/cache -o out/tc/gemma

Writes OUT/results.jsonl (each request, its reply and score) and OUT/summary.json (by length),
and prints the summary. Requests go through the store in `--cache-dir`, so a rerun asks nothing
it has asked. The work is the library's (`textcal`); this script holds the arguments.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import cameo_ingest
from cameo_ingest import textcal as tc
from cameo_ingest.cli import load_env
from cameo_ingest.llm import EnrichmentSession, LLMConfig, connect
from cameo_ingest.progress import Progress


def fifths(xs: list[float | None]) -> str:
    return " ".join("  -  " if x is None else f"{x:5.2f}" for x in xs)


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--env", type=Path)
    ap.add_argument("--model", required=True)
    ap.add_argument("--cache-dir", type=Path, required=True)
    ap.add_argument("-o", "--out", type=Path, required=True)
    ap.add_argument("--lengths", default=",".join(map(str, tc.LENGTHS)))
    ap.add_argument("--cards", type=int, default=tc.CARDS)
    ap.add_argument("--concurrency", type=int, default=4)
    ap.add_argument("--timeout", type=float, default=300)
    args = ap.parse_args()
    if args.env:
        load_env(args.env)
    cfg = LLMConfig.from_env(args.model, None, timeout=args.timeout)
    cfg.vision_model = None
    llm = EnrichmentSession(cfg, args.cache_dir, connect(cfg, None))
    cards = tc.cards(tuple(int(x) for x in args.lengths.split(",")), args.cards)
    results = tc.ask(llm, cards, args.concurrency, Progress(heartbeat=60))
    args.out.mkdir(parents=True, exist_ok=True)
    with (args.out / "results.jsonl").open("w", encoding="utf-8") as f:
        for r in results:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")
    summary = tc.summarize(results)
    (args.out / "summary.json").write_text(json.dumps({"model": args.model, "tool": cameo_ingest.__version__,
                                                       "by_length": summary}, indent=1), encoding="utf-8")
    print(f"{args.model}: {sum(r['asked'] for r in results)} of {len(results)} requests answered, "
          f"{llm.calls} sent")
    print("length  cards | named by fifth                  all   mid/ends | right by fifth                  all")
    for s in summary:
        mid = s["middle_over_ends"]
        print(f"{s['length']:6}  {s['cards']:5} | {fifths(s['named'])}  {s['named_all']:4.2f}  "
              f"{'  -  ' if mid is None else f'{mid:5.2f}'}    | {fifths(s['right'])}  {s['right_all']:4.2f}")


if __name__ == "__main__":
    main()
