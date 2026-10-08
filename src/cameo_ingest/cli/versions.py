"""`scan`, `projects`, `groups`, `remove` and `restore`: the projects in a tree, and versions of a
model (plan PV)."""

from __future__ import annotations

import argparse
import csv
import json
import sys
from pathlib import Path

from .. import runner as tree
from ..config import ProjectOptions
from ..llm import EnrichmentSession, LLMConfig
from ..progress import Progress
from ..runner import Runner
from ..state import State
from .common import open_tree


def _paths(state: State) -> dict[str, list[str]]:
    """Each content's places: input path, then archive members, '!' between."""
    out: dict[str, list[str]] = {}
    for r in state.catalog():
        out[r["sha256"]] = list(dict.fromkeys("!".join([s["path"], *json.loads(s["chain"])])
                                              for s in state.sightings(r["sha256"])))
    return out


def _resolve(tokens: list[str], candidates: dict[str, str]) -> tuple[list[tuple[str, str]], list[str]]:
    """Tokens (sha256:..., or 8 or more hex digits) to (sha256, name) among `candidates`; and errors."""
    found, errors = [], []
    for t in tokens:
        hexes = t.removeprefix("sha256:").lower()
        if len(hexes) < 8 or any(c not in "0123456789abcdef" for c in hexes):
            errors.append(f"{t}: give sha256:... or at least 8 hex digits")
            continue
        hits = [(sha, name) for sha, name in candidates.items() if sha.startswith(hexes)]
        if len(hits) != 1:
            errors.append(f"{t}: {'no project' if not hits else f'{len(hits)} projects'} match")
            continue
        found.append(hits[0])
    return found, errors


def scan(out: Path, args: argparse.Namespace) -> int:
    """`scan`: find the projects in the inputs, and what each says about itself, building nothing."""
    with open_tree(out, lock=True) as state:
        cfg = LLMConfig(None, None, None)
        runner = Runner(state, out, EnrichmentSession(cfg, out / ".cache", None), ProjectOptions(),
                        Progress(heartbeat=10))
        runner.check_inputs()
        runner.scan()
        caught_up = runner.fingerprint_missing()
        counts = state.counts("projects")
    print(f"scanned {out}: " + ", ".join(f"{n} {s}" for s, n in sorted(counts.items()))
          + (f"; {caught_up} fingerprinted from earlier scans" if caught_up else "")
          + f". See `cameo-ingest projects -o {out}` and `cameo-ingest groups -o {out}`")
    return 3 if runner.failed_inputs else 0


def projects(out: Path, args: argparse.Namespace) -> int:
    """`projects`: every project, its status, save time, Cameo version, size and places."""
    with open_tree(out) as state:
        rows, paths = state.catalog(), _paths(state)
    for r in rows:
        where = paths.get(r["sha256"], [])
        print(f"{r['sha256'][:8]}  {r['status']:<8} {(r['saved_raw'] or '-'):<30} {(r['exporter'] or '-'):<24} "
              f"{(r['elements'] or 0):>8,}  {r['name']}  ({len(where)} place{'s' if len(where) != 1 else ''})")
    print(f"{len(rows)} project(s); `groups` finds versions of the same model")
    if args.csv:
        with args.csv.open("w", encoding="utf-8", newline="") as f:
            w = csv.writer(f)
            w.writerow(["token", "name", "status", "saved", "saved_from", "exporter", "project_id",
                        "elements", "paths"])
            for r in rows:
                w.writerow([f"sha256:{r['sha256']}", r["name"], r["status"], r["saved_raw"] or "",
                            r["saved_from"] or "", r["exporter"] or "", r["project_id"] or "",
                            r["elements"] or "", "; ".join(paths.get(r["sha256"], []))])
    return 0


def groups(out: Path, args: argparse.Namespace) -> int:
    """`groups`: versions of the same model, by the element ids they share, and their kin."""
    from .. import groups as gp
    from .. import lineage

    with open_tree(out) as state:
        report = gp.find(state.catalog(), state.fingerprint_ids(), _paths(state), args.include_removed,
                         lineage.pairs(state, args.include_removed))
    print(gp.render(report, out))
    if args.csv:
        gp.write_csv(report, args.csv)
    return 0


def remove(out: Path, args: argparse.Namespace) -> int:
    """`remove`: projects out of the tree, kept out of later runs while their inputs remain."""
    with open_tree(out) as state:
        items, errors = _resolve(args.tokens, {r["sha256"]: r["name"] for r in state.catalog()
                                               if r["status"] != "removed"})
        for e in errors:
            print(f"error: {e}", file=sys.stderr)
        if errors:
            return 2
        for sha, name in items:
            print(f"{'would remove' if args.dry_run else 'removing'} {name} sha256:{sha[:16]}")
        if args.dry_run:
            return 0
        state.lock()
        tree.remove(state, out, items)
    print(f"removed {len(items)} project(s); later runs leave them out. `restore` undoes this")
    return 0


def restore(out: Path, args: argparse.Namespace) -> int:
    """`restore`: undo `remove`; the next run builds the projects again."""
    with open_tree(out) as state:
        items, errors = _resolve(args.tokens, {r["content_sha256"]: r["name"] for r in state.removed()})
        for e in errors:
            print(f"error: {e} (among removed projects)", file=sys.stderr)
        if errors:
            return 2
        state.lock()
        state.restore([sha for sha, _ in items])
    print(f"restored {len(items)} project(s); the next `run` builds them again, reusing their LLM answers")
    return 0
