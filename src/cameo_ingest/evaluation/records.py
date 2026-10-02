"""The evaluation's files (AR-020R2, AR-020R3): questions, rankings and judgments as JSONL, and a
run's record, `run.json`, written beside its rankings.

The record says how the run's windows were cut from the tree, so that the judges (`judge_pools`)
grade the same text under the same window ids, whatever sizes the run used.
"""

from __future__ import annotations

import json
from collections.abc import Iterable
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

RUN = "run.json"
RANKINGS = "rankings.jsonl"
PER_QUESTION = "per_question.jsonl"
REPORT = "report.md"


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def write_jsonl(path: Path, rows: Iterable[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as f:
        for r in rows:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")


def questions(source: str, tree: Path) -> list[dict[str, Any]]:
    """`structural` (generated from the tree), or a JSONL file of questions of any form."""
    if source == "structural":
        from .questions import structural

        return structural(tree)
    return read_jsonl(Path(source))


def set_name(source: str) -> str:
    """The name the judges know a question set by: `structural`, or the file's stem."""
    return "structural" if source == "structural" else Path(source).stem


@dataclass(frozen=True)
class Run:
    """What a retrieval run ranked: the units of a tree, cut into windows, for a set of questions."""

    tree: str
    questions: str  # "structural", or the questions' file
    rag: bool = False  # the units are rag/'s files, not chunks.jsonl's texts
    project: str | None = None  # only the units of elements whose ids start so
    without_details: bool = False  # the plain style's details chunks left out
    tokenizer: str = "intfloat/multilingual-e5-large"  # the tokens windows are cut on
    window: int = 512
    overlap: int = 64

    def units(self) -> list:
        from .harness import chunk_units, rag_units

        units = rag_units(Path(self.tree)) if self.rag else chunk_units(Path(self.tree))
        if self.project:
            units = [u for u in units if (u.element_id or "").startswith(self.project)]
        if self.without_details:
            units = [u for u in units if not u.kind.endswith(":details")]
        return units

    def windows(self, units: list | None = None) -> list:
        from .harness import windowed

        return windowed(self.units() if units is None else units, self.tokenizer, self.window, self.overlap)

    def write(self, out: Path) -> None:
        out.mkdir(parents=True, exist_ok=True)
        (out / RUN).write_text(json.dumps(asdict(self), indent=2) + "\n", encoding="utf-8")

    @classmethod
    def read(cls, out: Path) -> Run:
        return cls(**json.loads((out / RUN).read_text(encoding="utf-8")))
