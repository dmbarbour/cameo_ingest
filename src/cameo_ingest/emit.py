"""Write RAG-ready outputs for one project: Markdown, CSV and JSON/JSONL.

Layout (per project, under <out>/<project-slug>/):

    README.md                 overview: counts, top-level packages, diagrams
    packages/<path>.md        one file per package, one section per element
    diagrams/<name>.md        one file per diagram (+ rendered image if available)
    tables/*.csv              elements, relationships, requirements, properties,
                              tagged_values, diagrams
    index/elements.jsonl      every element with full structure
    index/hierarchy.json      containment tree of section-level elements
    index/chunks.jsonl        one self-contained chunk per section, with metadata

Every Markdown file has JSON-valued YAML front matter with a `provenance` block; every
section carries a visible `trace:` locator; every CSV row has a `trace` column; every
chunk has `metadata.provenance`. Text produced by an LLM is always labelled as such.
"""

from __future__ import annotations

import csv
import json
from collections import defaultdict
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from . import chunks
from . import diagrams as dg
from . import modules as mod
from . import plain as pl
from . import sections as sx
from . import semantics as sem
from .archive import Project
from .layout import Layout
from .ledger import LedgerWriter
from .model import Element, ModelIndex
from .provenance import TOOL, ContentInfo, Trace, generated_by
from .text import front_matter, md_inline, one_line, plural, shown_value, slug, tidy

SKIP_MEMBER_ROLES = {
    "ownedComment", "lowerValue", "upperValue", "defaultValue", "specification",
    "generalization", "interfaceRealization", "ownedDiagram",
}


@dataclass
class Annotation:
    """A piece of derived text (LLM description, rendered image...) about an element."""

    label: str
    text: str
    trace: Trace
    image: str | None = None  # path relative to the project dir
    module: int | None = None  # about this module of a large diagram, or part of a large package (plan DV)
    parts: tuple[int, int] | None = None  # about this run of a large package's parts


class ProjectWriter:
    def __init__(self, content: ContentInfo, project: Project, ix: ModelIndex, root: Path,
                 annotations: dict[str, list[Annotation]] | None = None,
                 layouts: dict[str, Layout] | None = None, modules: tuple[int, int, int] = mod.DEFAULTS):
        self.layouts = layouts or {}
        self.modules = modules  # large diagrams: split above N shapes, into MIN to MAX
        self.content = content
        self.project = project
        self.ix = ix
        self.root = root
        self.ann = annotations if annotations is not None else {}
        self.chunks: list[dict[str, Any]] = []  # written to index/chunks.jsonl
        self.rels = sem.relationships(ix)
        self.rel_by_id = {r.id: r for r in self.rels}
        self.rels_by_end: dict[str, list[sem.Relationship]] = defaultdict(list)
        for r in self.rels:
            self.rels_by_end[r.source].append(r)
            self.rels_by_end[r.target].append(r)
        self.flows = sem.item_flows(ix)
        self.notes: dict[str, list[Element]] = defaultdict(list)  # comments owned elsewhere, by what they annotate
        for c in ix.elements.values():
            if c.kind == "Comment" and c.attrs.get("body"):
                for target in sem.refs(c, "annotatedElement"):
                    if target != c.owner:
                        self.notes[target].append(c)
        self._graphs: dict[str, dg.DiagramGraph] = {}
        self._parts: dict[str, mod.Partition | None] = {}
        self.package_parts: dict[str, list[list[str]]] = {}  # large packages, summarized in parts (element ids)
        self.diagrams_showing: dict[str, list[str]] = defaultdict(list)
        for d in ix.diagrams.values():
            for e in d.shown:
                self.diagrams_showing[e].append(d.id)
        self.file_of: dict[str, str] = {}  # element id -> relative md path (+anchor)
        self._plan_files()

    def graph(self, dia_id: str) -> dg.DiagramGraph | None:
        """The diagram's shapes and connections, numbered (built once)."""
        layout = self.layouts.get(dia_id)
        if layout is None:
            return None
        if dia_id not in self._graphs:
            self._graphs[dia_id] = dg.build(self.ix, layout, self.rel_by_id, self.flows)
        return self._graphs[dia_id]

    def partition(self, dia_id: str) -> mod.Partition | None:
        """A large diagram's modules (computed once); None for a diagram drawn whole."""
        if dia_id not in self._parts:
            g = self.graph(dia_id)
            self._parts[dia_id] = mod.partition(g, *self.modules) if g is not None else None
        return self._parts[dia_id]

    def module_image(self, dia_id: str, num: int) -> str:
        return f"{self.dia_file[dia_id].removesuffix('.md')}.modules/M{num}.png"

    # -- provenance ------------------------------------------------------------
    def trace(self, el: Element | None = None, **kw: Any) -> Trace:
        base = Trace(content_sha256=self.content.sha256)
        if el is not None:
            base = base.with_(entry=el.entry, xmi_id=el.id, line=el.line,
                              qualified_name=self.ix.qualified_name(el.id) or None)
        return base.with_(**kw) if kw else base

    def file_provenance(self, **extra: Any) -> dict[str, Any]:
        # Only what the content itself determines: where it was found is looked up by
        # the token (INDEX.md, provenance.jsonl, state.sqlite).
        return {
            "content": self.content.token,
            "name": self.content.name,
            "model_entries": self.project.model_entries,
            "exporter": self.ix.exporter,
            "tool": TOOL,
            **extra,
        }

    # -- planning --------------------------------------------------------------
    def package_of(self, el: Element) -> Element | None:
        cur = self.ix.get(el.owner)
        while cur is not None and cur.kind not in sem.PACKAGE_KINDS:
            cur = self.ix.get(cur.owner)
        return cur

    def _plan_files(self) -> None:
        used: set[str] = set()
        self.pkg_file: dict[str, str] = {}
        for el in self.ix.elements.values():
            if el.kind in sem.PACKAGE_KINDS:
                base = slug(self.ix.qualified_name(el.id).replace("::", "__") or el.id, 150)
                name, n = base, 1
                while name.lower() in used:
                    n += 1
                    name = f"{base}_{n}"
                used.add(name.lower())
                self.pkg_file[el.id] = f"packages/{name}.md"
        self.dia_file: dict[str, str] = {}
        for d in self.ix.diagrams.values():
            base = slug(d.name or d.id)
            name, n = base, 1
            while f"d/{name}".lower() in used:
                n += 1
                name = f"{base}_{n}"
            used.add(f"d/{name}".lower())
            self.dia_file[d.id] = f"diagrams/{name}.md"
        for el in self.ix.elements.values():
            if el.kind == "Diagram" and el.id in self.dia_file:
                self.file_of[el.id] = self.dia_file[el.id]
            elif el.kind in sem.PACKAGE_KINDS:
                self.file_of[el.id] = self.pkg_file[el.id]
            elif sem.is_section(self.ix, el):
                pkg = self.package_of(el)
                if pkg is not None:
                    self.file_of[el.id] = f"{self.pkg_file[pkg.id]}#{self.anchor(el)}"

    def anchor(self, el: Element) -> str:
        # Only the name part is shortened, so the id always keeps anchors unique. Ids keep
        # their case: EMF-style ids (e.g. "_2VHvQXmuEe6Klrv3p62i1g") are case-sensitive.
        return f"{slug(el.name or el.kind, 80).lower()}-{slug(el.id, 200)}"

    def refs(self, from_file: str) -> dg.Refs:
        """Links from `from_file` to the pages of elements that have one, for diagram lists."""
        return dg.Refs(lambda e: _relpath(self.file_of[e], from_file) if self.file_of.get(e) else None)

    def link(self, target_id: str, from_file: str, text: str | None = None) -> str:
        """A link to the element's page, labelled with `text` or the element's label; the label
        alone when the element has no page."""
        label = md_inline(text if text is not None else sem.label(self.ix, target_id))
        dest = self.file_of.get(target_id)
        if not dest:
            return label
        rel = _relpath(dest, from_file)
        return f"[{label}]({rel})"

    # -- writing ---------------------------------------------------------------
    def write_text(self, rel: str, text: str) -> None:
        p = self.root / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(text, encoding="utf-8")

    def chunk(self, *, kind: str, title: str, text: str, file: str, el: Element | None,
              trace: Trace, extra: dict[str, Any] | None = None, salt: str = "") -> None:
        if kind.startswith("generated:") and pl.tokens(text) > pl.BUDGET:
            # Generated text too long for one embedding window: in parts, each under its heading.
            first, _, rest = text.partition("\n")
            pieces = pl.parts(first, rest.strip())
            for k, piece in enumerate(pieces, 1):
                self._chunk(kind, title, piece, file, el, trace, {**(extra or {}), "piece": k, "pieces": len(pieces)},
                            f"{salt}#{k}")
            return
        self._chunk(kind, title, text, file, el, trace, extra, salt)

    def _chunk(self, kind: str, title: str, text: str, file: str, el: Element | None, trace: Trace,
               extra: dict[str, Any] | None, salt: str) -> None:
        self.chunks.append(chunks.make((self.content.sha256, kind, el.id if el else file, salt), title, text, {
            "kind": kind,
            "file": file,
            "project": self.content.name,
            "content": self.content.token,
            "element_id": el.id if el else None,
            "element_type": el.type if el else None,
            "qualified_name": self.ix.qualified_name(el.id) if el else None,
            "stereotypes": self.ix.stereotype_names(el.id) if el else [],
            "provenance": trace.to_dict(),
            **(extra or {}),
        }))

    def heading(self, el: Element, kind_word: str | None = None) -> str:
        """The plain style's heading: what the element is, its readable name, where it is."""
        ix = self.ix
        name, kind_word = sem.label(ix, el.id), kind_word or sem.kind_word(ix, el)
        owner = ix.qualified_name(el.owner) if el.owner else ""  # not the element's: an unnamed one's ends with its owner
        return f"{kind_word} {one_line(name)} {pl.where(owner, self.content.label)}"

    def section_chunks(self, kind: str, el: Element, view: sx.Section, file: str, trace: Trace,
                       heading: str | None = None, extra: dict[str, Any] | None = None) -> None:
        """An element's (or package's, or diagram's) chunks: its meaning and its details, as plain
        parts under its heading (plan RE-08)."""
        title = (extra or {}).pop("title", None) or f"{el.kind} {self.ix.qualified_name(el.id)}"
        meaning, details = view.plain(heading or self.heading(el))
        for suffix, texts in (("", meaning), (":details", details)):
            for k, text in enumerate(texts, 1):
                more = {"part": k, "parts": len(texts)} if len(texts) > 1 else {}
                self.chunk(kind=kind + suffix, title=title + (", details" if suffix else ""), text=text, file=file,
                           el=el, trace=trace, extra={**(extra or {}), **more}, salt=f"{suffix}#{k}")

    def text_chunks(self, *, kind: str, title: str, text: str, file: str, el: Element | None, trace: Trace,
                    extra: dict[str, Any] | None = None, salt: str = "") -> None:
        """A chunk of running text (the project overview): plain, in parts under its first line."""
        first, _, rest = pl.plain(text).partition("\n")
        texts = pl.parts(first, rest.strip())
        for k, part in enumerate(texts, 1):
            more = {"part": k, "parts": len(texts)} if len(texts) > 1 else {}
            self.chunk(kind=kind, title=title, text=part, file=file, el=el, trace=trace,
                       extra={**(extra or {}), **more}, salt=f"{salt}#{k}")

    def write_steps(self) -> int:
        """How many times `write_all` calls `tick`."""
        return len(self.pkg_file) + len(self.dia_file) + 4

    def write_all(self, tick: Callable[[], None] = lambda: None) -> None:
        """Write every file; `tick` is called after each page and each of the four
        project-wide steps (README, ledger, tables, indices)."""
        for pkg_id, rel in self.pkg_file.items():
            self.write_package(self.ix.elements[pkg_id], rel)
            tick()
        for dia_id, rel in self.dia_file.items():
            self.write_diagram(dia_id, rel)
            tick()
        for step in (self.write_readme, LedgerWriter(self).write, self.write_tables, self.write_indices):
            step()
            tick()

    # -- element sections ------------------------------------------------------
    def section(self, el: Element, from_file: str, level: int, generated: bool = True, trace: bool = True) -> str:
        """Markdown for one element. `generated=False` omits LLM-derived annotations, so
        chunks of extracted text keep a pure `extracted` provenance. `trace=False` omits the
        trace line, whose locator depends on where the source was found, not on what it says."""
        lines = self.section_view(el, generated, from_file).markdown(level, self.linker(from_file))
        if trace:
            lines += [f"<sub>trace: `{self.trace(el).locator()}`</sub>", ""]
        return "\n".join(lines)

    def linker(self, from_file: str) -> sx.Link:
        return lambda id_, label: self.link(id_, from_file, label)

    def section_view(self, el: Element, generated: bool = True, from_file: str = "") -> sx.Section:
        """One element's section as data (AR-003R2): pages render it as Markdown, chunks as plain
        text. `generated=False` leaves out LLM-derived annotations."""
        ix = self.ix
        st_txt = " ".join(f"«{s}»" for s in ix.stereotype_names(el.id))
        title = sx.line(st_txt + " " if st_txt else "", sx.name(sem.label(ix, el.id)))
        fields: list[tuple[str, sx.Line]] = [("Kind", sx.line(el.kind))]
        qn = ix.qualified_name(el.id)
        if qn:
            fields.append(("Qualified name", sx.line(sx.Span(qn, "code"))))
        rq = sem.requirement(ix, el)
        if rq is not None and rq.id:  # the id people use, and a database number apart (AR-010R3)
            fields.append(("Requirement ID", sx.line(rq.id)))
            if rq.db_id:
                fields.append(("Database number", sx.line(rq.db_id)))
        for k in ("isAbstract", "visibility", "isEncapsulated", "isActive"):
            if k in el.attrs and el.attrs[k] not in ("false", "public"):
                fields.append((k, sx.line(el.attrs[k])))
        types = sem.refs(el, "type")
        if types:
            fields.append(("Type", sx.line(self.ref(types[0]))))
        classifiers = sem.refs(el, "classifier")  # what an instance specification is an instance of (FU-022)
        if classifiers:
            fields.append(("Classifier", self.refs_line(classifiers)))
        gens = [r for r in self.rels_by_end.get(el.id, []) if r.metaclass == "Generalization" and r.source == el.id]
        if gens:
            fields.append(("Specializes", self.refs_line([g.target for g in gens])))
        blocks: list[sx.Block] = []
        req = sem.requirement_fields(ix, el) if rq is not None else {}
        if "Text" in req:
            blocks.append(sx.Block("Requirement text", [sx.line(tidy(req["Text"]))], quoted=True))
        doc = sem.documentation(ix, el)
        if doc:
            blocks.append(sx.Block("Documentation", [sx.line(tidy(doc))]))
        notes = [c.attrs["body"].strip() for c in self.notes.get(el.id, [])]  # a diagram's notes about it
        blocks.append(sx.Block("Notes", [sx.line(f"- {tidy(one_line(n))}") for n in notes if n]))
        spec = next(iter(sem.children(ix, el, "specification")), None)
        if spec is not None and sem.value_text(ix, spec):
            lang = spec.attrs.get("language", "")
            blocks.append(sx.Block(f"Specification{f' ({lang})' if lang else ''}",
                                   [sx.line(sem.value_text(ix, spec) or "")], fenced=True))
        blocks.append(sx.Block("Tagged values", [sx.line(f"- «{s}» {k} = " + v.replace("\n", "\n  "))
                                                 for s, k, v in self.tagged_values(el)], form="list", detail=True))
        blocks.append(sx.Block("Members", self.members(el, depth=0), form="list", detail=True))
        rels = [r for r in self.rels_by_end.get(el.id, []) if r.metaclass != "Generalization" or r.target == el.id]
        rel_lines = []
        for r in rels:
            conveyed = [sem.label(ix, t) for t in sem.refs(ix.elements[r.id], "conveyed")]
            # A dependency reads with a verb, so that its direction is not left to an arrow
            # (FU-021, as FU-013 for diagrams): "is derived from [Y]", "[X] satisfies this".
            w = sem.wording(r.kind, r.metaclass)
            verb = w.forward if w else None
            if r.source == el.id:
                shown = (f"{verb} " if verb else "→ ", self.ref(r.target))
            else:
                shown = ("" if verb else "← ", self.ref(r.source), f" {verb} this" if verb else "")
            rel_lines.append(sx.line(f"- {r.kind}{': ' if verb else ' '}", *shown,
                                     *((" (conveys ", *self.names(conveyed), ")") if conveyed else ())))
        blocks.append(sx.Block("Relationships", rel_lines, form="list"))
        blocks.append(sx.Block("Shown in diagrams", [sx.line(self.ref(d)) for d in self.diagrams_showing.get(el.id, [])],
                               form="inline"))
        for a in self.ann.get(el.id, []):
            if (generated or a.trace.derivation.method != "llm") and a.module is None and a.parts is None:
                blocks.append(self.annotation_block(a, from_file))
        return sx.Section(title, fields, blocks)

    def ref(self, id_: str) -> sx.Span:
        """A reference to an element: its label, linked on pages to its page."""
        return sx.ref(id_, sem.label(self.ix, id_))

    def refs_line(self, ids: list[str]) -> sx.Line:
        return sx.line(*[p for k, i in enumerate(ids) for p in ((", ",) if k else ()) + (self.ref(i),)])

    def names(self, labels: list[str]) -> list[str | sx.Span]:
        return [p for k, x in enumerate(labels) for p in ((", ",) if k else ()) + (sx.name(x),)]

    def generated_heading(self, a: Annotation, el: Element, kind_word: str | None = None, what: str = "",
                          names: list[str] = (), names_word: str = "covering") -> str:
        """A generated chunk's heading (AR-004R1): what it is, of which element, as its plain
        heading says it (the project included), then the names it covers as far as room allows,
        and its origin. A heading takes at most a quarter of a part (AR-004R2)."""
        head = f"{a.label} of {self.heading(el, kind_word)}" + (f", {what}" if what else "")
        origin = f" ({generated_by(a.trace.derivation)})"
        room = pl.HEADING - pl.tokens(head) - pl.tokens(origin) - 2
        if names and room > 8:
            head += ", " + pl.cap(f"{names_word} " + "; ".join(names), room)
        return head + origin

    def generated_chunks(self, el: Element, file: str, kind_word: str | None = None) -> None:
        """One chunk per LLM-derived annotation, with the LLM derivation as provenance."""
        for i, a in enumerate(self.ann.get(el.id, [])):
            if a.trace.derivation.method != "llm" or not a.text or a.module is not None or a.parts is not None:
                continue
            what = f"{el.kind} {self.ix.qualified_name(el.id)}"
            text = f"{self.generated_heading(a, el, kind_word)}\n\n{a.text}"
            self.chunk(kind=f"generated:{a.label.lower().replace(' ', '_')}", title=f"{a.label}: {what}",
                       text=text, file=file, el=el, trace=a.trace, salt=str(i))

    def annotation_block(self, a: Annotation, from_file: str) -> sx.Block:
        before = [f"![{a.label}]({_relpath(a.image, from_file)})", ""] if a.image else []
        return sx.Block(a.label, [sx.line(tidy(a.text))] if a.text else [], before=before,
                        label=f"**{a.label}** _({generated_by(a.trace.derivation)})_:")

    def annotation_md(self, a: Annotation, from_file: str) -> list[str]:
        out = []
        if a.image:
            out += [f"![{a.label}]({_relpath(a.image, from_file)})", ""]
        if a.text:
            out += [f"**{a.label}** _({generated_by(a.trace.derivation)})_:", "", tidy(a.text), ""]
        return out

    def tagged_values(self, el: Element) -> list[tuple[str, str, str]]:
        out = []
        for app in self.ix.applications(el.id):
            for k, vals in app.tags.items():
                if k in ("Id", "Text") and sem.is_requirement(self.ix, el):
                    continue
                shown = ", ".join(sem.label(self.ix, v) if v in self.ix.elements else v.strip() for v in vals if v.strip())
                if shown:
                    out.append((app.name, k, shown_value(shown)))
        return out

    def members(self, el: Element, depth: int) -> list[sx.Line]:
        if depth > 3:
            return []
        ix = self.ix
        out: list[sx.Line] = []
        indent = "  " * depth
        for c in sem.children(ix, el):
            if c.role in SKIP_MEMBER_ROLES:
                continue
            if sem.is_section(ix, c):
                if depth == 0:
                    out.append(sx.line(f"{indent}- {c.kind} ", self.ref(c.id)))
                continue
            st = ix.stereotype_names(c.id)
            desc: list[str | sx.Span] = [f"{indent}- ", sx.Span(c.role, "italic"), f" {c.kind}"]
            if st:
                desc.append(" " + " ".join(f"«{s}»" for s in st))
            if c.name:
                desc += [" ", sx.name(c.name, "bold")]
            t = sem.refs(c, "type")
            if t:
                desc += [" : ", self.ref(t[0])]
            m = sem.multiplicity(ix, c)
            if m and m != "1":
                desc.append(f" [{m}]")
            dv = sem.value_text(ix, next(iter(sem.children(ix, c, "defaultValue")), None))
            if dv:
                desc += [" = ", sx.Span(dv, "code")]
            if c.attrs.get("aggregation") in ("composite", "shared"):
                desc.append(f" ({c.attrs['aggregation']})")
            if c.kind == "Slot":
                feat = sem.refs(c, "definingFeature")
                vals = [sem.value_text(ix, v) for v in sem.children(ix, c, "value")]
                desc = [f"{indent}- slot ", sx.name(sem.label(ix, feat[0])) if feat else "?",
                        f" = {', '.join(v or '' for v in vals)}"]
            if c.kind in sem.RELATIONSHIP_KINDS:
                r = self.rel_by_id.get(c.id)
                if r:
                    desc += [": ", sx.name(sem.label(ix, r.source)), " → ", sx.name(sem.label(ix, r.target))]
                flow = sem.flow_label(ix, c)  # a transition's trigger and guard, a flow's guard
                if flow:
                    desc += [" — ", sx.name(flow)]
            if c.kind == "Trigger" and sem.trigger_text(ix, c):
                desc += [" — ", sx.name(sem.trigger_text(ix, c) or "")]
            spec = sem.value_text(ix, next(iter(sem.children(ix, c, "specification")), None))
            if spec:
                desc += [" — ", sx.Span(spec, "code")]
            elif c.kind in sem.VALUE_KINDS and not c.name and not dv and sem.value_text(ix, c):
                desc += [" — ", sx.Span(sem.value_text(ix, c) or "", "code")]  # a guard, say: the value is the point
            doc = sem.documentation(ix, c)
            if doc:
                desc.append(" — " + tidy(doc).replace("\n", " "))
            out.append(sx.line(*desc))
            out += self.members(c, depth + 1)
        return out

    # -- files -----------------------------------------------------------------
    def write_package(self, pkg: Element, rel: str) -> None:
        ix = self.ix
        qn = ix.qualified_name(pkg.id) or pkg.name or pkg.id
        body = [self.section(pkg, rel, 1)]
        body += self.part_sections(pkg, rel)
        subs = [c for c in sem.children(ix, pkg) if c.kind in sem.PACKAGE_KINDS]
        if subs:
            body.append("## Sub-packages\n")
            body += [f"- {self.link(s.id, rel)}" for s in subs]
            body.append("")
        dias = [c for c in sem.children(ix, pkg) if c.kind == "Diagram"]
        if dias:
            body.append("## Diagrams\n")
            body += [f"- {self.link(d.id, rel)}" for d in dias]
            body.append("")
        pkg_trace = self.trace(pkg)
        self.section_chunks("package", pkg, self.section_view(pkg, generated=False), rel, pkg_trace,
                            heading=self.heading(pkg, "Package"), extra={"title": f"Package {qn}"})
        self.generated_chunks(pkg, rel, "Package")
        # Every non-package section element whose nearest package is this one.
        for el in self._section_elements_in(pkg):
            body += [f'<a id="{self.anchor(el)}"></a>\n', self.section(el, rel, 2)]
            anchor = f"{rel}#{self.anchor(el)}"
            self.section_chunks("requirement" if sem.is_requirement(ix, el) else "element", el,
                                self.section_view(el, generated=False), anchor, self.trace(el))
            self.generated_chunks(el, anchor)
        fm = front_matter({
            "title": f"Package {qn}",
            "kind": "package",
            "element_id": pkg.id,
            "qualified_name": qn,
            "provenance": self.file_provenance(trace=pkg_trace.to_dict()),
        })
        self.write_text(rel, fm + "\n".join(body))

    def part_sections(self, pkg: Element, rel: str) -> list[str]:
        """A large package's parts, as summarized (FU-005, plan DV-05): the elements of each,
        its summary, and the summaries of runs of parts, each also a chunk that names the
        elements it covers."""
        parts = self.package_parts.get(pkg.id)
        anns = [a for a in self.ann.get(pkg.id, []) if a.module is not None or a.parts is not None]
        if not parts or not anns:
            return []
        ix = self.ix
        what = f"Package {ix.qualified_name(pkg.id)}"
        lines = ["## Parts, summarized", "",
                 (f"The package is large, so its elements were summarized in {len(parts)} parts, and its summary "
                  "above was built from these (through runs of parts, when there are many)."), ""]
        for a in sorted(anns, key=lambda a: (a.parts is None, a.parts or (a.module, a.module))):  # runs, then parts
            first, last = a.parts or (a.module, a.module)  # type: ignore[assignment]
            ids = [e for part in parts[first - 1:last] for e in part]
            if a.parts is None:
                anchor, title = f"part-{first}", f"Part {first} of {len(parts)}"
                links = ", ".join(self.link(e, rel) for e in ids[:25]) + (", ..." if len(ids) > 25 else "")
                lines += [f'<a id="{anchor}"></a>', "", f"**{title}** ({plural(len(ids), 'element')}: {links}):", ""]
            else:
                anchor, title = f"parts-{first}-{last}", f"Parts {first} to {last} of {len(parts)}"
                lines += [f'<a id="{anchor}"></a>', "", f"**{title}** ({plural(len(ids), 'element')}):", ""]
            lines += self.annotation_md(a, rel)
            if a.trace.derivation.method != "llm" or not a.text:
                continue
            heading = self.generated_heading(a, pkg, "Package", title[0].lower() + title[1:],
                                             [sem.label(ix, e) for e in ids])
            covers = {"number": first, "last": last, "of": len(parts), "anchor": f"{rel}#{anchor}", "elements": ids}
            self.chunk(kind="generated:module_summary", title=f"{title}: {what}", text=f"{heading}\n\n{a.text}",
                       file=rel, el=pkg, trace=a.trace, salt=anchor, extra={"covers": covers})
            lines += [f"<sub>trace: `{a.trace.locator()}`</sub>", ""]
        return lines

    def _section_elements_in(self, pkg: Element) -> list[Element]:
        out = []
        stack = list(reversed(pkg.children))
        while stack:
            el = self.ix.elements.get(stack.pop())
            if el is None or el.kind in sem.PACKAGE_KINDS or el.kind == "Diagram":
                continue
            if sem.is_section(self.ix, el):
                out.append(el)
            stack.extend(reversed(el.children))
        return out

    def write_diagram(self, dia_id: str, rel: str) -> None:
        ix = self.ix
        d = ix.diagrams[dia_id]
        el = ix.elements[dia_id]
        qn = ix.qualified_name(dia_id)
        fields: list[tuple[str, sx.Line]] = [("Diagram type", sx.line(d.diagram_type or "unknown"))]
        if d.uml_type and d.uml_type != d.diagram_type:
            fields.append(("UML diagram kind", sx.line(d.uml_type)))
        if d.owner:
            fields.append(("Owner / context", sx.line(self.ref(d.owner))))
        fields.append(("Qualified name", sx.line(sx.Span(qn, "code"))))
        for app in ix.applications(dia_id, sem.DIAGRAM_INFO):  # author and dates
            for k, vals in app.tags.items():
                fields.append((k.replace("_", " "), sx.line(", ".join(vals))))
        blocks = []
        doc = sem.documentation(ix, el)
        if doc:
            blocks.append(sx.Block("Documentation", [sx.line(tidy(doc))]))
        layout = self.layouts.get(dia_id)
        graph = self.graph(dia_id)
        part = self.partition(dia_id)
        if graph is not None:
            where = (lambda n: f" (M{part.module_of[n.num]})") if part else None
            nodes, edges = dg.describe(ix, graph, self.refs(rel), where=where)
            if part:
                blocks.append(sx.Block("Modules", [sx.line(
                    "the diagram is large, so its shapes are grouped into modules of connected shapes drawn close "
                    "together, each drawn and described on its own below. The legend gives each shape's module.")],
                    label=f"**Modules ({len(part.modules)}):**", form="inline"))
            shapes = f"Shapes ({len(nodes)}), numbered as in the sketch and indented by nesting"
            blocks.append(sx.Block(shapes, [sx.markdown_line(n) for n in nodes], form="list"))
            blocks.append(sx.Block("Connections", [sx.markdown_line(e) for e in edges], form="list",
                                   label=f"**Connections ({len(edges)}):**"))
        tbl = [sx.line(t) for t in self.table_config(el)]
        if any(w in (d.diagram_type or "") for w in ("Table", "Matrix")):
            blocks.append(sx.Block("Table / matrix configuration", tbl, form="list", label=(
                "**Table / matrix configuration** (rows are computed by Cameo and not stored in the file):")))
        else:
            blocks.append(sx.Block("Stereotypes and tagged values", tbl, form="list"))
        if d.shown and layout is None:
            blocks.append(sx.Block("Elements shown", [sx.line(
                f"- {ix.elements[e].kind} {' '.join(f'«{s}»' for s in ix.stereotype_names(e)) + ' ' if ix.stereotype_names(e) else ''}",
                self.ref(e)) for e in d.shown], form="list", label=f"**Elements shown ({len(d.shown)}):**"))
        view = sx.Section(sx.line("Diagram: ", sx.name(d.name or dia_id)), fields, blocks)
        lines = view.markdown(1, self.linker(rel))
        tr = self.trace(el)
        trace_line = [f"<sub>trace: `{tr.locator()}`</sub>", ""]
        self.section_chunks("diagram", el, view, rel, tr,
                            heading=self.heading(el, self.diagram_kind(dia_id)),
                            extra={"title": f"Diagram {qn}", "diagram_type": d.diagram_type})
        self.generated_chunks(el, rel, self.diagram_kind(dia_id))
        for a in self.ann.get(dia_id, []):
            if a.module is None:
                lines += self.annotation_md(a, rel)
        if part is not None and graph is not None:
            lines += self.module_sections(el, graph, part, rel)
        text = "\n".join(lines + trace_line)
        fm = front_matter({
            "title": f"Diagram {d.name}",
            "kind": "diagram",
            "element_id": dia_id,
            "diagram_type": d.diagram_type,
            "qualified_name": qn,
            "provenance": self.file_provenance(trace=tr.to_dict(), layout_streams=d.streams),
        })
        self.write_text(rel, fm + text)

    def diagram_kind(self, dia_id: str) -> str:
        return f"Diagram ({self.ix.diagrams[dia_id].diagram_type or 'unknown type'})"

    def module_sections(self, el: Element, g: dg.DiagramGraph, part: mod.Partition, rel: str) -> list[str]:
        """A section per module of a large diagram: its sketch, description, legend and
        connections; and its description as a chunk that says where in the diagram it is."""
        ix = self.ix
        what = f"{el.kind} {ix.qualified_name(el.id)}"
        kind_word = self.diagram_kind(el.id)
        lines = []
        for m in part.modules:
            anchor = f"module-m{m.num}"
            title = f"Module M{m.num} of {len(part.modules)}"
            lines += [f'<a id="{anchor}"></a>', "", f"## {title}", ""]
            anns = [a for a in self.ann.get(el.id, []) if a.module == m.num]
            for a in anns:
                lines += self.annotation_md(a, rel)
            legend, inside, edge = mod.module_lists(ix, g, part, m.num, self.refs(rel))
            lines += [f"**Shapes ({len(legend)}):**"] + legend + [""]
            if inside:
                lines += [f"**Connections within the module ({len(inside)}):**"] + inside + [""]
            if edge:
                lines += [f"**Connections with other modules ({len(edge)}):**"] + edge + [""]
            shapes = [n for n in g.nodes if part.module_of[n.num] == m.num]
            where = {
                "number": m.num, "of": len(part.modules), "anchor": f"{rel}#{anchor}",
                "shapes": m.shapes, "elements": list(dict.fromkeys(
                    n.view.element for n in shapes if n.view.element and n.view.element in ix.elements)),
                "box": [round(v, 1) for v in m.box],
                "image": next((a.image for a in anns if a.image), None),
            }
            for a in anns:
                if a.trace.derivation.method != "llm" or not a.text:
                    continue
                heading = self.generated_heading(a, el, kind_word, title.lower(), [n.label for n in shapes],
                                                 "showing")
                self.chunk(kind="generated:module_description", title=f"{title}: {what}",
                           text=f"{heading}\n\n{a.text}", file=rel, el=el, trace=a.trace, salt=f"M{m.num}",
                           extra={"covers": where})
                lines += [f"<sub>trace: `{a.trace.locator()}`</sub>", ""]
        return lines

    def table_config(self, el: Element) -> list[str]:
        """Stereotypes on a diagram other than DiagramInfo; for tables and matrices, these
        hold the configuration (scope, row types, columns)."""
        out = []
        for app in self.ix.applications(el.id):
            if app.name == sem.DIAGRAM_INFO:
                continue
            for k, vals in app.tags.items():
                shown = [self.ix.qualified_name(v) or v if v in self.ix.elements else shown_value(v) for v in vals]
                if len(shown) > 12:
                    shown = shown[:12] + [f"... ({len(vals) - 12} more)"]
                out.append(f"- «{app.name}» {k}: {'; '.join(shown)}")
        return out

    def write_readme(self) -> None:
        ix = self.ix
        counts: dict[str, int] = defaultdict(int)
        for el in ix.elements.values():
            counts[el.kind] += 1
        st_counts: dict[str, int] = defaultdict(int)
        for a in ix.stereotypes.values():
            st_counts[a.name] += 1
        lines = [f"# Cameo project: {md_inline(self.content.name)}", ""]
        exp = ", ".join(f"{k}: {v}" for k, v in ix.exporter.items())
        lines += [(f"- **Content:** `{self.content.token}` (where this content was found is recorded under "
                   "this token, in `INDEX.md` and `provenance.jsonl` at the root of the output tree)"),
                  f"- **Exporter:** {exp or 'unknown'}",
                  (f"- **Elements:** {len(ix.elements)}; **diagrams:** {len(ix.diagrams)}; "
                   f"**relationships:** {len(self.rels)}; **stereotype applications:** {len(ix.stereotypes)}"),
                  ""]
        lines.append("## Top-level packages\n")
        for r in ix.roots:
            el = ix.elements[r]
            for c in [el] + sem.children(ix, el):
                if c.kind in sem.PACKAGE_KINDS:
                    lines.append(f"- {self.link(c.id, 'README.md')}")
        lines.append("")
        if ix.diagrams:
            lines.append("## Diagrams\n")
            for d in sorted(ix.diagrams.values(), key=lambda d: ix.qualified_name(d.id)):
                lines.append(f"- {self.link(d.id, 'README.md')} — {d.diagram_type or ''}")
            lines.append("")
        lines.append("## Element kinds\n")
        lines += [f"- {k}: {n}" for k, n in sorted(counts.items(), key=lambda x: -x[1])]
        lines.append("")
        if st_counts:
            lines.append("## Stereotypes applied\n")
            lines += [f"- «{k}»: {n}" for k, n in sorted(st_counts.items(), key=lambda x: -x[1])]
            lines.append("")
        if ix.external_refs:
            mods = sorted({h.split("#", 1)[0] for h in ix.external_refs})
            lines.append("## Referenced external modules / profiles\n")
            lines += [f"- `{m}`" for m in mods]
            lines.append("")
        text = "\n".join(lines)
        tr = self.trace()
        # The chunk names the project by its label: file names can be long, and can repeat.
        chunk_text = text.replace(lines[0], f"# Cameo project: {md_inline(self.content.label)}", 1)
        self.text_chunks(kind="project", title=f"Cameo project {self.content.name}", text=chunk_text,
                         file="README.md", el=None, trace=tr)
        fm = front_matter({"title": f"Cameo project {self.content.name}", "kind": "project",
                           "provenance": self.file_provenance(trace=tr.to_dict())})
        self.write_text("README.md", fm + text)

    # -- tables & indices ------------------------------------------------------
    def write_csv(self, rel: str, header: list[str], rows: list[list[Any]]) -> None:
        p = self.root / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        with p.open("w", newline="", encoding="utf-8") as f:
            w = csv.writer(f)
            w.writerow(header)
            w.writerows(rows)

    def write_tables(self) -> None:
        ix = self.ix
        rows = []
        for el in ix.elements.values():
            rows.append([el.id, el.type, el.name or "", ix.qualified_name(el.id), el.owner or "",
                         ";".join(ix.stereotype_names(el.id)), sem.documentation(ix, el),
                         self.file_of.get(el.id, ""), self.trace(el).locator()])
        self.write_csv("tables/elements.csv", ["id", "type", "name", "qualified_name", "owner_id",
                                                "stereotypes", "documentation", "file", "trace"], rows)
        rows = []
        for r in self.rels:
            el = ix.elements[r.id]
            rows.append([r.id, r.kind, r.metaclass, r.name or "", r.source, ix.qualified_name(r.source) or r.source,
                         r.target, ix.qualified_name(r.target) or r.target, self.trace(el).locator()])
        self.write_csv("tables/relationships.csv", ["id", "kind", "metaclass", "name", "source_id", "source",
                                                     "target_id", "target", "trace"], rows)
        rows = []
        for el in ix.elements.values():
            if not sem.is_requirement(ix, el):
                continue
            f = sem.requirement_fields(ix, el)
            rel_by_kind: dict[str, list[str]] = defaultdict(list)
            for r in self.rels_by_end.get(el.id, []):
                other = r.source if r.target == el.id else r.target
                direction = "in" if r.target == el.id else "out"
                rel_by_kind[f"{r.kind}_{direction}"].append(ix.qualified_name(other) or other)
            rows.append([el.id, f.get("Id", ""), el.name or "", f.get("Text", ""), ix.qualified_name(el.id),
                         ";".join(ix.stereotype_names(el.id)),
                         json.dumps(rel_by_kind, ensure_ascii=False) if rel_by_kind else "",
                         self.file_of.get(el.id, ""), self.trace(el).locator()])
        self.write_csv("tables/requirements.csv", ["id", "req_id", "name", "text", "qualified_name",
                                                    "stereotypes", "relationships", "file", "trace"], rows)
        rows = []
        for el in ix.elements.values():
            if el.role not in ("ownedAttribute", "ownedPort", "ownedEnd"):
                continue
            t = sem.refs(el, "type")
            rows.append([el.id, el.owner or "", ix.qualified_name(el.owner) if el.owner else "", el.name or "",
                         el.kind, ";".join(ix.stereotype_names(el.id)),
                         ix.qualified_name(t[0]) if t and t[0] in ix.elements else (t[0] if t else ""),
                         sem.multiplicity(ix, el) or "", el.attrs.get("aggregation", ""),
                         sem.value_text(ix, next(iter(sem.children(ix, el, "defaultValue")), None)) or "",
                         self.trace(el).locator()])
        self.write_csv("tables/properties.csv", ["id", "owner_id", "owner", "name", "kind", "stereotypes", "type",
                                                  "multiplicity", "aggregation", "default", "trace"], rows)
        rows = []
        for app in ix.stereotypes.values():
            base = ix.elements.get(app.base)
            tr = self.trace(base).with_(line=app.line) if base else self.trace().with_(xmi_id=app.id, line=app.line,
                                                                                         entry=app.entry)
            for k, vals in app.tags.items():
                for v in vals:
                    rows.append([app.base, ix.qualified_name(app.base) if base else "", app.stereotype, k,
                                 ix.qualified_name(v) if v in ix.elements else v, tr.locator()])
        self.write_csv("tables/tagged_values.csv", ["element_id", "element", "stereotype", "tag", "value", "trace"],
                       rows)
        rows = []
        for d in ix.diagrams.values():
            rows.append([d.id, d.name, d.diagram_type or "", d.uml_type or "",
                         ix.qualified_name(d.owner) if d.owner else "", len(d.shown), self.dia_file.get(d.id, ""),
                         self.trace(ix.elements[d.id]).locator()])
        self.write_csv("tables/diagrams.csv", ["id", "name", "diagram_type", "uml_type", "owner", "elements_shown",
                                                "file", "trace"], rows)

    def write_indices(self) -> None:
        ix = self.ix
        p = self.root / "index/elements.jsonl"
        p.parent.mkdir(parents=True, exist_ok=True)
        with p.open("w", encoding="utf-8") as f:
            for el in ix.elements.values():
                rec = {
                    "id": el.id, "type": el.type, "role": el.role, "name": el.name, "owner": el.owner,
                    "qualified_name": ix.qualified_name(el.id), "attrs": el.attrs,
                    "refs": [[r, t] for r, t in el.refs], "children": el.children,
                    "stereotypes": [{"name": a.stereotype, "tags": a.tags} for a in ix.applications(el.id)],
                    "file": self.file_of.get(el.id), "provenance": self.trace(el).to_dict(),
                }
                f.write(json.dumps(rec, ensure_ascii=False) + "\n")

        def tree(eid: str, seen: set[str]) -> dict[str, Any] | None:
            el = ix.elements.get(eid)
            if el is None or eid in seen:
                return None
            seen.add(eid)
            kids = [t for c in el.children if (t := tree(c, seen))]
            if not (sem.is_section(ix, el) or kids):
                return None
            node: dict[str, Any] = {"id": eid, "name": el.name, "kind": el.kind}
            if st := ix.stereotype_names(eid):
                node["stereotypes"] = st
            if eid in self.file_of:
                node["file"] = self.file_of[eid]
            if kids:
                node["children"] = kids
            return node

        seen: set[str] = set()
        h = {"project": self.content.name, "provenance": self.file_provenance(),
             "roots": [t for r in ix.roots if (t := tree(r, seen))]}
        p = self.root / "index/hierarchy.json"
        p.write_text(json.dumps(h, ensure_ascii=False, indent=1), encoding="utf-8")
        p = self.root / "index/chunks.jsonl"
        with p.open("w", encoding="utf-8") as f:
            for c in self.chunks:
                f.write(json.dumps(c, ensure_ascii=False) + "\n")


def _relpath(dest: str, from_file: str) -> str:
    """Relative link from one project-relative file to another (keeps #anchors)."""
    path, _, frag = dest.partition("#")
    from_parts = from_file.split("/")[:-1]
    to_parts = path.split("/")
    i = 0
    while i < len(from_parts) and i < len(to_parts) - 1 and from_parts[i] == to_parts[i]:
        i += 1
    rel = "/".join([".."] * (len(from_parts) - i) + to_parts[i:])
    return f"{rel}#{frag}" if frag else rel
