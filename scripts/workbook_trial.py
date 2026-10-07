#!/usr/bin/env python3
"""Trial workbooks for the maintainer's Excel (plan WT-01): tables, and table slicers.

    uv run python scripts/workbook_trial.py TREE DIR

Writes, from TREE's export, DIR/trial-tables.xlsx (every sheet but About an Excel Table) and
DIR/trial-slicers.xlsx (the same, with slicers on the Diagrams sheet for Project, Type and
Subject). Two files, so that a repair prompt in one tells tables from slicers.
"""

from __future__ import annotations

import argparse
import json
import shutil
from pathlib import Path

from cameo_ingest import __version__, catalog, lineage, subjects, workbook
from cameo_ingest.progress import Progress
from cameo_ingest.provenance import ContentInfo
from cameo_ingest.state import State
from cameo_ingest.xlsx_parts import Slicer, Table, add_parts


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("tree", type=Path)
    ap.add_argument("dir", type=Path)
    args = ap.parse_args()
    args.dir.mkdir(parents=True, exist_ok=True)
    state = State(args.tree)
    try:
        sub = args.tree / subjects.FILE
        families = json.loads(sub.read_text(encoding="utf-8")) if sub.is_file() else None
        facts = lineage.facts(state)
        for r in state.written():
            if f"sha256:{r['content_sha256']}" in facts:
                facts[f"sha256:{r['content_sha256']}"]["label"] = ContentInfo(r["content_sha256"], r["name"]).label
        tables_file = args.dir / "trial-tables.xlsx"
        rows = workbook.write_workbook(tables_file, catalog.tree_catalogs(state, args.tree, [], Progress()),
                                       __version__, families, facts)
    finally:
        state.close()
    tables = [Table(name, name, [c for c, _ in workbook.SHEETS[name]], n) for name, n in rows.items()]
    slicers_file = args.dir / "trial-slicers.xlsx"
    shutil.copyfile(tables_file, slicers_file)
    add_parts(tables_file, tables)
    width = len(workbook.SHEETS["Diagrams"])
    add_parts(slicers_file, tables, [Slicer("Diagrams", "Project", width + 1, 1, columns=1),
                                     Slicer("Diagrams", "Type", width + 1 + 3, 1),
                                     Slicer("Diagrams", "Subject", width + 1 + 6, 1, width=260, height=420)])
    for f in (tables_file, slicers_file):
        print(f"{f}: {f.stat().st_size / 1e6:.1f} MB")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
