"""Compare two output trees: what a change did to the output (plan RA-01).

    python -m cameo_ingest.treediff BEFORE AFTER [--show N]

A refactoring step that should change no output must show no difference; a step that changes
output must show only the expected ones. Every file is compared but the run records (which hold
times and local paths: `run.json`, `provenance.jsonl`, `state.sqlite` and its companions), work
directories and the `rag/` writer's stamps, with the tool's version masked. The manifest's
hashes of the files it lists are left out: they hash the version too, and the files themselves
are compared. Chunk files (`chunks.jsonl`) are compared
chunk by chunk, by id: which went, which came, and which changed their text or their metadata.
Build both trees from the same input paths: `rag/meta` names them. Exits 0 when the trees are
the same, 1 when they differ.
"""

from __future__ import annotations

import argparse
import difflib
import json
import re
import sys
from collections import defaultdict
from collections.abc import Iterator
from dataclasses import dataclass, field
from pathlib import Path

SKIPPED = {"run.json", "provenance.jsonl", "state.sqlite", "state.sqlite-wal", "state.sqlite-shm", "state.lock",
           ".stamp"}
_VERSION = re.compile(rb"cameo-ingest/\d+\.\d+\.\d+[\w.+-]*")


def _files(root: Path) -> Iterator[str]:
    for f in root.rglob("*"):
        rel = f.relative_to(root)
        if f.is_file() and f.name not in SKIPPED and not any(p in (".work", ".cache") for p in rel.parts):
            yield rel.as_posix()


def kind(rel: str) -> str:
    """What a file is, for the report."""
    parts = rel.split("/")
    if parts[0] == "rag":
        return f"rag/{parts[1]}" if len(parts) > 2 else "rag"
    if rel.endswith("chunks.jsonl"):
        return "chunks"
    suffix = rel.rsplit(".", 1)[-1] if "." in parts[-1] else ""
    return {"md": "pages", "csv": "tables", "png": "images", "json": "json", "jsonl": "jsonl"}.get(suffix, "other")


def _read(path: Path, rel: str = "") -> bytes:
    data = _VERSION.sub(b"cameo-ingest/*", path.read_bytes())
    if rel == "manifest.json":
        m = json.loads(data)
        for p in m.get("projects", []):
            for f in p.get("files", []):
                f.pop("sha256", None)
        data = json.dumps(m, sort_keys=True).encode()
    return data


def _chunks(path: Path) -> dict[str, dict]:
    out = {}
    for line in _read(path).decode("utf-8").splitlines():
        c = json.loads(line)
        out[c["id"]] = c
    return out


@dataclass
class ChunkChanges:
    removed: list[str] = field(default_factory=list)
    added: list[str] = field(default_factory=list)
    text: list[tuple[str, str, str]] = field(default_factory=list)  # id, before, after
    metadata: list[str] = field(default_factory=list)

    def __bool__(self) -> bool:
        return bool(self.removed or self.added or self.text or self.metadata)


@dataclass
class Report:
    removed: dict[str, list[str]] = field(default_factory=lambda: defaultdict(list))  # kind -> files
    added: dict[str, list[str]] = field(default_factory=lambda: defaultdict(list))
    changed: dict[str, list[str]] = field(default_factory=lambda: defaultdict(list))
    chunks: dict[str, ChunkChanges] = field(default_factory=dict)  # chunk file -> its changes

    def __bool__(self) -> bool:
        return bool(self.removed or self.added or self.changed)

    def lines(self, show: int = 3) -> list[str]:
        if not self:
            return ["The trees are the same."]
        out = []
        for what, files in (("Only before", self.removed), ("Only after", self.added), ("Changed", self.changed)):
            for k in sorted(files):
                out.append(f"{what}: {len(files[k])} {k}" + "".join(f"\n  {f}" for f in sorted(files[k])[:show]))
        for path, ch in sorted(self.chunks.items()):
            out.append(f"Chunks in {path}: {len(ch.removed)} only before, {len(ch.added)} only after, "
                       f"{len(ch.text)} with other text, {len(ch.metadata)} with other metadata only")
            for cid, before, after in ch.text[:show]:
                diff = difflib.unified_diff(before.splitlines(), after.splitlines(), "before", "after", lineterm="", n=1)
                out.append(f"  {cid}:\n" + "\n".join(f"    {d}" for d in list(diff)[2:40]))
            out += [f"  {cid}: metadata" for cid in ch.metadata[:show]]
        return out


def compare(before: Path, after: Path) -> Report:
    r = Report()
    a, b = set(_files(before)), set(_files(after))
    for rel in a - b:
        r.removed[kind(rel)].append(rel)
    for rel in b - a:
        r.added[kind(rel)].append(rel)
    for rel in sorted(a & b):
        if _read(before / rel, rel) == _read(after / rel, rel):
            continue
        r.changed[kind(rel)].append(rel)
        if rel.endswith("chunks.jsonl"):
            x, y = _chunks(before / rel), _chunks(after / rel)
            ch = ChunkChanges(sorted(x.keys() - y.keys()), sorted(y.keys() - x.keys()))
            for cid in sorted(x.keys() & y.keys()):
                if x[cid]["text"] != y[cid]["text"]:
                    ch.text.append((cid, x[cid]["text"], y[cid]["text"]))
                elif x[cid] != y[cid]:
                    ch.metadata.append(cid)
            r.chunks[rel] = ch
    return r


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("before", type=Path)
    ap.add_argument("after", type=Path)
    ap.add_argument("--show", type=int, default=3, help="examples to show of each kind of difference")
    args = ap.parse_args(argv)
    report = compare(args.before, args.after)
    print("\n".join(report.lines(args.show)))
    return 1 if report else 0


if __name__ == "__main__":
    sys.exit(main())
