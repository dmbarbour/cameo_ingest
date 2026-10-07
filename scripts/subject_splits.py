#!/usr/bin/env python3
"""Split a tree's families into subjects, every candidate way, and measure what needs no judge
(plan SB-02).

    uv run --extra eval python scripts/subject_splits.py out/sb/tree --out out/sb/splits

Writes OUT/splits.json (every family's items and each split's groups), OUT/<family>.md (each
split's groups, labelled, with their diagrams: a first look) and OUT/summary.md: the version
families found, against the known cases, and each split's measures.
"""

from __future__ import annotations

import argparse
import json
import re
from collections import Counter
from pathlib import Path

from cameo_ingest.evaluation.subjects import SPLITS, families, label, measures, target

MIN_ITEMS = 8  # smaller families aren't split

# The known version cases (plan SB): file names, and how many of each a family must hold.
KNOWN = {
    "TMT": Counter({"TMT.mdzip": 1, "TMT-2024x.mdzip": 1}),
    "Kestrel, a later save": Counter({"Kestrel_Orchard_Irrigation.mdzip": 2}),
    "Port Calder, forked": Counter({"Port_Calder_Traffic_Signal_System.mdzip": 1, "Eastport_Traffic_Signals.mdzip": 1}),
    "Ashgrove, copied": Counter({"Ashgrove_Library_Book_Return_Kiosk.mdzip": 2}),
}
RIVALS = "Riverbend_Water_Treatment_Works.mdzip"  # three proposals: never one family


def slug(text: str) -> str:
    return re.sub(r"[^A-Za-z0-9]+", "_", text).strip("_")[:60]


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("tree", type=Path)
    ap.add_argument("--out", type=Path, required=True)
    args = ap.parse_args()
    args.out.mkdir(parents=True, exist_ok=True)
    fams = families(args.tree)

    names = {}  # by the newest token: rivals share a file name
    for f in fams:
        names[f.tokens[0]] = Counter(_names(args.tree, f.tokens))
    lines = ["# Subject splits (plan SB-02)", "", f"Tree: `{args.tree}`; {len(fams)} families.", "",
             "## Version families (V)", "", "| Case | Found as one family | Members |", "|---|---|---|"]
    for case, want in KNOWN.items():
        hit = [lab for lab, got in names.items() if got == want]
        lines.append(f"| {case} | {'yes' if hit else 'NO'} | {', '.join(f'{n} × {c}' for n, c in want.items())} |")
    rivals = [lab for lab, got in names.items() if got.get(RIVALS)]
    lines.append(f"| Riverbend's rivals, apart | {'yes' if all(names[r][RIVALS] == 1 for r in rivals) and len(rivals) == 3 else 'NO'} "
                 f"| {len(rivals)} families |")
    extra = [" + ".join(got) for got in names.values() if sum(got.values()) > 1 and got not in KNOWN.values()]
    lines += ["", f"Other families of versions: {', '.join(extra) or 'none'}.", ""]

    lines += ["## Copies taken once", "", "| Family | Diagrams in all versions | Items |", "|---|---|---|"]
    for f in fams:
        if len(f.tokens) > 1:
            lines.append(f"| {f.label} | {f.copies:,} | {len(f.items):,} |")

    data = []
    lines += ["", "## Splits", "", f"Families of at least {MIN_ITEMS} diagrams; k is the target number of groups.", "",
              "| Family | Items | k | " + " | ".join(f"{s}: groups, largest, balance" for s in SPLITS) + " |",
              "|---|---|---|" + "---|" * len(SPLITS)]
    for f in sorted(fams, key=lambda f: -len(f.items)):
        if len(f.items) < MIN_ITEMS:
            continue
        k = target(len(f.items))
        splits = {name: fn(f, k) for name, fn in SPLITS.items()}
        ms = {name: measures(s) for name, s in splits.items()}
        lines.append(f"| {f.label} | {len(f.items)} | {k} | "
                     + " | ".join(f"{m['groups']}, {m['largest']:.0%}, {m['balance']:.2f}" for m in ms.values()) + " |")
        page = [f"# {f.label}: {len(f.items)} diagrams, split into about {k}", ""]
        rec = {"family": f.label, "tokens": f.tokens, "k": k,
               "items": {key: {"name": it.name, "owner": it.owner, "kind": it.kind, "package": it.package,
                               "about": it.about, "versions": len(it.versions)} for key, it in sorted(f.items.items())},
               "splits": {}}
        for name, s in splits.items():
            groups = sorted(set(s.values()), key=lambda g: -sum(1 for x in s.values() if x == g))
            labels = {g: (_package_label(f, s, g) if name == "P" else label(f, s, g)) for g in groups}
            rec["splits"][name] = {"groups": {str(g): sorted(k_ for k_, x in s.items() if x == g) for g in groups},
                                   "labels": {str(g): labels[g] for g in groups}, "measures": ms[name]}
            page += [f"## {name}: {ms[name]['groups']} groups, the largest {ms[name]['largest']:.0%}", ""]
            for g in groups:
                members = sorted((f.items[k_] for k_, x in s.items() if x == g), key=lambda it: it.name)
                shown = "; ".join(it.title for it in members[:8]) + (f"; … {len(members) - 8} more" if len(members) > 8 else "")
                page.append(f"- **{labels[g]}** ({len(members)}): {shown}")
            page.append("")
        data.append(rec)
        (args.out / f"{slug(f.label)}.md").write_text("\n".join(page), encoding="utf-8")
    (args.out / "splits.json").write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8")
    (args.out / "summary.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    print("\n".join(lines))
    return 0


def _package_label(f, s, g) -> str:
    paths = [f.items[k].package for k, x in s.items() if x == g]
    parts = [p.split("::") for p in paths]
    common = []
    for level in zip(*parts, strict=False):
        if len(set(level)) != 1:
            break
        common.append(level[0])
    return "::".join(common[-2:]) or "(the model's root)"


def _names(tree: Path, tokens: list[str]) -> list[str]:
    from cameo_ingest.state import State

    st = State(tree)
    try:
        by = {f"sha256:{r['content_sha256']}": r["name"] for r in st.written()}
    finally:
        st.close()
    return [by[t] for t in tokens]


if __name__ == "__main__":
    raise SystemExit(main())
