"""An index of identifiers across every model in a tree (plan RF, RF-03).

The maintainer's first tracing need is "requirements to source files": from a requirement, wherever
it was read, to every model and input file that addresses it. The models come from several
companies, with no common structure, so the index assumes none. It reads each project's tables:
- **requirement ids:** a requirement's Id tag, or the bracketed id that starts its text (as DOORS
  imports write them);
- **ids in text:** tokens shaped like ids (`RWT-REG-002`, `AIT-401`, `REQ-1-OAD-0468`) in names,
  requirement text, documentation and tagged values;
- **relationships:** the elements at the other end of a relationship with a requirement that
  has an id (what satisfies, verifies, refines or derives from it), where a model has them.

An identifier gets an entry when it occurs on two elements or more, in one model or several:
that is where bringing the occurrences together adds something. Each entry lists every place,
with the project's label, what the element is, how it holds the id, a snippet, and a short
reference to the element's chunk (`[9ffd7a2c:14d101e0b1d2]`, which chunks.jsonl resolves), so
that a search for the id finds, in one chunk, every model that addresses it.
"""

from __future__ import annotations

import csv
import json
import re
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any

from . import chunks
from . import plain as pl
from . import semantics as sem
from .model import Element
from .provenance import TOOL, ContentInfo, chunk_ref, short_id
from .text import one_line

if TYPE_CHECKING:
    from .view import ProjectView

csv.field_size_limit(1 << 30)
ID = re.compile(r"(?<![\w-])[A-Z][A-Z0-9]*(?:-[A-Z0-9]+)+(?![\w-])")  # letters first, a hyphen, and a digit somewhere
SNIPPET = 90  # characters of context either side of a mention
NOT_IDS = re.compile(r"^(UTF-\d+|UCS-\d+|US-ASCII|ISO-8859-\d+|WINDOWS-\d+|X-[A-Z0-9-]+)$")  # encodings and such
FILE = "CROSSREF.md"


@dataclass
class Place:
    """One element holding an identifier."""

    project: str  # content sha256
    label: str  # the project's label ("TMT [9ffd7a2c]")
    element_id: str
    what: str  # "Requirement RWT-REG-002: The works shall ...", "Block Ozone Contactor"
    how: str  # "its id", "in its documentation", ...
    snippet: str
    chunk_id: str | None
    locator: str


def _rows(project_dir: Path, table: str) -> list[dict[str, str]]:
    path = project_dir / "tables" / f"{table}.csv"
    if not path.is_file():
        return []
    with path.open(encoding="utf-8", newline="") as f:
        return list(csv.DictReader(f))


def _ids(text: str) -> set[str]:
    """The identifiers in a text, as a set: iterate it sorted, so that output keeps one order
    whatever the hash seed."""
    return {m for m in ID.findall(text or "") if any(c.isdigit() for c in m) and not NOT_IDS.match(m)}


def _snippet(text: str, term: str) -> str:
    """The text around the first mention of `term` (or its start), cut at word boundaries."""
    text = one_line(text)
    i = max(text.find(term), 0)
    a = max(0, i - SNIPPET)
    b = min(len(text), i + len(term) + SNIPPET + (SNIPPET if text.find(term) < 0 else 0))
    if a > 0 and " " in text[a:i]:
        a = text.index(" ", a) + 1
    if b < len(text) and " " in text[i + len(term):b]:
        b = text.rindex(" ", i + len(term), b)
    return ("…" if a else "") + text[a:b].strip() + ("…" if b < len(text) else "")


def project_places(view: ProjectView, chunk_of: dict[str, str]) -> list[dict[str, Any]]:
    """Every identifier in one project, with the elements that hold it, from the in-memory model
    (AR-012R1): the records of its `index/ids.jsonl`, which the index across models merges."""
    ix = view.ix
    out: list[dict[str, Any]] = []
    seen: set[tuple[str, str]] = set()

    def add(term: str, el_id: str, what: str, how: str, text: str, locator: str) -> None:
        if (term, el_id) in seen:
            return
        seen.add((term, el_id))
        out.append({"term": term, "element_id": el_id, "what": what, "how": how, "snippet": _snippet(text, term),
                    "chunk_id": chunk_of.get(el_id), "locator": locator})

    def what_of(el: Element) -> str:
        return f"{sem.kind_word(ix, el)} {one_line(sem.label(ix, el.id))}"

    req_id: dict[str, str] = {}  # requirement element -> its id
    for el in ix.elements.values():
        req = sem.requirement(ix, el)
        if req is None:
            continue
        text = sem.requirement_fields(ix, el).get("Text", "")
        locator = view.trace(el).locator()
        if req.id and _ids(req.id):
            req_id[el.id] = req.id
            add(req.id, el.id, "Requirement" + (f" {el.name}" if el.name else ""), "its id",  # the text follows
                text or req.title, locator)
        for term in sorted(_ids(text) - {req.id}):
            add(term, el.id, what_of(el), "in its text", text, locator)
    for r in view.rels:  # the other end of a relationship with a requirement
        w = sem.wording(r.kind)
        verb = w.forward if w else r.kind.lower()
        locator = view.trace(ix.elements[r.id]).locator()
        for end, other, phrase in ((r.target, r.source, f"{verb} it"), (r.source, r.target, f"it {verb} this")):
            el = ix.elements.get(other)
            if end in req_id and el is not None and other != end:
                req = sem.requirement(ix, el)
                text = sem.documentation(ix, el) or (sem.requirement_fields(ix, el).get("Text", "") if req else "") \
                    or el.name or ""
                add(req_id[end], other, what_of(el), phrase, text, locator)
    for el in ix.elements.values():
        name, doc = el.name or "", sem.documentation(ix, el)
        if not (_ids(name) or _ids(doc)):
            continue
        locator = view.trace(el).locator()
        for term in sorted(_ids(name)):
            add(term, el.id, what_of(el), "in its name", name, locator)
        for term in sorted(_ids(doc)):
            add(term, el.id, what_of(el), "in its documentation", doc, locator)
    for app in ix.stereotypes.values():
        el = ix.elements.get(app.base)
        if el is None:
            continue
        locator = view.trace(el).with_(line=app.line).locator()
        for tag, vals in app.tags.items():
            for v in vals:
                value = ix.qualified_name(v) if v in ix.elements else v
                for term in sorted(_ids(value)):
                    add(term, el.id, what_of(el), f"in its tag {tag}", f"{tag} = {value}", locator)
    return out


def places(project_dir: Path, content: ContentInfo) -> dict[str, list[Place]]:
    """Every identifier in one project, with the elements that hold it, as its build recorded them
    (`index/ids.jsonl`)."""
    out: dict[str, list[Place]] = defaultdict(list)
    path = project_dir / "index" / "ids.jsonl"
    if path.is_file():
        for line in path.open(encoding="utf-8"):
            r = json.loads(line)
            out[r["term"]].append(Place(content.sha256, content.label, r["element_id"], r["what"], r["how"],
                                        r["snippet"], r["chunk_id"], r["locator"]))
    return out


def _heading(term: str, ps: list[Place]) -> str:
    labels = sorted({p.label for p in ps})
    shown = ", ".join(labels[:4]) + (f" and {len(labels) - 4} more" if len(labels) > 4 else "")
    return f"Index: {term}, in {len(labels)} model{'s' if len(labels) > 1 else ''} ({shown}), {len(ps)} places"


def _line(p: Place, refs: bool) -> str:
    ref = f"[{chunk_ref(p.project, p.chunk_id)}]" if refs and p.chunk_id else f"[{short_id(p.project)}]"
    return f"- {p.what}, {p.how}: {p.snippet} {ref}"


def _kept(index: dict[str, list[Place]]) -> list[tuple[str, list[Place]]]:
    """The identifiers held by two elements or more, each with its places in order: where it is
    an id first, then by project and element."""
    out = []
    for term in sorted(index):
        ps = sorted(index[term], key=lambda p: (p.how != "its id", p.label, p.what))
        if len({(p.project, p.element_id) for p in ps}) >= 2:
            out.append((term, ps))
    return out


def entries(index: dict[str, list[Place]], refs: bool = False) -> list[dict[str, Any]]:
    """Chunks for the identifiers held by two elements or more: a heading naming the models (by
    label and short id), then a line per place, split into parts that fit an embedding window.
    Each line ends with the project's short id, and with `refs` the element's chunk id too
    (`[9ffd7a2c:14d101e0b1d2]`; plan RF, decision 5), which chunks.jsonl resolves. Off by default:
    the references lengthen entries, so that fewer fit one window whole (RF-06)."""
    out = []
    for term, ps in _kept(index):
        texts = pl.parts(_heading(term, ps), "\n".join(_line(p, refs) for p in ps))
        for k, text in enumerate(texts, 1):
            out.append(chunks.make(("index:id", term, str(k)),
                                   f"Index: {term}" + (f" (part {k} of {len(texts)})" if len(texts) > 1 else ""), text, {
                "kind": "index:id", "file": f"{FILE}#{_anchor(term)}", "term": term,
                "contents": sorted({f"sha256:{p.project}" for p in ps}),
                "element_ids": [p.element_id for p in ps],
                "chunk_refs": [f"{short_id(p.project)}:{p.chunk_id}" for p in ps if p.chunk_id],
                "provenance": {"derivation": {"method": "assembled", "tool": TOOL, "inputs": [p.locator for p in ps]},
                               "locator": f"{FILE}#{_anchor(term)}"},
                **({"part": k, "parts": len(texts)} if len(texts) > 1 else {}),
            }))
    return out


def _anchor(term: str) -> str:
    return re.sub(r"[^a-z0-9-]+", "-", term.lower()).strip("-")


def page(index: dict[str, list[Place]]) -> str:
    """CROSSREF.md: the same entries, for reading and for Ctrl+F."""
    lines = ["# Identifiers across the models in this tree", "",
             ("Every identifier (requirement ids, ids in names, text, documentation and tagged values, and what "
              "relates to a requirement with an id) held by two elements or more, with each place. "
              "`[9ffd7a2c:14d101e0b1d2]` is the project's short id and the element's chunk id, as in `chunks.jsonl`; "
              "`rag/meta/_sources.json` gives the project's files."), ""]
    for term, ps in _kept(index):
        lines += [f'<a id="{_anchor(term)}"></a>', "", f"## {_heading(term, ps).removeprefix('Index: ')}", ""]
        lines += [_line(p, True) for p in ps] + [""]
    return "\n".join(lines)


# -- threads: derivation trees within a model (plan RF, RF-05) ------------------------------------
THREAD_DEPTH = 4  # levels of derivation shown below a thread's root
THREADS = "THREADS.md"  # each project's page of them


def project_threads(view: ProjectView, chunk_of: dict[str, str]) -> list[dict[str, Any]]:
    """Each derivation tree of requirements in one model, from the in-memory model (AR-014R2): from
    a requirement that others derive from, and nothing above it, down through what derives from it
    (to THREAD_DEPTH levels), each with what satisfies, verifies and refines it. The records of the
    project's `index/threads.jsonl`: a line per requirement, as text without and with the chunk
    references that `--line-refs` adds. Models without derive relationships have none."""
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
        text = text if len(text) <= 120 else text[:119].rsplit(" ", 1)[0] + "…"
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


def _thread_heading(t: dict[str, Any], content: ContentInfo) -> str:
    return f"Thread: what derives from {t['title']}, in {content.label}, {t['requirements']} requirements"


def thread_chunks(threads: list[dict[str, Any]], content: ContentInfo, refs: bool = False) -> list[dict[str, Any]]:
    """A chunk (in parts) per thread, its `file` relative to the project. A part after the first
    starts with its first line's ancestors, by title, so that each part says what its lines derive
    from (AR-027R2): a question such as "which tests verify the requirements derived from SN-02?"
    then finds its whole answer in a thread, where otherwise it is spread over a requirement, its
    children and their tests."""
    out = []
    for t in threads:
        rows = [("  " * ln["depth"]) + (ln["text_refs"] if refs else ln["text"]) for ln in t["lines"]]
        context: list[list[str]] = []
        above: list[str] = []  # the titles of the lines above the current one, by depth
        for ln in t["lines"]:
            above = above[:ln["depth"]]
            context.append([f"{'  ' * d}- {title} (continued)" for d, title in enumerate(above)])
            above.append(ln["title"])
        texts = pl.parts_with_context(_thread_heading(t, content), rows, context)
        for k, text in enumerate(texts, 1):
            out.append(chunks.make((content.sha256, "trace:thread", t["root"], str(k)),
                                   f"Thread: {t['title']}" + (f" (part {k} of {len(texts)})" if len(texts) > 1 else ""),
                                   text, {
                "kind": "trace:thread", "file": f"{THREADS}#{_anchor('thread-' + t['root'])}", "content": content.token,
                "element_id": t["root"], "element_ids": t["element_ids"],
                "provenance": {"derivation": {"method": "assembled", "tool": TOOL}, "locator": t["locator"]},
                **({"part": k, "parts": len(texts)} if len(texts) > 1 else {}),
            }))
    return out


def threads_page(threads: list[dict[str, Any]], content: ContentInfo) -> str:
    """THREADS.md: a project's threads, for reading, with each line's chunk reference."""
    lines = [f"# Threads: derivation trees in {content.label}", "",
             ("Each requirement that others derive from (and nothing above it), with what derives from it, "
              "level by level, and what satisfies, verifies or refines each. `[9ffd7a2c:14d101e0b1d2]` is the "
              "project's short id and the element's chunk id, as in `chunks.jsonl`."), ""]
    for t in threads:
        lines += [f'<a id="{_anchor("thread-" + t["root"])}"></a>', "",
                  f"## {_thread_heading(t, content).removeprefix('Thread: ')}", ""]
        lines += [("  " * ln["depth"]) + ln["text_refs"] for ln in t["lines"]] + [""]
    return "\n".join(lines)
