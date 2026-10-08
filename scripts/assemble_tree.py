#!/usr/bin/env python3
"""Rebuild a tree's own files with what its chunks bring together changed, to measure a change
to one of the defaults (ADR-0027).

    uv run python scripts/assemble_tree.py out/v019/off --without hierarchies
    uv run python scripts/assemble_tree.py out/v019/refs --line-refs

TREE is an output tree as a run left it: `chunks.jsonl`, `CROSSREF.md` and `rag/` are rebuilt from
its state, with the index across models, the threads or the hierarchies left out, with line
references added, or with kinds left out of `rag/` (`--rag-without generated:summary`). Work on a copy: the next run of the tree puts the defaults back.
Users don't set these; they are measured defaults (`rootfiles.Assembly`), and this script holds the
arguments.
"""

from __future__ import annotations

import argparse
import dataclasses
from pathlib import Path

from cameo_ingest import rootfiles
from cameo_ingest.state import State

PARTS = ("cross-index", "threads", "hierarchies")


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("tree", type=Path, help="the output tree to rebuild (a copy)")
    ap.add_argument("--without", nargs="+", choices=PARTS, default=[], help="leave these out of the tree's chunks")
    ap.add_argument("--line-refs", action="store_true",
                    help="end each line of an assembled chunk with its source chunk, [project:chunk]")
    ap.add_argument("--rag-without", nargs="+", default=[], metavar="KIND",
                    help="leave chunks of these kinds out of rag/, as globs (ADR-0028, ADR-0029)")
    args = ap.parse_args(argv)
    if not State.exists(args.tree):
        ap.error(f"{args.tree} is not an output tree")
    assembly = rootfiles.Assembly(**{p.replace("-", "_"): False for p in args.without}, line_refs=args.line_refs,
                                rag_without=tuple(args.rag_without))
    state = State(args.tree)
    try:
        state.lock()
        rootfiles.rebuild(state, args.tree, assembly)
    finally:
        state.close()
    changed = {k: v for k, v in dataclasses.asdict(assembly).items() if v != getattr(rootfiles.Assembly(), k)}
    print(f"rebuilt {args.tree}: {changed or 'the defaults'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
