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
from .treefiles import index_file, read_jsonl

if TYPE_CHECKING:
    from .view import ProjectView

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
                value = ix.qualified_name(v) if v in ix.elements else ix.label(v) if v in ix.external_refs else v
                for term in sorted(_ids(value)):
                    add(term, el.id, what_of(el), f"in its tag {tag}", f"{tag} = {value}", locator)
    return out


def places(project_dir: Path, content: ContentInfo) -> dict[str, list[Place]]:
    """Every identifier in one project, with the elements that hold it, as its build recorded them
    (`index/ids.jsonl`)."""
    out: dict[str, list[Place]] = defaultdict(list)
    for r in read_jsonl(index_file(project_dir, "ids"), missing_ok=True):
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
