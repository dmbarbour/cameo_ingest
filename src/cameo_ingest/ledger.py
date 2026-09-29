"""Compact ledgers: one line per package, diagram, requirement and significant element.

Similarity search returns the top few chunks, which is poor at "list every X" and
"where does Y live" questions. Ledgers answer those: each ledger chunk covers one group
(one kind of item within one package), so a single retrieved chunk is a complete,
self-describing list with the project, source file and package in its header. Rows link
to the full element sections, which carry the per-element traces.

The same content is written to <project>/LEDGER.md for humans and file-based loaders.
"""

from __future__ import annotations

import re
from collections import defaultdict
from typing import TYPE_CHECKING

from . import semantics as sem
from .model import Element
from .text import front_matter, md_escape, md_inline, md_plain

if TYPE_CHECKING:
    from .emit import ProjectWriter

MAX_ROWS = 60
MAX_CHARS = 6000
TEXT_CHARS = 200
DOC_CHARS = 120
# SysML requirement relationships, read from the requirement's side:
# kind -> (phrase when the requirement is the target, phrase when it is the source).
REQ_LINKS = {
    "satisfy": ("satisfied by", "satisfies"),
    "verify": ("verified by", "verifies"),
    "derivereqt": ("derived into", "derived from"),  # client = derived, supplier = source
    "refine": ("refined by", "refines"),
    "trace": ("traced from", "traces to"),
    "copy": ("copied by", "copies"),
    "allocate": ("allocated from", "allocated to"),
}

FILE = "LEDGER.md"
_MD_LINK = re.compile(r"\[((?:\\.|[^\]\\])+)\]\([^)]*\)")


def _clip(text: str, n: int) -> str:
    text = " ".join(md_escape(text).split())
    return text if len(text) <= n else text[: n - 1].rstrip() + "…"


def _plural(n: int, word: str) -> str:
    return f"{n} {word}" if n == 1 else f"{n} {word}s"


def _natural_key(text: str) -> list:
    """Sort REQ.1.2 before REQ.1.10."""
    return [(0, int(t), "") if t.isdigit() else (1, 0, t.lower()) for t in re.split(r"(\d+)", text) if t]


def _first_sentence(text: str) -> str:
    text = " ".join(text.split())
    for end in (". ", "; "):
        i = text.find(end)
        if 0 < i < DOC_CHARS:
            return text[: i + 1]
    return _clip(text, DOC_CHARS)


class LedgerWriter:
    def __init__(self, w: ProjectWriter):
        self.w = w
        self.ix = w.ix
        self.md: list[str] = []

    # -- rows ------------------------------------------------------------------
    def counts(self, pkg: Element) -> tuple[int, int, int]:
        els = self.w._section_elements_in(pkg)
        reqs = sum(1 for e in els if sem.is_requirement(self.ix, e))
        dias = sum(1 for c in sem.children(self.ix, pkg) if c.kind == "Diagram")
        return len(els) - reqs, reqs, dias

    def package_row(self, pkg: Element) -> str:
        n_el, n_req, n_dia = self.counts(pkg)
        parts = [_plural(n_el, "element")] + ([_plural(n_req, "requirement")] if n_req else []) + \
                ([_plural(n_dia, "diagram")] if n_dia else [])
        return f"- {self.w.link(pkg.id, FILE)} `{self.ix.qualified_name(pkg.id)}` — {', '.join(parts)}"

    def diagram_row(self, dia_id: str) -> str:
        d = self.ix.diagrams[dia_id]
        row = f"- {self.w.link(dia_id, FILE)} — {d.diagram_type or 'diagram'}"
        if d.owner and d.owner in self.ix.elements and self.ix.elements[d.owner].kind not in sem.PACKAGE_KINDS:
            row += f"; context {md_inline(self.ix.label(d.owner))}"
        if d.shown:
            row += f"; {len(d.shown)} elements shown"
        return row

    def requirement_row(self, el: Element) -> str:
        f = sem.requirement_fields(self.ix, el)
        rid = f.get("Id", "").strip()
        row = f"- {'**' + rid + '** ' if rid else ''}{self.w.link(el.id, FILE)}"
        text = f.get("Text", "").strip()
        if text:
            row += f" — “{_clip(text, TEXT_CHARS)}”"
        links: dict[str, list[str]] = defaultdict(list)
        for r in self.w.rels_by_end.get(el.id, []):
            if r.metaclass not in ("Abstraction", "Dependency", "Realization", "Usage"):
                continue
            incoming = r.target == el.id
            phrases = REQ_LINKS.get(r.kind.lower(), (f"{r.kind} from", f"{r.kind} to"))
            links[phrases[0] if incoming else phrases[1]].append(md_inline(self.ix.label(r.source if incoming else r.target)))
        if links:
            row += " (" + "; ".join(f"{k}: {', '.join(v[:6])}{' …' if len(v) > 6 else ''}"
                                    for k, v in links.items()) + ")"
        return row

    def element_row(self, el: Element) -> str:
        st = self.ix.stereotype_names(el.id)
        label = " ".join(f"«{s}»" for s in st) or el.kind
        row = f"- {label} {self.w.link(el.id, FILE)}"
        doc = sem.documentation(self.ix, el)
        if doc:
            row += f" — {_first_sentence(doc)}"
        return row

    # -- groups ----------------------------------------------------------------
    def emit_group(self, kind: str, heading: str, pkg: Element | None, items: list[tuple[str, str]]) -> None:
        """Write one group of (element id, markdown row) to LEDGER.md and as ledger chunks.

        Chunk text drops link targets (long paths and ids that only add noise to
        embeddings); the ids travel in `metadata.element_ids`, row for row."""
        if not items:
            return
        where = f"package `{self.ix.qualified_name(pkg.id)}`" if pkg is not None else "whole project"
        self.md += [f"### {heading} — {where}", ""] + [r for _, r in items] + [""]
        parts: list[list[tuple[str, str]]] = [[]]
        size = 0
        for eid, r in items:
            plain = md_plain(_MD_LINK.sub(r"\1", r))
            if parts[-1] and (len(parts[-1]) >= MAX_ROWS or size + len(plain) > MAX_CHARS):
                parts.append([])
                size = 0
            parts[-1].append((eid, plain))
            size += len(plain)
        rows = items
        src = self.w.run.source
        chain = "!".join(self.w.project.trace_container) or self.w.project.name
        for i, part in enumerate(parts, 1):
            of = f" (part {i} of {len(parts)})" if len(parts) > 1 else ""
            header = (f"{heading} ledger{of} — Cameo project {self.w.project.name}, {where}. "
                      f"Source file `{src.path}` (archive path `{chain}`), {len(rows)} entries in this group.")
            text = header + "\n\n" + "\n".join(r for _, r in part)
            tr = self.w.trace(pkg) if pkg is not None else self.w.trace()
            self.w.chunk(kind=f"ledger:{kind}", title=f"{heading} ledger: {where}{of}", text=text, file=FILE,
                         el=pkg, trace=tr, salt=f"ledger:{kind}:{i}",
                         extra={"ledger": kind, "entries": len(part), "element_ids": [e for e, _ in part]})

    def write(self) -> None:
        ix, w = self.ix, self.w
        pkgs = sorted((ix.elements[p] for p in w.pkg_file), key=lambda e: ix.qualified_name(e.id))
        by_pkg: dict[str | None, list[Element]] = defaultdict(list)
        for el in ix.elements.values():
            if sem.is_section(ix, el) and el.kind not in sem.PACKAGE_KINDS and el.kind != "Diagram":
                p = w.package_of(el)
                by_pkg[p.id if p else None].append(el)
        dias_by_pkg: dict[str | None, list[str]] = defaultdict(list)
        for d in ix.diagrams.values():
            p = w.package_of(ix.elements[d.id])
            dias_by_pkg[p.id if p else None].append(d.id)

        n_req = sum(1 for els in by_pkg.values() for e in els if sem.is_requirement(ix, e))
        self.md += [
            f"# Ledger: {w.project.name}", "",
            ("Compact listing of everything in this project, grouped by package. Each entry links to its "
             "full description."), "",
            f"- **Source:** `{w.run.source.path}` (sha256 `{w.run.source.sha256}`)",
            f"- **Archive path:** `{'!'.join(w.project.trace_container) or w.project.name}`",
            f"- **Packages:** {len(pkgs)}; **diagrams:** {len(ix.diagrams)}; **requirements:** {n_req}", "",
            "## Packages", "",
        ]
        self.emit_group("packages", "Packages", None, [(p.id, self.package_row(p)) for p in pkgs])

        for kind, heading in (("diagrams", "Diagrams"), ("requirements", "Requirements"), ("elements", "Elements")):
            self.md += [f"## {heading}", ""]
            for p in [None] + [x.id for x in pkgs]:
                pkg = ix.elements[p] if p else None
                if kind == "diagrams":
                    ids = sorted(dias_by_pkg.get(p, []), key=lambda d: ix.diagrams[d].name.lower())
                    rows = [(d, self.diagram_row(d)) for d in ids]
                else:
                    want_req = kind == "requirements"
                    els = [e for e in by_pkg.get(p, []) if sem.is_requirement(ix, e) == want_req
                           and (want_req or e.name)]
                    if want_req:
                        # By requirement ID when every requirement has one; otherwise model order.
                        ids = [sem.requirement_fields(ix, e).get("Id", "").strip() for e in els]
                        if all(ids):
                            els = [e for _, e in sorted(zip(ids, els, strict=True), key=lambda x: _natural_key(x[0]))]
                        rows = [(e.id, self.requirement_row(e)) for e in els]
                    else:
                        els.sort(key=lambda e: (e.kind, (e.name or "").lower()))
                        rows = [(e.id, self.element_row(e)) for e in els]
                self.emit_group(kind, heading, pkg, rows)

        fm = front_matter({"title": f"Ledger {w.project.name}", "kind": "ledger",
                           "provenance": w.file_provenance(trace=w.trace().to_dict())})
        w.write_text(FILE, fm + "\n".join(self.md))
