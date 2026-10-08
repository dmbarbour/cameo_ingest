"""Outlines: trees of lines that gather, in one place, an answer otherwise spread over many
elements' chunks (review CQ-015). Two sorts, each building its own records:
- **threads** (`threads`, plan RF): what derives from a requirement, level by level;
- **type hierarchies** (`hierarchies`, plan TH): the kinds of a general, level by level.

Both are chunked and shown alike: an outline is a chunk, in parts if it is long, each part after
the first starting with its first line's ancestors (AR-027R2), so that it says what its lines are
under; and a page of the project's outlines, each line with its chunk reference.
"""

from __future__ import annotations

import re
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any, TypedDict

from . import chunks
from . import plain as pl
from .provenance import TOOL, ContentInfo


class Line(TypedDict):
    depth: int
    id: str  # the element
    title: str
    text: str  # without chunk references
    text_refs: str  # with them (`exports.Assembly.line_refs`)


class Outline(TypedDict):
    """A record of a project's `index/threads.jsonl` or `index/hierarchies.jsonl`; each sort adds
    its own counts (`requirements`; `kinds` and `levels`)."""

    root: str
    title: str
    element_ids: list[str]
    locator: str
    lines: list[Line]


@dataclass(frozen=True)
class Sort:
    """How one sort of outline is chunked and shown."""

    kind: str  # the chunks' kind
    word: str  # "Thread", "Hierarchy": its chunks' and headings' first word
    file: str  # each project's page of them
    heading: Callable[[dict[str, Any], ContentInfo], str]  # a chunk's heading line
    element_id: Callable[[dict[str, Any]], str]  # the element a chunk is about

    def anchor(self, root: str) -> str:
        return anchor(f"{self.word.lower()}-{root}")


def anchor(term: str) -> str:
    """An HTML anchor for `term`."""
    return re.sub(r"[^a-z0-9-]+", "-", term.lower()).strip("-")


def outline_chunks(sort: Sort, outlines: list[dict[str, Any]], content: ContentInfo,
                   refs: bool = False) -> list[dict[str, Any]]:
    """A chunk (in parts) per outline, its `file` relative to the project."""
    out = []
    for o in outlines:
        rows = [("  " * ln["depth"]) + (ln["text_refs"] if refs else ln["text"]) for ln in o["lines"]]
        context: list[list[str]] = []
        above: list[str] = []  # the titles of the lines above the current one, by depth
        for ln in o["lines"]:
            above = above[:ln["depth"]]
            context.append([f"{'  ' * d}- {title} (continued)" for d, title in enumerate(above)])
            above.append(ln["title"])
        texts = pl.parts_with_context(sort.heading(o, content), rows, context)
        for k, text in enumerate(texts, 1):
            out.append(chunks.make((content.sha256, sort.kind, o["root"], str(k)),
                                   f"{sort.word}: {o['title']}" + (f" (part {k} of {len(texts)})" if len(texts) > 1 else ""),
                                   text, {
                "kind": sort.kind, "file": f"{sort.file}#{sort.anchor(o['root'])}", "content": content.token,
                "element_id": sort.element_id(o), "element_ids": o["element_ids"],
                "provenance": {"derivation": {"method": "assembled", "tool": TOOL}, "locator": o["locator"]},
                **({"part": k, "parts": len(texts)} if len(texts) > 1 else {}),
            }))
    return out


def outline_page(sort: Sort, outlines: list[dict[str, Any]], content: ContentInfo, title: str, about: str) -> str:
    """A project's page of one sort of outline, for reading, with each line's chunk reference."""
    lines = [f"# {title}", "", about, ""]
    for o in outlines:
        lines += [f'<a id="{sort.anchor(o["root"])}"></a>', "",
                  f"## {sort.heading(o, content).removeprefix(sort.word + ': ')}", ""]
        lines += [("  " * ln["depth"]) + ln["text_refs"] for ln in o["lines"]] + [""]
    return "\n".join(lines)
