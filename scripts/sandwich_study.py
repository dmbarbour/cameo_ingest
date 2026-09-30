#!/usr/bin/env python3
"""Compare prompts with and without the task repeated after the input (plan DV-06).

    uv run python scripts/sandwich_study.py --env .env samples/Package_Delivery_Drone.mdzip ... --out DIR

For every large package's parts (up to --sample parts per input, drawn at random with a fixed
seed), asks module-summary v1 (the task before the input only) and v2 (repeated after it);
then, for packages whose parts were all asked, package-synthesis v1 and v2 from the v1 part
summaries. Answers are cached in DIR/.cache, so a rerun costs nothing. Writes DIR/results.jsonl
and DIR/pairs.md (pairs in random order, for rating blind), and prints:

- adherence: answers over the word limit, with Markdown, or naming parts by number;
- coverage: the share of a part's element names that its summary mentions, for the first,
  middle and last third of the part's sections, where a long input loses attention first.
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
from cameo_ingest.text import md_plain

PAIRS = {"module-summary": ("module-summary@v1", "module-summary@v2", 120),
         "package-synthesis": ("package-synthesis@v1", "package-synthesis@v2", 200)}
_NAME = re.compile(r"^## (?:«[^»]*» )*(.+)$", re.MULTILINE)


def adherence(text: str, limit: int) -> dict[str, bool]:
    return {"over_limit": len(text.split()) > limit,
            "markdown": bool(re.search(r"^\s*([-*#>]|\d+\.)\s|\*\*|`", text, re.MULTILINE)),
            "part_numbers": bool(re.search(r"\bparts? \d+\b", text, re.IGNORECASE))}


def coverage(sections: str, text: str) -> list[float | None]:
    """Shares of the part's element names mentioned in `text`, by thirds of the part."""
    names = [md_plain(n).strip() for n in _NAME.findall(sections) if n.strip() != "(unnamed)"]
    low = text.lower()
    out: list[float | None] = []
    for i in range(3):
        third = names[i * len(names) // 3:(i + 1) * len(names) // 3]
        out.append(sum(n.lower() in low for n in third) / len(third) if third else None)
    return out


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("samples", nargs="+", type=Path)
    ap.add_argument("--env", type=Path, required=True)
    ap.add_argument("--out", type=Path, required=True)
    ap.add_argument("--sample", type=int, default=60, help="at most this many parts per input (default 60)")
    ap.add_argument("--concurrency", type=int, default=8)
    args = ap.parse_args()
    load_env(args.env)
    llm = LLM(LLMConfig.from_env(None, None), args.out / ".cache")
    rng = random.Random(1)

    items = []  # (sample, package, k, n, values, sizes, own)
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
                if len(own + "\n".join(texts)) <= pl.SUMMARY_INPUT_CHARS:
                    continue
                groups = pl.package_parts(w, sections, texts)
                for k, g in enumerate(groups, 1):
                    values, _ = pl.part_values(ix.qualified_name(pkg_id), k, len(groups), "\n".join(texts[i] for i in g))
                    found.append((sample.name, ix.qualified_name(pkg_id), k, len(groups), values, [len(x) for x in groups], own))
        chosen = found if len(found) <= args.sample else rng.sample(found, args.sample)
        print(f"{sample.name}: {len(found)} parts in large packages; {len(chosen)} asked")
        items += sorted(chosen, key=lambda x: (x[1], x[2]))

    def ask(key: str, values: dict[str, str]) -> str | None:
        res = llm.ask(TEMPLATES[key], values, project="study:sandwich", inputs=("study",))
        return res[0] if res else None

    with ThreadPoolExecutor(args.concurrency) as pool:
        answers = {}
        for key in PAIRS["module-summary"][:2]:
            answers[key] = list(pool.map(lambda it, key=key: ask(key, it[4]), items))
        # Syntheses, for packages all of whose parts were asked, from the v1 part summaries.
        packages: dict[tuple[str, str], list[int]] = {}
        for i, it in enumerate(items):
            packages.setdefault((it[0], it[1]), []).append(i)
        whole = [(key, idx) for key, idx in packages.items() if len(idx) == items[idx[0]][3] <= pl.MAX_SUMMARIES]
        synth_values = []
        for (_, package), idx in whole:
            run = [((items[i][2], items[i][2]), answers["module-summary@v1"][i]) for i in idx]
            synth_values.append(pl.synthesis_values(package, items[idx[0]][5], items[idx[0]][6], run, True))
        for key in PAIRS["package-synthesis"][:2]:
            answers[key] = list(pool.map(lambda v, key=key: ask(key, v), synth_values))

    args.out.mkdir(parents=True, exist_ok=True)
    rows = []
    for tid, (a, b, limit) in PAIRS.items():
        inputs = items if tid == "module-summary" else [None] * len(synth_values)
        for i, it in enumerate(inputs):
            sections = it[4]["SECTIONS"] if it else ""
            name = f"{it[0]} {it[1]} part {it[2]} of {it[3]}" if it else f"{whole[i][0][0]} {whole[i][0][1]}"
            row = {"template": tid, "item": name}
            for key in (a, b):
                text = answers[key][i]
                row[key] = {"text": text, "words": len(text.split()) if text else 0,
                            **(adherence(text, limit) if text else {}),
                            **({"coverage": coverage(sections, text)} if text and it else {})}
            rows.append(row)
    with (args.out / "results.jsonl").open("w", encoding="utf-8") as f:
        for r in rows:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")

    for tid, (a, b, limit) in PAIRS.items():
        rs = [r for r in rows if r["template"] == tid and r[a]["text"] and r[b]["text"]]
        print(f"\n{tid}: {len(rs)} items, limit {limit} words")
        print("| version | words (median) | over limit | Markdown | part numbers | coverage: first | middle | last |")
        print("|---|---|---|---|---|---|---|---|")
        for key in (a, b):
            cov = [[r[key]["coverage"][j] for r in rs if r[key].get("coverage") and r[key]["coverage"][j] is not None]
                   for j in range(3)]
            print(f"| {key} | {statistics.median(r[key]['words'] for r in rs):.0f} "
                  f"| {sum(r[key]['over_limit'] for r in rs)} | {sum(r[key]['markdown'] for r in rs)} "
                  f"| {sum(r[key]['part_numbers'] for r in rs)} | "
                  + " | ".join(f"{statistics.mean(c):.0%}" if c else "-" for c in cov) + " |")

    # Blind pairs: X and Y are v1 and v2 in random order; the key is at the end.
    lines, key_lines = ["# Blind pairs", ""], ["", "## Key", ""]
    for n, r in enumerate(rng.sample(rows, min(24, len(rows))), 1):
        a, b, _ = PAIRS[r["template"]]
        x, y = (a, b) if rng.random() < 0.5 else (b, a)
        lines += [f"## {n}. {r['template']}: {r['item']}", "", f"**X:** {r[x]['text']}", "", f"**Y:** {r[y]['text']}", ""]
        key_lines.append(f"- {n}: X = {x}, Y = {y}")
    (args.out / "pairs.md").write_text("\n".join(lines + key_lines) + "\n", encoding="utf-8")
    print(f"\nresults in {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
