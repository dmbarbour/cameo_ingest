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
from typing import Any

from . import plain as pl
from .provenance import TOOL, ContentInfo, sha256_text
from .text import one_line, requirement_title

csv.field_size_limit(1 << 30)
ID = re.compile(r"(?<![\w-])[A-Z][A-Z0-9]*(?:-[A-Z0-9]+)+(?![\w-])")  # letters first, a hyphen, and a digit somewhere
_BRACKET_ID = re.compile(r"^\s*\[([A-Z][A-Z0-9]*(?:-[A-Z0-9]+)+)\]")
SNIPPET = 90  # characters of context either side of a mention
NOT_IDS = re.compile(r"^(UTF-\d+|UCS-\d+|US-ASCII|ISO-8859-\d+|WINDOWS-\d+|X-[A-Z0-9-]+)$")  # encodings and such
VERBS = {"satisfy": "satisfies", "verify": "verifies", "refine": "refines", "derivereqt": "is derived from",
         "trace": "traces to", "allocate": "is allocated to", "copy": "copies", "dependency": "depends on"}
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


def places(project_dir: Path, content: ContentInfo) -> dict[str, list[Place]]:
    """Every identifier in one project, with the elements that hold it."""
    chunk_of: dict[str, str] = {}  # element -> its first chunk (its meaning, not its details)
    chunks = project_dir / "index" / "chunks.jsonl"
    if chunks.is_file():
        for line in chunks.open(encoding="utf-8"):
            c = json.loads(line)
            el, kind = c["metadata"].get("element_id"), c["metadata"]["kind"]
            if el and kind in ("element", "requirement", "package", "diagram") and el not in chunk_of:
                chunk_of[el] = c["id"]
    elements = {e["id"]: e for e in _rows(project_dir, "elements")}
    req_text = {r["id"]: r["text"] for r in _rows(project_dir, "requirements")}
    out: dict[str, list[Place]] = defaultdict(list)
    seen: set[tuple[str, str]] = set()

    def add(term: str, el_id: str, what: str, how: str, text: str, locator: str) -> None:
        if (term, el_id) in seen:
            return
        seen.add((term, el_id))
        out[term].append(Place(content.sha256, content.label, el_id, what, how, _snippet(text, term),
                               chunk_of.get(el_id), locator))

    def kind_of(e: dict[str, str]) -> str:
        st = [s for s in (e.get("stereotypes") or "").split(";") if s]
        return st[0] if st else (e.get("type") or "").removeprefix("uml:")

    def what_of(e: dict[str, str]) -> str:
        if e["id"] in req_text:
            return "Requirement " + requirement_title(e["name"] or None, None, req_text[e["id"]])
        return f"{kind_of(e)} {e['name'] or '(unnamed)'}"

    req_id: dict[str, str] = {}  # requirement element -> its id
    for r in _rows(project_dir, "requirements"):
        m = _BRACKET_ID.match(r["text"] or "")
        rid = m.group(1) if m else (r["req_id"] or "")
        what = "Requirement " + requirement_title(r["name"] or None, r["req_id"] or None, r["text"])
        if rid and _ids(rid):
            req_id[r["id"]] = rid
            add(rid, r["id"], "Requirement" + (f" {r['name']}" if r["name"] else ""), "its id",  # the text follows
                r["text"] or what, r["trace"])
        for term in _ids(r["text"]) - {rid}:
            add(term, r["id"], what, "in its text", r["text"], r["trace"])
    for r in _rows(project_dir, "relationships"):  # the other end of a relationship with a requirement
        verb = VERBS.get(r["kind"].lower(), r["kind"].lower())
        for end, other, phrase in ((r["target_id"], r["source_id"], f"{verb} it"),
                                   (r["source_id"], r["target_id"], f"it {verb} this")):
            e = elements.get(other)
            if end in req_id and e is not None and other != end:
                text = e.get("documentation") or req_text.get(other, "") or e["name"]
                add(req_id[end], other, what_of(e), phrase, text, r["trace"])
    for e in elements.values():
        what = what_of(e)
        for term in _ids(e["name"]):
            add(term, e["id"], what, "in its name", e["name"], e["trace"])
        for term in _ids(e["documentation"]):
            add(term, e["id"], what, "in its documentation", e["documentation"], e["trace"])
    for t in _rows(project_dir, "tagged_values"):
        e = elements.get(t["element_id"])
        if e is None:
            continue
        what = what_of(e)
        for term in _ids(t["value"]):
            add(term, e["id"], what, f"in its tag {t['tag']}", f"{t['tag']} = {t['value']}", t["trace"])
    return out


def _heading(term: str, ps: list[Place]) -> str:
    labels = sorted({p.label for p in ps})
    shown = ", ".join(labels[:4]) + (f" and {len(labels) - 4} more" if len(labels) > 4 else "")
    return f"Index: {term}, in {len(labels)} model{'s' if len(labels) > 1 else ''} ({shown}), {len(ps)} places"


def _line(p: Place, refs: bool) -> str:
    ref = f"[{p.project[:8]}:{p.chunk_id[:12]}]" if refs and p.chunk_id else f"[{p.project[:8]}]"
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
    chunks = []
    for term, ps in _kept(index):
        texts = pl.parts(_heading(term, ps), "\n".join(_line(p, refs) for p in ps))
        for k, text in enumerate(texts, 1):
            chunks.append({
                "id": sha256_text(f"index:id|{term}|{k}")[:24],
                "title": f"Index: {term}" + (f" (part {k} of {len(texts)})" if len(texts) > 1 else ""),
                "text": text,
                "metadata": {
                    "kind": "index:id", "file": f"{FILE}#{_anchor(term)}", "term": term,
                    "contents": sorted({f"sha256:{p.project}" for p in ps}),
                    "element_ids": [p.element_id for p in ps],
                    "chunk_refs": [f"{p.project[:8]}:{p.chunk_id}" for p in ps if p.chunk_id],
                    "provenance": {"derivation": {"method": "assembled", "tool": TOOL,
                                                  "inputs": [p.locator for p in ps]},
                                   "locator": f"{FILE}#{_anchor(term)}"},
                    **({"part": k, "parts": len(texts)} if len(texts) > 1 else {}),
                },
            })
    return chunks


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


def _chunk_ids(project_dir: Path) -> dict[str, str]:
    """Each element's first chunk: its meaning, not its details."""
    out: dict[str, str] = {}
    path = project_dir / "index" / "chunks.jsonl"
    if path.is_file():
        for line in path.open(encoding="utf-8"):
            c = json.loads(line)
            el, kind = c["metadata"].get("element_id"), c["metadata"]["kind"]
            if el and kind in ("element", "requirement", "package", "diagram") and el not in out:
                out[el] = c["id"]
    return out


def threads(project_dir: Path, content: ContentInfo, refs: bool = False) -> list[dict[str, Any]]:
    """A chunk (in parts) per derivation tree of requirements in one model: from a requirement that
    others derive from, and nothing above it, down through what derives from it (to THREAD_DEPTH
    levels), each with what satisfies, verifies and refines it. A question such as "which tests
    verify the requirements derived from SN-02?" then finds its whole answer in one place, where
    otherwise it is spread over a requirement, its children and their tests. Models without derive
    relationships have none."""
    reqs = {r["id"]: r for r in _rows(project_dir, "requirements")}
    elements = {e["id"]: e for e in _rows(project_dir, "elements")}
    chunk_of = _chunk_ids(project_dir)
    children: dict[str, list[str]] = defaultdict(list)
    parents: dict[str, list[str]] = defaultdict(list)
    ends: dict[str, list[tuple[str, str]]] = defaultdict(list)  # requirement -> [(verb, element)]
    locators: dict[str, str] = {}
    for r in _rows(project_dir, "relationships"):
        kind, s, t = r["kind"].lower(), r["source_id"], r["target_id"]
        if kind == "derivereqt" and s in reqs and t in reqs:
            children[t].append(s)
            parents[s].append(t)
        elif t in reqs and kind in ("satisfy", "verify", "refine", "trace", "allocate") and s in elements:
            ends[t].append((VERBS[kind].replace("satisfies", "satisfied by").replace("verifies", "verified by")
                            .replace("refines", "refined by").replace("traces to", "traced from")
                            .replace("is allocated to", "allocated from"), s))
        locators[r["id"]] = r["trace"]

    def title(rid: str) -> str:
        r = reqs[rid]
        return requirement_title(r["name"] or None, r["req_id"] or None, r["text"])

    def ref(el: str) -> str:
        return f" [{content.sha256[:8]}:{chunk_of[el][:12]}]" if refs and el in chunk_of else ""

    def name(el: str) -> str:
        e = elements.get(el) or {}
        return title(el) if el in reqs else (e.get("name") or "(unnamed)")

    def owner(el: str) -> str:
        return (elements.get(el) or {}).get("qualified_name", "").rsplit("::", 2)[-2:][0]

    def walk(rid: str, depth: int, lines: list[str], seen: set[str]) -> None:
        if rid in seen or depth > THREAD_DEPTH:
            return
        seen.add(rid)
        text = one_line(reqs[rid]["text"] or "") if reqs[rid]["name"] else ""  # an unnamed one's title has it
        text = text if len(text) <= 120 else text[:119].rsplit(" ", 1)[0] + "…"
        line = "  " * depth + f"- {title(rid)}" + (f": {text}" if text else "") + ref(rid)
        by_verb: dict[str, list[str]] = defaultdict(list)
        related = ends.get(rid, [])
        names = [name(el) for _, el in related]
        for verb, el in related:  # where two share a name (a variant's blocks), their package tells them apart
            shown = name(el) + (f" (in {owner(el)})" if names.count(name(el)) > 1 and owner(el) else "")
            by_verb[verb].append(f"{shown}{ref(el)}")
        if by_verb:
            line += "; " + "; ".join(f"{verb} {', '.join(els)}" for verb, els in sorted(by_verb.items()))
        lines.append(line)
        for child in sorted(children.get(rid, []), key=title):
            walk(child, depth + 1, lines, seen)

    out = []
    for root in sorted(r for r in children if not parents.get(r)):
        lines: list[str] = []
        seen: set[str] = set()
        walk(root, 0, lines, seen)
        if len(seen) < 2:
            continue
        heading = (f"Thread: what derives from {title(root)}, in {content.label}, {len(seen)} requirements")
        texts = pl.parts(heading, "\n".join(lines))
        for k, text in enumerate(texts, 1):
            out.append({
                "id": sha256_text(f"{content.sha256}|trace:thread|{root}|{k}")[:24],
                "title": f"Thread: {title(root)}" + (f" (part {k} of {len(texts)})" if len(texts) > 1 else ""),
                "text": text,
                "metadata": {
                    "kind": "trace:thread", "file": f"{FILE}#{_anchor('thread-' + root)}", "content": content.token,
                    "element_id": root, "element_ids": sorted(seen),
                    "provenance": {"derivation": {"method": "assembled", "tool": TOOL},
                                   "locator": reqs[root]["trace"]},
                    **({"part": k, "parts": len(texts)} if len(texts) > 1 else {}),
                },
            })
    return out
