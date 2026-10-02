"""A diagram's layout as a graph: numbered nodes (the shapes) and links (the connections).

A link's direction comes from the model relationship it shows (FU-001), and a connector carries
the item flows that it realizes (FU-002). Shapes keep their numbers in every view made from the
graph: the text (`diagram_text`), the sketch (`sketch`) and a large diagram's modules
(`partition`).
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field

from . import semantics as sem
from .layout import Layout, View
from .model import ModelIndex
from .semantics import ItemFlow, Relationship
from .text import one_line

# Views that only decorate another view (labels, connector ends, roles): never shapes (FU-007).
DECORATION = {"TextBox", "TextBoxWithIcon", "ConnectorEnd", "Role", "NoteAnchor", "DiagramShape", "FlowConnector"}
# Drawn on the border of the shape that owns them, and named as "Owner.pin" in text.
ATTACHED = {"Pin", "Port", "ParameterNode", "ObjectNode"}
DIRECTED = {
    "ControlFlow", "ObjectFlow", "Dependency", "Abstraction", "Realization", "Usage", "Include",
    "Extend", "Generalization", "InformationFlow", "Transition", "FlowConnector", "Message",
    "InterfaceRealization", "Containment",
}


@dataclass(frozen=True)
class ShapeLabel:
    """How a shape's element reads, computed once per shape (AR-010R2)."""

    stereotype: str  # its first shown stereotype, or ""
    name: str  # its own name (semantics.own_name), or "" when nothing names it
    type: str  # the label of its type, or ""
    kind: str  # its metaclass, for an element nothing else names

    def full(self) -> str:
        """The legend's text: '«stereotype» name : Type'; an unnamed typed element by its type
        alone (FU-003)."""
        name = f"{self.name} : {self.type}" if self.name and self.type else self.name or self.type
        return ((f"«{self.stereotype}» " if self.stereotype else "") + name).strip() or f"(unnamed {self.kind})"

    def shown(self) -> str:
        """The name drawn in the shape: its own, or its type, as in the legend (FU-018)."""
        return self.name or self.type


def shape_label(ix: ModelIndex, v: View) -> ShapeLabel:
    el = ix.elements.get(v.element or "")
    if el is None:  # a reference into a used project, or a shape with text only
        ref = v.element.rsplit("#", 1)[-1] if v.element and "#" in v.element else v.element
        return ShapeLabel("", ref or v.text or "", "", v.cls)
    t = next((tgt for r, tgt in el.refs if r == "type"), None)
    st = sem.shown_stereotypes(ix, el.id)
    return ShapeLabel(st[0] if st else "", sem.own_name(ix, el), sem.label(ix, t) if t else "", el.kind)


@dataclass
class Node:
    num: int  # stable within the diagram: the legend key and the tag drawn on the shape
    view: View
    label: str  # full label, plain text
    depth: int  # nesting among shapes
    parent: int | None = None  # number of the shape this one is nested in
    shown: str = ""  # the name drawn in the shape


@dataclass
class Link:
    view: View
    source: View | None  # the ends, source first for directed kinds
    target: View | None
    directed: bool
    label: str  # «stereotype» name
    verb: str  # how a dependency reads from source to target ("is derived from"); "" for flows
    items: list[str]  # conveyed items, "Energy →" read from source to target
    target_at_first_point: bool  # where to draw the arrowhead
    more: list[View] = field(default_factory=list)  # further segments of a flow broken by connector circles


@dataclass
class DiagramGraph:
    nodes: list[Node] = field(default_factory=list)
    links: list[Link] = field(default_factory=list)
    node_of: dict[str, Node] = field(default_factory=dict)  # view id of a shape, or of a pin on it
    pins: dict[str, str] = field(default_factory=dict)  # view id of a pin or port -> its label
    pin_views: list[View] = field(default_factory=list)
    # Connector circles where a flow's segments break off (FU-017), each with the label drawn
    # beside it: the shape the flow continues to ("to 12") or comes from ("from 12").
    connectors: list[tuple[View, str]] = field(default_factory=list)

    def trivial(self) -> bool:
        """Too little to describe: fewer than 3 shapes, unless 2 shapes are connected (FU-010)."""
        return len(self.nodes) < 3 and not (len(self.nodes) == 2 and self.links)


def build(ix: ModelIndex, layout: Layout, rels: dict[str, Relationship],
          flows: dict[str, list[ItemFlow]]) -> DiagramGraph:
    g = DiagramGraph()
    by_id = layout.by_view_id()
    for v in layout.views:  # parents come before the views nested in them
        if v.is_path or v.cls in DECORATION or v.cls == "DiagramFrame" or not (v.element or v.text):
            continue
        owner = g.node_of.get(v.parent or "")
        if v.cls in ATTACHED and owner is not None and owner.view.view_id == v.parent:
            g.node_of[v.view_id or ""] = owner
            g.pins[v.view_id or ""] = one_line(shape_label(ix, v).full())
            g.pin_views.append(v)
            continue
        parent = by_id.get(v.parent or "")
        while parent is not None and (parent.view_id or "") not in g.node_of:
            parent = by_id.get(parent.parent or "")
        up = g.node_of[parent.view_id or ""] if parent is not None else None
        lb = shape_label(ix, v)
        node = Node(len(g.nodes) + 1, v, one_line(lb.full() if v.element else f'"{v.text}"'),
                    up.depth + 1 if up else 0, up.num if up else None, one_line(lb.shown()))
        g.nodes.append(node)
        g.node_of[v.view_id or ""] = node

    def ends(view: View | None) -> set[str]:
        """Element ids a flow's source or target may name for this end: the pin or shape,
        the shape a pin belongs to, and their types (item flows usually name the blocks
        that type the parts at a connector's ends)."""
        if view is None:
            return set()
        node = g.node_of.get(view.view_id or "")
        ids = {e for e in (view.element, node.view.element if node else None) if e}
        return ids | {t for e in ids if e in ix.elements for r, t in ix.elements[e].refs if r == "type"}

    def connector(view_id: str | None) -> bool:
        v = by_id.get(view_id or "")
        return v is not None and v.cls == "FlowConnector"

    # A long flow may be drawn as two segments, each ending at one of a pair of connector
    # circles rather than at the far shape; the segments share the flow's element (FU-017).
    halves: dict[str, list[View]] = defaultdict(list)
    for v in layout.views:
        if v.is_path and v.element and (connector(v.first) or connector(v.second)):
            halves[v.element].append(v)
    joined: set[str] = set()

    def shape_end(seg: View) -> tuple[View | None, bool]:
        """A segment's end at a shape, and whether that is its first end."""
        return (by_id.get(seg.second or ""), False) if connector(seg.first) else (by_id.get(seg.first or ""), True)

    for v in layout.views:
        if not v.is_path or not (v.first or v.second):
            continue
        rel = rels.get(v.element or "")
        directed = v.cls in DIRECTED or (rel is not None and rel.metaclass in DIRECTED)
        more: list[View] = []
        pair = halves.get(v.element or "", [])
        if len(pair) == 2:
            if v.element in joined:
                continue
            joined.add(v.element or "")
            (a, a_first), (b, b_first) = shape_end(pair[0]), shape_end(pair[1])
            # Cameo stores a directed path's target as its first end (FU-001); the model's
            # relationship, when there is one, decides.
            to_target = pair[0] if a_first and not b_first else pair[1]
            if rel is not None and rel.target in ends(a) and rel.source in ends(b):
                to_target = pair[0]
            elif rel is not None and rel.target in ends(b) and rel.source in ends(a):
                to_target = pair[1]
            from_source = pair[1] if to_target is pair[0] else pair[0]
            (target, at_first), (source, _) = shape_end(to_target), shape_end(from_source)
            v, more = to_target, [from_source]
            for seg, far, arrow in ((from_source, target, "to {}"), (to_target, source, "from {}")):
                circle = by_id.get((seg.first if connector(seg.first) else seg.second) or "")
                node = g.node_of.get(far.view_id or "") if far is not None else None
                if circle is not None:
                    g.connectors.append((circle, arrow.format(node.num) if node else ""))
        else:
            first, second = by_id.get(v.first or ""), by_id.get(v.second or "")
            source, target, at_first = first, second, False
            if directed and not (rel is not None and (first and first.element, second and second.element)
                                 == (rel.source, rel.target)):
                # Cameo stores a directed path's target as its first end (FU-001).
                source, target, at_first = second, first, True
        el = ix.elements.get(v.element or "")
        stereotypes = sem.shown_stereotypes(ix, el.id) if el else []
        flow = sem.flow_label(ix, el) if el is not None and el.kind in ("Transition", "ControlFlow", "ObjectFlow") else ""
        label = " ".join([f"«{s}»" for s in stereotypes] + ([el.name] if el and el.name else [])
                         + ([flow] if flow and flow != (el.name if el else None) else []))
        w = sem.wording(*stereotypes, rel.metaclass if rel else "", v.cls) if directed else None
        verb = w.forward if w else ""
        items = []
        for f in flows.get(v.element or "", []):
            names = ", ".join(sem.label(ix, i) for i in f.items) or sem.label(ix, f.id)
            if f.source in ends(source) or f.target in ends(target):
                names += " →"
            elif f.source in ends(target) or f.target in ends(source):
                names += " ←"
            items.append(names)
        if not directed and items and all(i.endswith(" ←") for i in items):
            # A connector has no direction of its own: list it the way its items flow.
            source, target, at_first = target, source, not at_first
            items = [i[:-1] + "→" for i in items]
        g.links.append(Link(v, source, target, directed, label, verb, items, at_first, more))
    return g
