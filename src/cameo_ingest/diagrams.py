"""A diagram's layout as a graph, and the two views made from it: text and a sketch.

`build` turns a layout into numbered nodes (the shapes) and links (the connections). A
link's direction comes from the model relationship it shows (FU-001), and a connector
carries the item flows that it realizes (FU-002). `describe` writes the graph as text: a
legend of numbered shapes, and connections between those numbers. `render_png` draws a
sketch at the size the vision model sees (FU-012) in which shapes carry the same numbers,
so full labels live in the legend instead of being wrapped into boxes (FU-008). A `Frame`
narrows a sketch to one module of a large diagram, or colours the modules in an overview
(plan DV, `modules.py`).

The sketch is not a faithful Cameo rendering; the text is the authoritative description.
"""

from __future__ import annotations

import io
import itertools
import math
from collections import defaultdict
from dataclasses import dataclass, field

from PIL import Image, ImageDraw, ImageFont

from . import semantics as sem
from .layout import Layout, View
from .model import Element, ModelIndex
from .richtext import to_text
from .semantics import ItemFlow, Relationship
from .text import md_inline, one_line

# gemma-4 fills a budget of 280 soft tokens of 48 x 48 px (645,120 px) at the image's own aspect
# ratio, with sides in multiples of 48 (docs/research/gemma4-images-2026-09-30.md, FU-015).
IMAGE_PIXELS = 280 * 48 * 48
PATCH_PX = 48
MAX_ZOOM = 2.0  # small diagrams are not blown up further than this
FONT_PX = 12
MARGIN = 8
TITLE_PX = 18
# Views that only decorate another view (labels, connector ends, roles): never shapes (FU-007).
DECORATION = {"TextBox", "TextBoxWithIcon", "ConnectorEnd", "Role", "NoteAnchor", "DiagramShape", "FlowConnector"}
# Drawn on the border of the shape that owns them, and named as "Owner.pin" in text.
ATTACHED = {"Pin", "Port", "ParameterNode", "ObjectNode"}
DIRECTED = {
    "ControlFlow", "ObjectFlow", "Dependency", "Abstraction", "Realization", "Usage", "Include",
    "Extend", "Generalization", "InformationFlow", "Transition", "FlowConnector", "Message",
    "InterfaceRealization", "Containment",
}
DASHED = {"Dependency", "Abstraction", "Realization", "Usage", "Include", "Extend", "InterfaceRealization"}
HOLLOW = {"Generalization", "Realization", "InterfaceRealization"}
ROUND = {"UseCase", "InitialNode", "ActivityFinalNode", "FlowFinalNode", "PseudoNode"}
_NOT_SHOWN = "DiagramInfo"  # MagicDraw_Profile metadata on diagrams, not a stereotype to display (FU-003)
# How a dependency reads from source to target, by stereotype or kind (lower case). A stated
# rule about arrow direction was not enough for the model (FU-013); words in the line are.
VERBS = {
    "derivereqt": "is derived from", "satisfy": "satisfies", "verify": "verifies", "refine": "refines",
    "trace": "traces to", "allocate": "is allocated to", "copy": "is a copy of", "generalization": "is a kind of",
    "include": "includes", "extend": "extends", "realization": "realizes", "interfacerealization": "realizes",
    "usage": "uses", "dependency": "depends on", "abstraction": "depends on",
}


def _stereotypes(ix: ModelIndex, el_id: str) -> list[str]:
    return [s for s in ix.stereotype_names(el_id) if s != _NOT_SHOWN]


def _name(ix: ModelIndex, v: View) -> str:
    """The element's own name, or for unnamed actions the behavior they invoke."""
    el = ix.elements.get(v.element or "")
    if el is None:
        return (v.element.rsplit("#", 1)[-1] if v.element and "#" in v.element else v.element) or v.text or ""
    if el.name:
        return el.name
    for role in ("behavior", "operation", "signal", "event", "structuralFeature"):
        tgt = next((t for r, t in el.refs if r == role), None)
        if tgt:
            return ix.label(tgt)
    return _described(ix, el)


def _described(ix: ModelIndex, el: Element) -> str:
    """What an unnamed element otherwise says it is (FU-024): the part a swimlane or lifeline
    represents, an opaque action's body, a value action's value, a state invariant's
    constraint, a comment's text, a requirement's id or text. Empty when nothing does."""
    def short(text: str | None) -> str:
        text = one_line(text or "")
        return text if len(text) <= 80 else text[:79] + "…"

    represents = next((t for r, t in el.refs if r == "represents"), None)
    if represents:
        part = ix.elements.get(represents)
        typ = next((t for r, t in part.refs if r == "type"), None) if part is not None else None
        if part is not None and typ:
            return f"{part.name} : {ix.label(typ)}" if part.name else ix.label(typ)
        return ix.label(represents)
    if el.kind == "OpaqueAction":
        return short(el.attrs.get("body"))
    for trigger in sem.children(ix, el, "trigger"):  # an AcceptEventAction: the event, or its signal
        event = ix.elements.get(next((t for r, t in trigger.refs if r == "event"), ""))
        if event is not None:
            return event.name or ix.label(next((t for r, t in event.refs if r == "signal"), event.id))
    if el.kind == "Comment":
        return f'"{short(to_text(el.attrs.get("body")))}"' if el.attrs.get("body") else ""
    for role in ("value", "invariant"):  # a ValueSpecificationAction's value; a StateInvariant's constraint
        spec = next(iter(sem.children(ix, el, role)), None)
        if spec is not None and spec.kind == "Constraint":
            spec = next(iter(sem.children(ix, spec, "specification")), None)
        if spec is not None:
            return short(sem.value_text(ix, spec))
    if sem.is_requirement(ix, el):
        fields = sem.requirement_fields(ix, el)
        return short(fields.get("Id") or fields.get("Text"))
    return ""


def element_label(ix: ModelIndex, v: View) -> str:
    """'«stereotype» name : Type'; an unnamed typed element is labelled by its type alone
    (FU-003)."""
    el = ix.elements.get(v.element or "")
    if el is None:
        return _name(ix, v)
    name = _name(ix, v)
    t = next((tgt for r, tgt in el.refs if r == "type"), None)
    if t:
        name = f"{name} : {ix.label(t)}" if name else ix.label(t)
    st = _stereotypes(ix, el.id)
    return ((f"«{st[0]}» " if st else "") + name).strip() or f"({el.kind})"


def _shown_name(ix: ModelIndex, v: View) -> str:
    """The name drawn in a shape: its own, or for an unnamed typed element its type, as in
    the legend (FU-018)."""
    name = _name(ix, v)
    el = ix.elements.get(v.element or "")
    if not name and el is not None:
        t = next((tgt for r, tgt in el.refs if r == "type"), None)
        name = ix.label(t) if t else ""
    return name or (v.text or "")


@dataclass
class Node:
    num: int  # stable within the diagram: the legend key and the tag drawn on the shape
    view: View
    label: str  # full label, plain text
    depth: int  # nesting among shapes
    parent: int | None = None  # number of the shape this one is nested in


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
            g.pins[v.view_id or ""] = one_line(element_label(ix, v))
            g.pin_views.append(v)
            continue
        parent = by_id.get(v.parent or "")
        while parent is not None and (parent.view_id or "") not in g.node_of:
            parent = by_id.get(parent.parent or "")
        up = g.node_of[parent.view_id or ""] if parent is not None else None
        node = Node(len(g.nodes) + 1, v, one_line(element_label(ix, v) if v.element else f'"{v.text}"'),
                    up.depth + 1 if up else 0, up.num if up else None)
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
        stereotypes = _stereotypes(ix, el.id) if el else []
        label = " ".join([f"«{s}»" for s in stereotypes] + ([el.name] if el and el.name else []))
        verb = ""
        if directed:
            for k in [*stereotypes, rel.metaclass if rel else "", v.cls]:
                if k.lower() in VERBS:
                    verb = VERBS[k.lower()]
                    break
        items = []
        for f in flows.get(v.element or "", []):
            names = ", ".join(ix.label(i) for i in f.items) or ix.label(f.id)
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


def describe(ix: ModelIndex, g: DiagramGraph, link, nodes: list[Node] | None = None,
             links: list[Link] | None = None, where=None) -> tuple[list[str], list[str]]:
    """Markdown bullet lines for (legend, connections). `link(id)` renders a reference to
    an element; plain `ix.label` gives plain text, as in the LLM request. `nodes` and `links`
    narrow the lists (to a module), indenting from the shallowest shape; `where(node)` adds
    text after each shape, such as its module."""

    def ref(n: Node) -> str:
        v = n.view
        if v.element and v.element in ix.elements:
            linked = link(v.element)
            if linked.startswith("["):  # blocks, requirements...: a link, with the stereotype
                st = _stereotypes(ix, v.element)
                return (f"«{st[0]}» " if st else "") + linked
        return md_inline(n.label) or v.cls

    def end(view: View | None) -> str:
        node = g.node_of.get(view.view_id or "") if view is not None else None
        if node is None:
            return "(not shown)"
        pin = g.pins.get(view.view_id or "")
        return f"[{node.num}] {ref(node)}" + (f".{md_inline(pin)}" if pin else "") + (where(node) if where else "")

    shapes = g.nodes if nodes is None else nodes
    top = min((n.depth for n in shapes), default=0)
    legend = [f"{'  ' * (n.depth - top)}- [{n.num}] {n.view.cls}: {ref(n)}{where(n) if where else ''}" for n in shapes]
    lines = []
    for lk in g.links if links is None else links:
        arrow = "→" if lk.directed else "—"
        detail = "; ".join(x for x in (md_inline(lk.label), lk.verb,
                                       "carries " + ", ".join(md_inline(i) for i in lk.items) if lk.items else "")
                           if x)
        lines.append(f"- {end(lk.source)} {arrow}[{lk.view.cls}{': ' + detail if detail else ''}]{arrow} "
                     f"{end(lk.target)}")
    return legend, lines


# -- the sketch ---------------------------------------------------------------------------------
@dataclass
class Frame:
    """What a sketch shows, when not simply the whole diagram."""
    region: tuple[float, float, float, float] | None = None  # x0, y0, x1, y1 to draw; None for all
    focus: set[int] | None = None  # shapes drawn in full, the others faded; None for all
    tagged: set[int] = field(default_factory=set)  # faded shapes that keep their numbers (boundary shapes)
    fills: dict[int, str] = field(default_factory=dict)  # shape number -> fill colour (an overview's modules)
    outlines: list[tuple[str, tuple[float, float, float, float], str]] = field(default_factory=list)  # label, box, colour
    tags: bool = True  # number tags on shapes in focus


INK, FADED = "#1f4e79", "#b4b4b4"
FADED_LINE, FADED_TEXT, FADED_TAG = "#c8c8c8", "#8c8c8c", "#f0f0f0"


def canvas(w: float, h: float, pixels: int = IMAGE_PIXELS) -> tuple[int, int, float]:
    """(width, height, scale) for drawing w x h diagram units, with margins and a title
    line, within `pixels` at the diagram's own aspect ratio, sides in multiples of 48."""
    # Solve (w s + 2m)(h s + 2m + t) = pixels for the scale s.
    m, t = MARGIN, TITLE_PX
    a, b, c = w * h, w * (2 * m + t) + h * 2 * m, 2 * m * (2 * m + t) - pixels
    s = min((-b + math.sqrt(b * b - 4 * a * c)) / (2 * a), MAX_ZOOM)
    W = max(PATCH_PX, int((w * s + 2 * m) // PATCH_PX) * PATCH_PX)
    H = max(PATCH_PX, int((h * s + 2 * m + t) // PATCH_PX) * PATCH_PX)
    return W, H, max(0.01, min((W - 2 * m) / w, (H - 2 * m - t) / h))


def render_png(ix: ModelIndex, g: DiagramGraph, title: str, pixels: int = IMAGE_PIXELS,
               frame: Frame | None = None) -> bytes | None:
    """A sketch that fills the model's pixel budget (FU-015): shapes tagged with their legend
    numbers, connections with arrowheads at the target, pins as dots (FU-007, FU-008).

    With a `frame`, only its region is drawn, around the shapes in focus: other shapes are
    faded, and a connection leaving the picture ends in its far shape's number."""
    f = frame or Frame()
    focus = f.focus
    xs: list[float] = []
    ys: list[float] = []
    if f.region is not None:
        xs += [f.region[0], f.region[2]]
        ys += [f.region[1], f.region[3]]
    else:
        for n in g.nodes:
            if n.view.rect:
                x, y, w, h = n.view.rect
                xs += [x, x + w]
                ys += [y, y + h]
        for lk in g.links:
            for x, y in lk.view.points:
                xs.append(x)
                ys.append(y)
    if not xs:
        return None
    x0, y0, x1, y1 = min(xs), min(ys), max(xs), max(ys)
    w, h = max(1.0, x1 - x0), max(1.0, y1 - y0)
    W, H, scale = canvas(w, h, pixels)
    if f.outlines:  # room above the drawing for module labels
        pad = (FONT_PX + 16) / scale
        y0, h = y0 - pad, h + pad
        W, H, scale = canvas(w, h, pixels)
    img = Image.new("RGB" if f.fills or f.outlines else "L", (W, H), "white")
    d = ImageDraw.Draw(img)
    font = ImageFont.load_default(size=FONT_PX)
    d.text((MARGIN, 2), _fit(d, title, font, img.width - 2 * MARGIN), fill="black", font=font)

    def P(x: float, y: float) -> tuple[float, float]:
        return (x - x0) * scale + MARGIN, (y - y0) * scale + MARGIN + TITLE_PX

    def lit(n: Node | None) -> bool:
        return focus is None or (n is not None and n.num in focus)

    def end_node(view: View | None) -> Node | None:
        return g.node_of.get(view.view_id or "") if view is not None else None

    boxes = []
    for n in sorted((n for n in g.nodes if n.view.rect), key=lambda n: n.depth):
        x, y, rw, rh = n.view.rect  # type: ignore[misc]
        a, c = P(x, y), P(x + rw, y + rh)
        c = (max(c[0], a[0] + 3), max(c[1], a[1] + 3))
        ink, fill = (INK if lit(n) else FADED), f.fills.get(n.num, "white")
        if n.view.cls in ROUND:
            d.ellipse([a, c], outline=ink, fill=fill, width=1)
        elif n.view.cls == "Bar":  # fork and join bars
            d.rectangle([a, c], fill="black" if lit(n) else FADED)
        else:
            d.rectangle([a, c], outline=ink, fill=fill, width=1)
        boxes.append((n, a, c))
    stubs: list[tuple[int, tuple[float, float]]] = []  # far shapes of connections leaving the picture
    for lk in g.links:
        if len(lk.view.points) < 2:
            continue
        pts = [P(*p) for p in lk.view.points]
        s, t = end_node(lk.source), end_node(lk.target)
        shown = lit(s) or lit(t)
        _polyline(d, pts, dashed=lk.view.cls in DASHED, fill=None if shown else FADED_LINE)
        for seg in lk.more:
            if len(seg.points) >= 2:
                _polyline(d, [P(*p) for p in seg.points], dashed=lk.view.cls in DASHED, fill=None if shown else FADED_LINE)
        if lk.directed:
            tip, prev = (pts[0], pts[1]) if lk.target_at_first_point else (pts[-1], pts[-2])
            _arrowhead(d, prev, tip, hollow=lk.view.cls in HOLLOW, fill="black" if shown else FADED_LINE)
        dirs = {i[-1:] for i in lk.items}  # "→" source to target, "←" target to source
        if dirs in ({"→"}, {"←"}):  # all items flow one way: show it halfway along
            # The points run from the path's first end to its second.
            _mid_arrow(d, pts, along=(dirs == {"→"}) != lk.target_at_first_point,
                       fill="black" if shown else FADED_LINE)
        if f.region is not None and shown and not (lit(s) and lit(t)):
            far = t if lit(s) else s
            far_first = (far is t) == lk.target_at_first_point  # the far end is at the first point
            inner = pts[::-1] if far_first else pts
            out = _leaving(inner, (0, TITLE_PX, W, H))
            if far is not None and out is not None:
                stubs.append((far.num, out))
    for v, label in g.connectors:  # small circles where a flow's segments break off
        if v.rect:
            x, y, rw, rh = v.rect
            cx, cy = P(x + rw / 2, y + rh / 2)
            r = max(3.0, min(rw, rh) * scale / 2)
            d.ellipse([cx - r, cy - r, cx + r, cy + r], outline=INK, fill="white")
            d.text((cx + r + 2, cy - FONT_PX / 2 - 1), label, fill="black", font=font)
    for v in g.pin_views:  # pins and ports: dots on their owner's border
        if v.rect:
            x, y, rw, rh = v.rect
            cx, cy = P(x + rw / 2, y + rh / 2)
            dot = INK if lit(g.node_of.get(v.view_id or "")) else FADED
            d.ellipse([cx - 2.5, cy - 2.5, cx + 2.5, cy + 2.5], fill=dot)
    tagged: set[int] = set()
    for n, a, c in boxes:  # tags last, so that no line crosses them
        if not lit(n) and (n.num not in f.tagged or c[0] <= 0 or a[0] >= W or c[1] <= TITLE_PX or a[1] >= H):
            continue  # context only, or out of the picture (then marked where its connections leave)
        text_fill = "black" if lit(n) else FADED_TEXT
        if not lit(n):  # a boundary shape cut by the picture's edge keeps its number in view
            a = (min(max(a[0], 0), W - 40), min(max(a[1], TITLE_PX), H - FONT_PX - 4))
            tagged.add(n.num)
        tw = 0.0
        if f.tags or not lit(n):
            tag = str(n.num)
            tw = d.textlength(tag, font=font)
            d.rectangle([a[0] + 1, a[1] + 1, a[0] + tw + 5, a[1] + FONT_PX + 3], fill="#e4e4e4" if lit(n) else FADED_TAG)
            d.text((a[0] + 3, a[1] + 1), tag, fill=text_fill, font=font)
        room = c[0] - a[0] - tw - 10
        name = _shown_name(ix, n.view)
        if room > 4 * FONT_PX * 0.5 and c[1] - a[1] >= FONT_PX + 2 and name:
            d.text((a[0] + tw + 8, a[1] + 1), _fit(d, name, font, room), fill=text_fill, font=font)
    big = ImageFont.load_default(size=FONT_PX + 4)
    for label, (bx0, by0, bx1, by1), colour in f.outlines:  # an overview's modules
        a, c = P(bx0, by0), P(bx1, by1)
        d.rectangle([a[0] - 3, a[1] - 3, c[0] + 3, c[1] + 3], outline=colour, width=2)
        lw, lh = d.textlength(label, font=big) + 8, FONT_PX + 9
        # The label sits outside the outline's top left corner, so that it hides no shape's
        # number: there is room above the drawing.
        top = max(TITLE_PX, a[1] - 3 - lh)
        d.rectangle([a[0] - 3, top, a[0] - 3 + lw, top + lh], fill=colour)
        d.text((a[0] + 1, top + 1), label, fill="white", font=big)
    if f.region is not None:
        seen = tagged
        for num, (px, py) in stubs:
            if num in seen:
                continue
            seen.add(num)
            tag = str(num)
            tw = d.textlength(tag, font=font)
            px = min(max(px - tw / 2 - 2, 1), W - tw - 6)
            py = min(max(py - FONT_PX / 2 - 1, TITLE_PX + 1), H - FONT_PX - 4)
            d.rectangle([px, py, px + tw + 4, py + FONT_PX + 2], fill=FADED_TAG, outline=FADED)
            d.text((px + 2, py), tag, fill=FADED_TEXT, font=font)
        d.rectangle([0, 0, W, TITLE_PX - 1], fill="white")  # shapes cut by the region stop below the title
        d.text((MARGIN, 2), _fit(d, title, font, img.width - 2 * MARGIN), fill="black", font=font)
        d.line([(0, TITLE_PX - 1), (W, TITLE_PX - 1)], fill=FADED_LINE)
    buf = io.BytesIO()
    img.save(buf, "PNG", compress_level=6)
    return buf.getvalue()


def _leaving(pts: list[tuple[float, float]], box: tuple[float, float, float, float]) -> tuple[float, float] | None:
    """Where a polyline starting inside `box` (x0, y0, x1, y1) first leaves it; None if it
    doesn't."""
    bx0, by0, bx1, by1 = box

    def inside(p: tuple[float, float]) -> bool:
        return bx0 <= p[0] <= bx1 and by0 <= p[1] <= by1

    for p, q in itertools.pairwise(pts):
        if inside(p) and not inside(q):
            t = 1.0
            for lo, hi, a, b in ((bx0, bx1, p[0], q[0]), (by0, by1, p[1], q[1])):
                if b < lo:
                    t = min(t, (lo - a) / (b - a))
                elif b > hi:
                    t = min(t, (hi - a) / (b - a))
            return p[0] + (q[0] - p[0]) * t, p[1] + (q[1] - p[1]) * t
    return None


def _fit(d: ImageDraw.ImageDraw, text: str, font, width: float) -> str:
    """`text` on one line, cut with an ellipsis to fit `width` px (the legend has it all):
    the longest prefix that fits, found by bisection, since notes and requirement texts
    can run to thousands of characters."""
    text = one_line(text)  # Pillow can't measure text with line breaks (FU-016)
    if d.textlength(text, font=font) <= width:
        return text
    lo, hi = 0, len(text) - 1  # the longest fitting prefix has lo to hi characters
    while lo < hi:
        mid = (lo + hi + 1) // 2
        if d.textlength(text[:mid] + "…", font=font) <= width:
            lo = mid
        else:
            hi = mid - 1
    return text[:lo] + "…" if lo else ""


def _polyline(d: ImageDraw.ImageDraw, pts: list[tuple[float, float]], dashed: bool, fill: str | None = None) -> None:
    if not dashed:
        d.line(pts, fill=fill or "black", width=1)
        return
    for p, q in itertools.pairwise(pts):
        length = math.dist(p, q)
        steps = max(1, int(length // 5))
        for i in range(0, steps, 2):  # 5 px dashes, 5 px gaps
            t0, t1 = i / steps, min(1.0, (i + 1) / steps)
            d.line([(p[0] + (q[0] - p[0]) * t0, p[1] + (q[1] - p[1]) * t0),
                    (p[0] + (q[0] - p[0]) * t1, p[1] + (q[1] - p[1]) * t1)], fill=fill or "#333333", width=1)


def _arrowhead(d: ImageDraw.ImageDraw, p: tuple[float, float], q: tuple[float, float], hollow: bool,
               fill: str = "black") -> None:
    """An arrowhead at `q`, pointing away from `p`: a hollow triangle for generalization and
    realization, an open arrow otherwise."""
    ang = math.atan2(q[1] - p[1], q[0] - p[0])
    size = 10
    left = (q[0] - size * math.cos(ang - 0.45), q[1] - size * math.sin(ang - 0.45))
    right = (q[0] - size * math.cos(ang + 0.45), q[1] - size * math.sin(ang + 0.45))
    if hollow:
        d.polygon([q, left, right], outline=fill, fill="white")
    else:
        d.line([left, q, right], fill=fill, width=2)


def _mid_arrow(d: ImageDraw.ImageDraw, pts: list[tuple[float, float]], along: bool, fill: str = "black") -> None:
    """A small filled triangle halfway along a connector, pointing the way its items flow:
    along the points' order, or against it."""
    lengths = [math.dist(p, q) for p, q in itertools.pairwise(pts)]
    half, i = sum(lengths) / 2, 0
    while i < len(lengths) - 1 and half > lengths[i]:
        half -= lengths[i]
        i += 1
    p, q = pts[i], pts[i + 1]
    t = half / lengths[i] if lengths[i] else 0.5
    m = (p[0] + (q[0] - p[0]) * t, p[1] + (q[1] - p[1]) * t)
    ang = math.atan2(q[1] - p[1], q[0] - p[0]) + (0 if along else math.pi)
    tip = (m[0] + 6 * math.cos(ang), m[1] + 6 * math.sin(ang))
    left = (m[0] - 4 * math.cos(ang - 1.2), m[1] - 4 * math.sin(ang - 1.2))
    right = (m[0] - 4 * math.cos(ang + 1.2), m[1] - 4 * math.sin(ang + 1.2))
    d.polygon([tip, left, right], fill=fill)
