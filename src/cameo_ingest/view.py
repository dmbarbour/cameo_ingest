"""A project as pages and chunks see it: its model's semantic indexes and caches (relationships by end,
notes, diagrams showing each element, diagram graphs and partitions), traces, headings and each
element's section as data (plan RA-13, AR-007R1)."""

from __future__ import annotations

from collections import defaultdict
from typing import Any

from . import cameo_tables as ct
from . import diagram_graph as dg
from . import partition as pt
from . import plain as pl
from . import sections as sx
from . import semantics as sem
from .annotations import Annotation
from .archive import Project
from .config import MODULES
from .files import relpath
from .layout import Layout
from .model import Element, ModelIndex
from .provenance import TOOL, ContentInfo, Trace, generated_by
from .text import one_line, shown_value, tidy

SKIP_MEMBER_ROLES = {
    "ownedComment", "lowerValue", "upperValue", "defaultValue", "specification",
    "generalization", "interfaceRealization", "ownedDiagram",
}


class ProjectView:
    def __init__(self, content: ContentInfo, project: Project, ix: ModelIndex,
                 annotations: dict[str, list[Annotation]] | None = None,
                 layouts: dict[str, Layout] | None = None, modules: tuple[int, int, int] = MODULES):
        self.layouts = layouts or {}
        self.modules = modules  # large diagrams: split above N shapes, into MIN to MAX
        self.content = content
        self.project = project
        self.ix = ix
        self.ann = annotations if annotations is not None else {}
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
        self._parts: dict[str, pt.Partition | None] = {}
        self._tables: dict[str, ct.Table | None] = {}
        self._columns: ct.Columns | None = None
        self.package_parts: dict[str, list[list[str]]] = {}  # large packages, summarized in parts (element ids)
        self.diagrams_showing: dict[str, list[str]] = defaultdict(list)
        for d in ix.diagrams.values():
            for e in d.shown:
                self.diagrams_showing[e].append(d.id)

    def table(self, dia_id: str) -> ct.Table | None:
        """The table a diagram shows, computed as Cameo shows it (plan CT); None for a diagram
        that isn't a table, or a table that lists no columns or rows (built once)."""
        if dia_id not in self._tables:
            d = self.ix.diagrams.get(dia_id)
            if d is None or not ct.is_table(d.diagram_type) or dia_id in self.layouts:
                self._tables[dia_id] = None
            else:
                self._columns = self._columns or ct.Columns(self.ix, self.rels)
                self._tables[dia_id] = ct.build(self.ix, self._columns, dia_id)
        return self._tables[dia_id]

    def inside_shapes(self, dia_id: str) -> tuple[list[tuple[dg.Node | dg.Link, list[Element]]], int]:
        """What a drawn diagram shows inside its shapes (plan IS): the elements it uses
        (`usedObjects`) but doesn't draw, each under the shape or line drawn for its owner (or its
        owner's owner, up to three levels): a block's properties and operations, a transition's
        trigger, a state's regions. The holders in legend order, and how many used elements have
        no owner drawn, which are only counted."""
        g, d = self.graph(dia_id), self.ix.diagrams.get(dia_id)
        layout = self.layouts.get(dia_id)
        if g is None or d is None or layout is None:
            return [], 0
        holders: dict[str, dg.Node | dg.Link] = {}
        for n in g.nodes:
            if n.view.element:
                holders.setdefault(n.view.element, n)
        for lk in g.links:
            if lk.view.element:
                holders.setdefault(lk.view.element, lk)
        drawn = set(layout.elements())
        held: dict[int, list[Element]] = defaultdict(list)
        unchecked = 0
        for e in d.used:
            if e in drawn:
                continue
            owner, holder = self.ix.elements[e].owner, None
            for _ in range(3):
                if not owner or owner in holders:
                    holder = holders.get(owner or "")
                    break
                owner = self.ix.elements[owner].owner if owner in self.ix.elements else None
            if holder is None:
                unchecked += 1
            else:
                held[id(holder)].append(self.ix.elements[e])
        order = [*g.nodes, *g.links]
        return [(h, held[id(h)]) for h in order if id(h) in held], unchecked

    def graph(self, dia_id: str) -> dg.DiagramGraph | None:
        """The diagram's shapes and connections, numbered (built once)."""
        layout = self.layouts.get(dia_id)
        if layout is None:
            return None
        if dia_id not in self._graphs:
            self._graphs[dia_id] = dg.build(self.ix, layout, self.rel_by_id, self.flows)
        return self._graphs[dia_id]

    def partition(self, dia_id: str) -> pt.Partition | None:
        """A large diagram's modules (computed once); None for a diagram drawn whole."""
        if dia_id not in self._parts:
            g = self.graph(dia_id)
            self._parts[dia_id] = pt.partition(g, *self.modules) if g is not None else None
        return self._parts[dia_id]

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

    def sections_in(self, pkg: Element) -> list[Element]:
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

    def set_parts(self, pkg_id: str, parts: list[list[str]]) -> None:
        """A large package's parts (element ids), as summarized (plan DV-05)."""
        self.package_parts[pkg_id] = parts

    def heading(self, el: Element, kind_word: str | None = None) -> str:
        """The plain style's heading: what the element is, its readable name, where it is."""
        ix = self.ix
        name, kind_word = sem.label(ix, el.id), kind_word or sem.kind_word(ix, el)
        owner = ix.qualified_name(el.owner) if el.owner else ""  # not the element's: an unnamed one's ends with its owner
        # A long name is cut first, so that the heading keeps where the element is (AR-004R2).
        return f"{kind_word} {pl.cap(one_line(name), pl.HEADING // 2, keep='')} {pl.where(owner, self.content.label)}"

    def diagram_kind(self, dia_id: str) -> str:
        return f"Diagram ({self.ix.diagrams[dia_id].diagram_type or 'unknown type'})"

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

    def annotation_block(self, a: Annotation, from_file: str) -> sx.Block:
        before = [f"![{a.label}]({relpath(a.image, from_file)})", ""] if a.image else []
        return sx.Block(a.label, [sx.line(tidy(a.text))] if a.text else [], before=before,
                        label=f"**{a.label}** _({generated_by(a.trace.derivation)})_:")

    def tagged_values(self, el: Element) -> list[tuple[str, str, str]]:
        out = []
        for app in self.ix.applications(el.id):
            for k, vals in app.tags.items():
                if k in ("Id", "Text") and sem.is_requirement(self.ix, el):
                    continue
                shown = ", ".join(sem.label(self.ix, v) if self.ix.refers(v) else v.strip() for v in vals if v.strip())
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

    def table_config(self, el: Element) -> list[str]:
        """Stereotypes on a diagram other than DiagramInfo; for tables and matrices, these
        hold the configuration (scope, row types, columns)."""
        out = []
        for app in self.ix.applications(el.id):
            if app.name == sem.DIAGRAM_INFO:
                continue
            for k, vals in app.tags.items():
                shown = [(self.ix.qualified_name(v) or v) if v in self.ix.elements
                         else self.ix.label(v) if v in self.ix.external_refs else shown_value(v) for v in vals]
                if len(shown) > 12:
                    shown = shown[:12] + [f"... ({len(vals) - 12} more)"]
                out.append(f"- «{app.name}» {k}: {'; '.join(shown)}")
        return out
