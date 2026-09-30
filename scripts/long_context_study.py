#!/usr/bin/env python3
"""Summarize whole large packages in one long request, with and without the task repeated
after the input, against summarizing them in parts (plan DV-06).

    uv run python scripts/long_context_study.py --env .env samples/TMT.mdzip ... --out DIR

For up to --sample packages per input whose text is --min to --max characters (8,000 to
100,000 tokens by default), asks for a summary three ways:
- long: package-summary@v2 with the whole text (no cut);
- long, sandwiched: package-summary@v3, the same with the task repeated after the text;
- parts: module-summary@v1 per part, then package-synthesis@v1, as the pipeline does.

Answers are cached in DIR/.cache. Writes DIR/whole.jsonl and DIR/whole-blind.md (the three
answers per package in random order, with the package's element names, for rating), and
prints, per way: words, Markdown, how many of the package's element names each answer
mentions, and which thirds of the package those names come from. Attention lost in the
middle of a long input, or drawn to its start or end, shows as a skew in the thirds.
"""

from __future__ import annotations

import argparse
import json
import random
import re
import statistics
import tempfile
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from cameo_ingest import pipeline as pl
from cameo_ingest.archive import discover
from cameo_ingest.cli import load_env
from cameo_ingest.emit import ProjectWriter
from cameo_ingest.llm import LLM, LLMConfig
from cameo_ingest.prompts import TEMPLATES
from cameo_ingest.provenance import ContentInfo

WAYS = ("long", "long, sandwiched", "parts")


def mentions(names: list[str], text: str) -> list[int]:
    """Indices of the names (of 4 characters or more) that `text` mentions."""
    low = text.lower()
    return [i for i, n in enumerate(names) if len(n) >= 4 and n.lower() in low]


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("samples", nargs="+", type=Path)
    ap.add_argument("--env", type=Path, required=True)
    ap.add_argument("--out", type=Path, required=True)
    ap.add_argument("--sample", type=int, default=8, help="at most this many packages per input (default 8)")
    ap.add_argument("--min", type=int, default=30_000)
    ap.add_argument("--max", type=int, default=400_000)
    ap.add_argument("--concurrency", type=int, default=6)
    args = ap.parse_args()
    load_env(args.env)
    llm = LLM(LLMConfig.from_env(None, None, timeout=600), args.out / ".cache")
    rng = random.Random(1)

    packages = []
    for sample in args.samples:
        found = []
        for proj in discover(sample.read_bytes(), sample.name):
            ix = pl.parse_project(proj)
            w = ProjectWriter(ContentInfo(proj.sha256, sample.name), proj, ix, Path(tempfile.mkdtemp()), {},
                              pl.load_layouts(proj, ix))
            for pkg_id, rel in w.pkg_file.items():
                sections = w._section_elements_in(ix.elements[pkg_id])
                if len(sections) < pl.MIN_SECTIONS_FOR_SUMMARY:
                    continue
                own = w.section(ix.elements[pkg_id], rel, 1, trace=False)
                texts = [w.section(e, rel, 2, trace=False) for e in sections]
                text = own + "\n".join(texts)
                if not args.min <= len(text) <= args.max:
                    continue
                groups = pl.package_parts(w, sections, texts)
                if len(groups) > pl.MAX_SUMMARIES:
                    continue
                qn = ix.qualified_name(pkg_id)
                parts = [pl.part_values(qn, k, len(groups), "\n".join(texts[i] for i in g))[0]
                         for k, g in enumerate(groups, 1)]
                found.append({"sample": sample.name, "package": qn, "chars": len(text), "text": text, "own": own,
                              "names": [ix.label(e.id) for e in sections], "parts": parts,
                              "sizes": [len(g) for g in groups]})
        chosen = found if len(found) <= args.sample else rng.sample(found, args.sample)
        print(f"{sample.name}: {len(found)} packages of {args.min:,} to {args.max:,} characters; {len(chosen)} asked")
        packages += sorted(chosen, key=lambda p: p["package"])

    def ask(key: str, values: dict[str, str]) -> str | None:
        res = llm.ask(TEMPLATES[key], values, project="study:long-context", inputs=("study",))
        return res[0] if res else None

    with ThreadPoolExecutor(args.concurrency) as pool:
        whole = {"CUT_NOTE": ""}
        longs = [pool.submit(ask, key, {**whole, "PACKAGE_TEXT": p["text"]})
                 for p in packages for key in ("package-summary@v2", "package-summary@v3")]
        part_answers = [[pool.submit(ask, "module-summary@v1", v) for v in p["parts"]] for p in packages]
        for i, p in enumerate(packages):
            p["long"], p["long, sandwiched"] = longs[2 * i].result(), longs[2 * i + 1].result()
        syntheses = []
        for p, futures in zip(packages, part_answers, strict=True):
            run = [((k, k), f.result()) for k, f in enumerate(futures, 1)]
            syntheses.append(pool.submit(ask, "package-synthesis@v1",
                                         pl.synthesis_values(p["package"], p["sizes"], p["own"], run, True)))
        for p, f in zip(packages, syntheses, strict=True):
            p["parts_answer"] = f.result()

    args.out.mkdir(parents=True, exist_ok=True)
    with (args.out / "whole.jsonl").open("w", encoding="utf-8") as f:
        for p in packages:
            f.write(json.dumps({k: v for k, v in p.items() if k not in ("text", "own", "parts")}, ensure_ascii=False) + "\n")

    print(f"\n{len(packages)} packages, {statistics.median(p['chars'] for p in packages):,.0f} characters (median), "
          f"{statistics.median(len(p['names']) for p in packages):.0f} elements (median)")
    print("| way | answered | words (median) | Markdown | names mentioned (median) | from first third | middle | last |")
    print("|---|---|---|---|---|---|---|---|")
    for way in WAYS:
        field = "parts_answer" if way == "parts" else way
        got = [p for p in packages if p[field]]
        thirds = [0, 0, 0]
        counts = []
        for p in got:
            idx = mentions(p["names"], p[field])
            counts.append(len(idx))
            for i in idx:
                thirds[min(2, 3 * i // len(p["names"]))] += 1
        total = sum(thirds) or 1
        md = sum(bool(re.search(r"^\s*([-*#>]|\d+\.)\s|\*\*|`", p[field], re.MULTILINE)) for p in got)
        print(f"| {way} | {len(got)} | {statistics.median(len(p[field].split()) for p in got):.0f} | {md} "
              f"| {statistics.median(counts):.0f} | " + " | ".join(f"{t / total:.0%}" for t in thirds) + " |")

    lines, key = ["# Whole-package summaries, blind", ""], ["", "## Key", ""]
    for n, p in enumerate(packages, 1):
        order = list(WAYS)
        rng.shuffle(order)
        names = "; ".join(p["names"][:60]) + ("; ..." if len(p["names"]) > 60 else "")
        lines += [f"## {n}. {p['sample']}: {p['package']} ({p['chars']:,} characters, {len(p['names'])} elements)", "",
                  f"Elements, in order: {names}", ""]
        for label, way in zip("XYZ", order, strict=True):
            lines += [f"**{label}:** {p['parts_answer' if way == 'parts' else way]}", ""]
        key.append(f"- {n}: " + ", ".join(f"{label} = {way}" for label, way in zip("XYZ", order, strict=True)))
    (args.out / "whole-blind.md").write_text("\n".join(lines + key) + "\n", encoding="utf-8")
    print(f"\nresults in {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
