"""Where a tree keeps its files, and JSON Lines read and written one way (review CQ-010).

- `PROJECTS/<sha256>/`: a built project (`project_dir`); its `index/<name>.jsonl` files
  (`index_file`) are what the root's files and the exports read: `catalog`, `chunks`, `ids`,
  `threads`, `hierarchies`, `elements`.
"""

from __future__ import annotations

import json
from collections.abc import Iterable
from pathlib import Path
from typing import Any

PROJECTS = "by-sha256"
INDEX = "index"


def project_dir(out: Path, sha: str) -> Path:
    """A built project's folder, by its content sha256 (with or without the "sha256:" of a token)."""
    return out / PROJECTS / sha.removeprefix("sha256:")


def index_file(project: Path, name: str) -> Path:
    """One of a project's index files: `index/<name>.jsonl`."""
    return project / INDEX / f"{name}.jsonl"


def read_jsonl(path: Path, missing_ok: bool = False) -> list[dict[str, Any]]:
    """Every record of a JSON Lines file, blank lines skipped; [] for a missing file if `missing_ok`."""
    if missing_ok and not path.is_file():
        return []
    with path.open(encoding="utf-8") as f:
        return [json.loads(line) for line in f if line.strip()]


def write_jsonl(path: Path, records: Iterable[Any]) -> None:
    """One record a line, its folder made."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as f:
        for r in records:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")
