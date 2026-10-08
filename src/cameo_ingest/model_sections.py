"""Sections built from the model (review CQ-016): an element's and a diagram's, as data
(`sections.Section`) that pages render as Markdown and chunks as plain text. `ProjectView` holds
the model's indexes; this reads them.
"""

from __future__ import annotations

import re
from typing import TYPE_CHECKING

from . import cameo_tables as ct
from . import diagram_graph as dg
from . import diagram_text as dt
from . import sections as sx
from . import semantics as sem
from .annotations import Annotation
from .diagram_text import Refs
from .files import relpath
from .model import Element
from .provenance import generated_by
from .text import one_line, shown_value, tidy

if TYPE_CHECKING:
    from .view import ProjectView

SKIP_MEMBER_ROLES = {
    "ownedComment", "lowerValue", "upperValue", "defaultValue", "specification",
    "generalization", "interfaceRealization", "ownedDiagram",
}


class Sections:
    """A project's sections, from its view."""

    def __init__(self, view: ProjectView):
        self.view = view
        self.ix = view.ix

    def element(self, el: Element, generated: bool = True, from_file: str = "") -> sx.Section:
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
        gens = [r for r in self.view.rels_by_end.get(el.id, []) if r.metaclass == "Generalization" and r.source == el.id]
        if gens:
            fields.append(("Specializes", self.refs_line([g.target for g in gens])))
        blocks: list[sx.Block] = []
        req = sem.requirement_fields(ix, el) if rq is not None else {}
        if "Text" in req:
            blocks.append(sx.Block("Requirement text", [sx.line(tidy(req["Text"]))], quoted=True))
        doc = sem.documentation(ix, el)
        if doc:
            blocks.append(sx.Block("Documentation", [sx.line(tidy(doc))]))
        notes = [c.attrs["body"].strip() for c in self.view.notes.get(el.id, [])]  # a diagram's notes about it
        blocks.append(sx.Block("Notes", [sx.line(f"- {tidy(one_line(n))}") for n in notes if n]))
        spec = next(iter(sem.children(ix, el, "specification")), None)
        if spec is not None and sem.value_text(ix, spec):
            lang = spec.attrs.get("language", "")
            blocks.append(sx.Block(f"Specification{f' ({lang})' if lang else ''}",
                                   [sx.line(sem.value_text(ix, spec) or "")], fenced=True))
        blocks.append(sx.Block("Tagged values", [sx.line(f"- «{s}» {k} = " + v.replace("\n", "\n  "))
                                                 for s, k, v in self.tagged_values(el)], form="list", detail=True))
        blocks.append(sx.Block("Members", self.members(el, depth=0), form="list", detail=True))
        rels = [r for r in self.view.rels_by_end.get(el.id, []) if r.metaclass != "Generalization" or r.target == el.id]
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
        blocks.append(sx.Block("Shown in diagrams", [sx.line(self.ref(d)) for d in self.view.diagrams_showing.get(el.id, [])],
                               form="inline"))
        for a in self.view.ann.get(el.id, []):
            if (generated or a.trace.derivation.method != "llm") and a.module is None and a.parts is None:
                blocks.append(self.annotation(a, from_file))
        return sx.Section(title, fields, blocks)

    def diagram(self, dia_id: str, refs: Refs) -> sx.Section:
        """A diagram's section as data: its fields, its documentation, its shapes and connections
        (`refs` link them from its page), what its shapes hold, and a table's rows or configuration."""
        ix = self.view.ix
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
        layout = self.view.layouts.get(dia_id)
        graph = self.view.graph(dia_id)
        part = self.view.partition(dia_id)
        if graph is not None:
            where = (lambda n: f" (M{part.module_of[n.num]})") if part else None
            nodes, edges = dt.describe(ix, graph, refs, where=where)
            if part:
                blocks.append(sx.Block("Modules", [sx.line(
                    "the diagram is large, so its shapes are grouped into modules of connected shapes drawn close "
                    "together, each drawn and described on its own below. The legend gives each shape's module.")],
                    label=f"**Modules ({len(part.modules)}):**", form="inline"))
            shapes = f"Shapes ({len(nodes)}), numbered as in the sketch and indented by nesting"
            blocks.append(sx.Block(shapes, [sx.markdown_line(n) for n in nodes], form="list"))
            blocks.append(sx.Block("Connections", [sx.markdown_line(e) for e in edges], form="list",
                                   label=f"**Connections ({len(edges)}):**"))
            inside = self.inside_block(dia_id, graph)
            if inside is not None:
                blocks.append(inside)
        tbl = [sx.line(t) for t in self.table_config(el)]
        table = ct.computed_kind(d.diagram_type)  # a table, a matrix or a map
        computed = self.view.table(dia_id)
        if computed is not None:  # a table, computed as Cameo shows it (plan CT)
            blocks += self.table_blocks(computed)
        elif table:
            missing = ct.not_computed(ix, dia_id) if layout is None else None
            relates = ct.describe_matrix(ix, dia_id)  # a matrix: what it relates, in words (ADR-0025)
            if missing is not None:  # what isn't shown, and why: said, not guessed at (plan CT)
                follows = " What it relates follows." if relates else " Its configuration follows."
                blocks.append(sx.Block("Not computed", [sx.line(missing[1] + follows)]))
            if relates:
                blocks.append(sx.Block("Matrix", [sx.line(relates)]))
            else:
                blocks.append(sx.Block("Table / matrix configuration", tbl, form="list", label=(
                    "**Table / matrix configuration** (Cameo computes the rows and cells from it when it shows the "
                    "table):")))
        else:
            blocks.append(sx.Block("Stereotypes and tagged values", tbl, form="list"))
        if d.shown and layout is None and computed is None:
            shown = f"Elements shown when last saved ({len(d.shown)})" if table else f"Elements shown ({len(d.shown)})"
            blocks.append(sx.Block("Elements shown", [sx.line(
                f"- {ix.elements[e].kind} {' '.join(f'«{s}»' for s in ix.stereotype_names(e)) + ' ' if ix.stereotype_names(e) else ''}",
                self.ref(e)) for e in d.shown], form="list", label=f"**{shown}:**"))
        return sx.Section(sx.line("Diagram: ", sx.name(d.name or dia_id)), fields, blocks)

    def inside_block(self, dia_id: str, graph: dg.DiagramGraph) -> sx.Block | None:
        """What the diagram shows inside its shapes (plan IS): under each shape's (or line's) legend
        number, what it holds, by kind; then how many more Cameo lists as used without an owner
        drawn here, counted, not shown."""
        ix = self.view.ix
        inside, unchecked = self.view.inside_shapes(dia_id)
        if not inside and not unchecked:
            return None

        def name(e: Element) -> str:
            if e.kind == "Trigger":
                return sem.trigger_text(ix, e) or sem.label(ix, e.id)
            return sem.label(ix, e.id) + ("()" if e.kind == "Operation" else "")

        lines = []
        for holder, els in inside:
            if isinstance(holder, dg.Node):
                head: list[sx.Span | str] = [f"[{holder.num}] ", sx.name(holder.label)]
            else:
                ends = [graph.node(v)
                        for v in (holder.source, holder.target)]
                head = [f"{holder.view.cls} " + " → ".join(f"[{n.num}]" if n else "?" for n in ends)]
            groups: dict[str, list[str]] = {}
            for e in els:
                groups.setdefault(kinds_word(e.kind), []).append(name(e))
            spans: list[sx.Span | str] = ["- ", *head, ": "]
            for k, (kind, names) in enumerate(groups.items()):
                spans += ["; " if k else "", f"{kind} ", sx.name(", ".join(dict.fromkeys(names)))]
            lines.append(sx.line(*spans))
        if unchecked:
            lines.append(sx.line(f"- and {unchecked} more that Cameo lists as used, whose owners aren't drawn here"))
        return sx.Block("Shown inside its shapes", lines, form="list", detail=True)

    def table_blocks(self, t: ct.Table) -> list[sx.Block]:
        """A computed table: what it shows, in a sentence or two, then its rows (plan CT)."""
        ix = self.view.ix
        about = [f"Columns: {', '.join(c.header for c in t.columns)}."]
        if t.sort:
            about.append(f"Sorted by {t.sort}.")
        if t.row_types:
            about.append(f"Row types: {', '.join(t.row_types)}.")
        if t.scope:
            about.append(f"Scope: {', '.join(ix.qualified_name(s) for s in t.scope)}.")
        about.append(f"Rows: {len(t.rows)}, as the table lists them.")
        if t.not_computed:
            about.append(f"Not computed here (Cameo computes them): {', '.join(t.not_computed)}.")

        def cell(values: list[ct.Value]) -> sx.Line:
            spans: list[sx.Span | str] = []
            for k, v in enumerate(values):
                spans += (["; "] if k else []) + [sx.ref(v.ref, v.text) if v.ref else sx.name(v.text)]
            return sx.line(*spans)

        return [sx.Block("Table", [sx.line(" ".join(about))]),
                sx.Block("Rows", [], label=f"**Rows ({len(t.rows)}):**", form="table", detail=True,
                         columns=[c.header for c in t.columns], rows=[[cell(c) for c in row] for row in t.cells])]

    def ref(self, id_: str) -> sx.Span:
        """A reference to an element: its label, linked on pages to its page."""
        return sx.ref(id_, sem.label(self.ix, id_))

    def refs_line(self, ids: list[str]) -> sx.Line:
        return sx.line(*[p for k, i in enumerate(ids) for p in ((", ",) if k else ()) + (self.ref(i),)])

    def names(self, labels: list[str]) -> list[str | sx.Span]:
        return [p for k, x in enumerate(labels) for p in ((", ",) if k else ()) + (sx.name(x),)]

    @staticmethod
    def annotation(a: Annotation, from_file: str) -> sx.Block:
        """A sketch or a generated description: its image, then its text, labelled with what made it."""
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
                r = self.view.rel_by_id.get(c.id)
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


def kinds_word(kind: str) -> str:
    """A metaclass as a plural, for a list of them: "Property" → "properties", "ConnectorEnd" →
    "connector ends"."""
    words = re.sub(r"(?<=[a-z])(?=[A-Z])", " ", kind).lower().split()
    last = words[-1]
    last = last[:-1] + "ies" if last.endswith("y") and last[-2:-1] not in "aeiou" else \
        last + "es" if last.endswith(("s", "x", "ch")) else last + "s"
    return " ".join([*words[:-1], last])
