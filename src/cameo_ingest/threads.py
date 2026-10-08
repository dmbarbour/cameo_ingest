"""Threads (plan RF, RF-05): each derivation tree of requirements in one model, as an outline
(`outlines`), so that "which tests verify the requirements derived from SN-02?" finds its whole
answer in one place, where otherwise it is spread over a requirement, its children and their
tests. Records go to the project's `index/threads.jsonl` and `THREADS.md`; the tree's chunks
include them as `trace:thread`.
"""

from __future__ import annotations

from collections import defaultdict
from typing import TYPE_CHECKING, Any

from . import semantics as sem
from .outlines import Sort, outline_chunks, outline_page
from .provenance import ContentInfo, chunk_ref
from .text import clip, one_line

if TYPE_CHECKING:
    from .view import ProjectView

THREAD_DEPTH = 4  # levels of derivation shown below a thread's root
THREADS = "THREADS.md"  # each project's page of them


def project_threads(view: ProjectView, chunk_of: dict[str, str]) -> list[dict[str, Any]]:
    """Each derivation tree of requirements in one model, from the in-memory model (AR-014R2): from
    a requirement that others derive from, and nothing above it, down through what derives from it
    (to THREAD_DEPTH levels), each with what satisfies, verifies and refines it. The records of the
    project's `index/threads.jsonl`: a line per requirement, as text without and with the chunk
    references (`rootfiles.Assembly.line_refs`, off). Models without derive relationships have none."""
    ix = view.ix
    reqs = {el.id: req for el in ix.elements.values() if (req := sem.requirement(ix, el)) is not None}
    children: dict[str, list[str]] = defaultdict(list)
    parents: dict[str, list[str]] = defaultdict(list)
    ends: dict[str, list[tuple[str, str]]] = defaultdict(list)  # requirement -> [(verb, element)]
    for r in view.rels:
        kind, s_, t = r.kind.lower(), r.source, r.target
        if kind == "derivereqt" and s_ in reqs and t in reqs:
            children[t].append(s_)
            parents[s_].append(t)
        elif t in reqs and kind in ("satisfy", "verify", "refine", "trace", "allocate") and s_ in ix.elements:
            ends[t].append((sem.RELATIONS[kind].inverse, s_))

    def ref(el: str) -> str:
        return f" [{chunk_ref(view.content.sha256, chunk_of[el])}]" if el in chunk_of else ""

    def name(el: str) -> str:
        return reqs[el].title if el in reqs else one_line(sem.label(ix, el))

    def owner(el: str) -> str:
        return ix.qualified_name(el).rsplit("::", 2)[-2:][0]

    def walk(rid: str, depth: int, lines: list[dict[str, Any]], seen: set[str]) -> None:
        if rid in seen or depth > THREAD_DEPTH:
            return
        seen.add(rid)
        el = ix.elements[rid]
        text = one_line(sem.requirement_fields(ix, el).get("Text", "")) if el.name else ""  # an unnamed one's title has it
        text = clip(text, 120)
        head = f"- {reqs[rid].title}" + (f": {text}" if text else "")
        plain, refs = [head], [head + ref(rid)]
        by_verb: dict[str, list[tuple[str, str]]] = defaultdict(list)  # verb -> [(shown, element)]
        related = ends.get(rid, [])
        names = [name(e) for _, e in related]
        for verb, e in related:  # where two share a name (a variant's blocks), their package tells them apart
            by_verb[verb].append((name(e) + (f" (in {owner(e)})" if names.count(name(e)) > 1 and owner(e) else ""), e))
        if by_verb:
            plain.append("; " + "; ".join(f"{verb} {', '.join(sh for sh, _ in els)}" for verb, els in sorted(by_verb.items())))
            refs.append("; " + "; ".join(f"{verb} {', '.join(sh + ref(e) for sh, e in els)}"
                                         for verb, els in sorted(by_verb.items())))
        lines.append({"depth": depth, "id": rid, "title": reqs[rid].title, "text": "".join(plain),
                      "text_refs": "".join(refs)})
        for child in sorted(children.get(rid, []), key=name):
            walk(child, depth + 1, lines, seen)

    out = []
    for root in sorted(r for r in children if not parents.get(r)):
        lines: list[dict[str, Any]] = []
        seen: set[str] = set()
        walk(root, 0, lines, seen)
        if len(seen) >= 2:
            out.append({"root": root, "title": reqs[root].title, "requirements": len(seen),
                        "element_ids": sorted(seen), "locator": view.trace(ix.elements[root]).locator(),
                        "lines": lines})
    return out


def _heading(t: dict[str, Any], content: ContentInfo) -> str:
    return f"Thread: what derives from {t['title']}, in {content.label}, {t['requirements']} requirements"


SORT = Sort("trace:thread", "Thread", THREADS, _heading, lambda t: t["root"])


def thread_chunks(threads: list[dict[str, Any]], content: ContentInfo, refs: bool = False) -> list[dict[str, Any]]:
    """A chunk (in parts) per thread, its `file` relative to the project (AR-027R2)."""
    return outline_chunks(SORT, threads, content, refs)


def threads_page(threads: list[dict[str, Any]], content: ContentInfo) -> str:
    """THREADS.md: a project's threads, for reading, with each line's chunk reference."""
    return outline_page(SORT, threads, content, f"Threads: derivation trees in {content.label}",
                        "Each requirement that others derive from (and nothing above it), with what derives from it, "
                        "level by level, and what satisfies, verifies or refines each. `[9ffd7a2c:14d101e0b1d2]` is the "
                        "project's short id and the element's chunk id, as in `chunks.jsonl`.")
