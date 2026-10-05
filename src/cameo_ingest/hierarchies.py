"""Type hierarchies (plan TH): each tree of generalizations in one model, as threads are for
requirements (`crossref`), so that "what kinds of detector are there?" finds its answer in one
place, where otherwise every kind's own chunk holds a piece of it.

- **A root** is a general with specializations and no general of its own in the project; or a
  general outside the project (a library's or used project's type) that two or more of the
  project's kinds specialize.
- **A hierarchy** holds each kind once, under its general, level by level, with its kind word and
  the first sentence of its documentation. A kind with two or more generals is placed under the
  first one met, and says what else it is a kind of. Hierarchies of fewer than three kinds are
  left out: the element's own chunk says "is a kind of" already.
- **Records** go to the project's `index/hierarchies.jsonl` and `HIERARCHIES.md`; the tree's
  chunks include them when its setting says so (`--hierarchies`), as `index:hierarchy`.
"""

from __future__ import annotations

import re
from collections import defaultdict
from typing import TYPE_CHECKING, Any

from . import chunks
from . import plain as pl
from . import semantics as sem
from .provenance import TOOL, ContentInfo, chunk_ref
from .text import one_line

if TYPE_CHECKING:
    from .view import ProjectView

FILE = "HIERARCHIES.md"  # each project's page of them
MIN_KINDS = 3  # a hierarchy's kinds, its root included
DOC_CHARS = 100  # of a kind's documentation, its first sentence


def _anchor(term: str) -> str:
    return re.sub(r"[^a-z0-9-]+", "-", term.lower()).strip("-")


def _first_sentence(text: str) -> str:
    text = one_line(text)
    m = re.search(r"(?<=[.!?])\s", text)
    text = text[:m.start()] if m else text
    return text if len(text) <= DOC_CHARS else text[:DOC_CHARS - 1].rsplit(" ", 1)[0] + "…"


def project_hierarchies(view: ProjectView, chunk_of: dict[str, str]) -> list[dict[str, Any]]:
    """The project's type hierarchies, from the in-memory model: the records of its
    `index/hierarchies.jsonl`, each a line per kind, as text without and with the chunk references
    that `--line-refs` adds."""
    ix = view.ix
    generals: dict[str, list[str]] = defaultdict(list)  # a kind -> its generals, in the model's order
    specifics: dict[str, list[str]] = defaultdict(list)  # a general -> its kinds
    for r in view.rels:
        if r.metaclass == "Generalization" and r.source in ix.elements and r.target != r.source:
            generals[r.source].append(r.target)
            specifics[r.target].append(r.source)

    def inside(e: str) -> bool:
        return e in ix.elements

    outside_roots = {g for g, ks in specifics.items() if not inside(g) and len(ks) >= 2}
    roots = sorted(outside_roots) + sorted(
        g for g in specifics if inside(g)
        and not any(inside(x) or x in outside_roots for x in generals.get(g, [])))

    def name(e: str) -> str:
        return one_line(sem.label(ix, e)) + ("" if inside(e) else " (outside this project)")

    def ref(e: str) -> str:
        return f" [{chunk_ref(view.content.sha256, chunk_of[e])}]" if e in chunk_of else ""

    def line(e: str, under: str | None) -> tuple[str, str]:
        if not inside(e):
            head = f"- {name(e)}"
            return head, head
        el = ix.elements[e]
        doc = _first_sentence(sem.documentation(ix, el))
        also = [name(g) for g in generals.get(e, []) if g != under]
        head = f"- {name(e)} ({sem.kind_word(ix, el)})"
        tail = (f": {doc}" if doc else "") + (f"; also a kind of {', '.join(also)}" if also else "")
        return head + tail, head + ref(e) + tail

    def walk(e: str, depth: int, under: str | None, lines: list[dict[str, Any]], seen: set[str]) -> None:
        if e in seen:
            return
        seen.add(e)
        text, text_refs = line(e, under)
        lines.append({"depth": depth, "id": e, "title": name(e), "text": text, "text_refs": text_refs})
        # In name order; alike leaves (kinds with none of their own, such as a model's runs of one
        # analysis) on one line, where the first of them falls.
        order: list[str | tuple[str, list[str]]] = []
        alike: dict[str, list[str]] = {}
        for k in sorted(specifics.get(e, []), key=name):
            if k in seen:
                continue
            if specifics.get(k):
                order.append(k)
                continue
            text = line(k, e)[0]
            if text not in alike:
                alike[text] = []
                order.append((text, alike[text]))
            alike[text].append(k)
        for item in order:
            if isinstance(item, str):
                walk(item, depth + 1, e, lines, seen)
                continue
            text, ks = item
            seen.update(ks)
            many = f" ({len(ks)} kinds of this name)" if len(ks) > 1 else ""
            lines.append({"depth": depth + 1, "id": ks[0], "title": name(ks[0]), "text": text + many,
                          "text_refs": line(ks[0], e)[1] + many})

    out = []
    for root in roots:
        lines: list[dict[str, Any]] = []
        seen: set[str] = set()
        walk(root, 0, None, lines, seen)
        kinds = sum(1 for e in seen if inside(e))
        if kinds < MIN_KINDS - (0 if inside(root) else 1):
            continue
        first = root if inside(root) else lines[1]["id"]
        out.append({"root": root, "title": name(root), "kinds": kinds, "levels": max(ln["depth"] for ln in lines),
                    "element_ids": sorted(e for e in seen if inside(e)),
                    "locator": view.trace(ix.elements[first]).locator(), "lines": lines})
    return out


def _heading(h: dict[str, Any], content: ContentInfo) -> str:
    levels = h["levels"]
    return (f"Hierarchy: kinds of {h['title']}, in {content.label}, {h['kinds']} kinds, "
            f"{levels} level{'s' if levels != 1 else ''}")


def hierarchy_chunks(hierarchies: list[dict[str, Any]], content: ContentInfo, refs: bool = False) -> list[dict[str, Any]]:
    """A chunk (in parts) per hierarchy, its `file` relative to the project. A part after the
    first starts with its first line's ancestors, so that each part says what its kinds are kinds
    of."""
    out = []
    for h in hierarchies:
        rows = [("  " * ln["depth"]) + (ln["text_refs"] if refs else ln["text"]) for ln in h["lines"]]
        context: list[list[str]] = []
        above: list[str] = []
        for ln in h["lines"]:
            above = above[:ln["depth"]]
            context.append([f"{'  ' * d}- {title} (continued)" for d, title in enumerate(above)])
            above.append(ln["title"])
        texts = pl.parts_with_context(_heading(h, content), rows, context)
        for k, text in enumerate(texts, 1):
            out.append(chunks.make((content.sha256, "index:hierarchy", h["root"], str(k)),
                                   f"Hierarchy: {h['title']}" + (f" (part {k} of {len(texts)})" if len(texts) > 1 else ""),
                                   text, {
                "kind": "index:hierarchy", "file": f"{FILE}#{_anchor('hierarchy-' + h['root'])}",
                "content": content.token, "element_id": h["element_ids"][0] if h["root"] not in h["element_ids"]
                else h["root"], "element_ids": h["element_ids"],
                "provenance": {"derivation": {"method": "assembled", "tool": TOOL}, "locator": h["locator"]},
                **({"part": k, "parts": len(texts)} if len(texts) > 1 else {}),
            }))
    return out


def hierarchies_page(hierarchies: list[dict[str, Any]], content: ContentInfo) -> str:
    """HIERARCHIES.md: a project's type hierarchies, for reading, with each line's chunk reference."""
    lines = [f"# Hierarchies: kinds in {content.label}", "",
             ("Each general that other kinds specialize, and nothing above it in this project (or a type "
              "outside it that two or more of its kinds specialize), with its kinds, level by level. "
              "`[9ffd7a2c:14d101e0b1d2]` is the project's short id and the element's chunk id, as in "
              "`chunks.jsonl`."), ""]
    for h in hierarchies:
        lines += [f'<a id="{_anchor("hierarchy-" + h["root"])}"></a>', "",
                  f"## {_heading(h, content).removeprefix('Hierarchy: ')}", ""]
        lines += [("  " * ln["depth"]) + ln["text_refs"] for ln in h["lines"]] + [""]
    return "\n".join(lines)
