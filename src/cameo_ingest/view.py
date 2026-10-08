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
from . import semantics as sem
from .annotations import Annotation
from .archive import Project
from .config import MODULES
from .layout import Layout
from .model import Element, ModelIndex
from .provenance import TOOL, ContentInfo, Trace
from .text import one_line


class ProjectView:
    """One project's indexes and caches, and what is found about it before it is written: the
    pipeline draws the sketches and the enricher asks the LLM, both adding to `ann` (and the
    enricher to `package_parts`, by `set_parts`); only then do the writers read them (CQ-017)."""

    def __init__(self, content: ContentInfo, project: Project, ix: ModelIndex,
                 layouts: dict[str, Layout] | None = None, modules: tuple[int, int, int] = MODULES):
        self.layouts = layouts or {}
        self.modules = modules  # large diagrams: split above N shapes, into MIN to MAX
        self.content = content
        self.project = project
        self.ix = ix
        self.ann: dict[str, list[Annotation]] = {}  # by element: sketches and the LLM's notes (CQ-017: the one owner)
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

