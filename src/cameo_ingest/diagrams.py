"""A diagram's layout as a graph, and the two views made from it: text and a sketch.

`build` turns a layout into numbered nodes (the shapes) and links (the connections). A
link's direction comes from the model relationship it shows (FU-001), and a connector
carries the item flows that it realizes (FU-002). `describe` writes the graph as text: a
legend of numbered shapes, and connections between those numbers. `render_png` draws a
sketch at the size the vision model sees (FU-012) in which shapes carry the same numbers,
so full labels live in the legend instead of being wrapped into boxes (FU-008).

The sketch is not a faithful Cameo rendering; the text is the authoritative description.
"""

from __future__ import annotations

import io
import itertools
import math
from dataclasses import dataclass, field

from PIL import Image, ImageDraw, ImageFont

from .layout import Layout, View
from .model import ModelIndex
from .semantics import ItemFlow, Relationship
from .text import md_inline

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
    for role in ("behavior", "operation", "signal", "event"):
        tgt = next((t for r, t in el.refs if r == role), None)
        if tgt:
            return ix.label(tgt)
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


@dataclass
class Node:
    num: int  # stable within the diagram: the legend key and the tag drawn on the shape
    view: View
    label: str  # full label, plain text
    depth: int  # nesting among shapes


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


@dataclass
class DiagramGraph:
    nodes: list[Node] = field(default_factory=list)
    links: list[Link] = field(default_factory=list)
    node_of: dict[str, Node] = field(default_factory=dict)  # view id of a shape, or of a pin on it
    pins: dict[str, str] = field(default_factory=dict)  # view id of a pin or port -> its label
    pin_views: list[View] = field(default_factory=list)

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
            g.pins[v.view_id or ""] = element_label(ix, v)
            g.pin_views.append(v)
            continue
        parent = by_id.get(v.parent or "")
        while parent is not None and (parent.view_id or "") not in g.node_of:
            parent = by_id.get(parent.parent or "")
        depth = g.node_of[parent.view_id or ""].depth + 1 if parent is not None else 0
        node = Node(len(g.nodes) + 1, v, element_label(ix, v) if v.element else f'"{v.text}"', depth)
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

    for v in layout.views:
        if not v.is_path or not (v.first or v.second):
            continue
        first, second = by_id.get(v.first or ""), by_id.get(v.second or "")
        rel = rels.get(v.element or "")
        directed = v.cls in DIRECTED or (rel is not None and rel.metaclass in DIRECTED)
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
        g.links.append(Link(v, source, target, directed, label, verb, items, at_first))
    return g


def describe(ix: ModelIndex, g: DiagramGraph, link) -> tuple[list[str], list[str]]:
    """Markdown bullet lines for (legend, connections). `link(id)` renders a reference to
    an element; plain `ix.label` gives plain text, as in the LLM request."""

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
        return f"[{node.num}] {ref(node)}" + (f".{md_inline(pin)}" if pin else "")

    legend = [f"{'  ' * n.depth}- [{n.num}] {n.view.cls}: {ref(n)}" for n in g.nodes]
    lines = []
    for lk in g.links:
        arrow = "→" if lk.directed else "—"
        detail = "; ".join(x for x in (md_inline(lk.label), lk.verb,
                                       "carries " + ", ".join(md_inline(i) for i in lk.items) if lk.items else "")
                           if x)
        lines.append(f"- {end(lk.source)} {arrow}[{lk.view.cls}{': ' + detail if detail else ''}]{arrow} "
                     f"{end(lk.target)}")
    return legend, lines


# -- the sketch ---------------------------------------------------------------------------------
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


def render_png(ix: ModelIndex, g: DiagramGraph, title: str, pixels: int = IMAGE_PIXELS) -> bytes | None:
    """A sketch that fills the model's pixel budget (FU-015): shapes tagged with their legend
    numbers, connections with arrowheads at the target, pins as dots (FU-007, FU-008)."""
    xs: list[float] = []
    ys: list[float] = []
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
    img = Image.new("L", (W, H), "white")
    d = ImageDraw.Draw(img)
    font = ImageFont.load_default(size=FONT_PX)
    d.text((MARGIN, 2), _fit(d, title, font, img.width - 2 * MARGIN), fill="black", font=font)

    def P(x: float, y: float) -> tuple[float, float]:
        return (x - x0) * scale + MARGIN, (y - y0) * scale + MARGIN + TITLE_PX

    boxes = []
    for n in sorted((n for n in g.nodes if n.view.rect), key=lambda n: n.depth):
        x, y, rw, rh = n.view.rect  # type: ignore[misc]
        a, c = P(x, y), P(x + rw, y + rh)
        c = (max(c[0], a[0] + 3), max(c[1], a[1] + 3))
        if n.view.cls in ROUND:
            d.ellipse([a, c], outline="#1f4e79", fill="white", width=1)
        elif n.view.cls == "Bar":  # fork and join bars
            d.rectangle([a, c], fill="black")
        else:
            d.rectangle([a, c], outline="#1f4e79", fill="white", width=1)
        boxes.append((n, a, c))
    for lk in g.links:
        if len(lk.view.points) < 2:
            continue
        pts = [P(*p) for p in lk.view.points]
        _polyline(d, pts, dashed=lk.view.cls in DASHED)
        if lk.directed:
            tip, prev = (pts[0], pts[1]) if lk.target_at_first_point else (pts[-1], pts[-2])
            _arrowhead(d, prev, tip, hollow=lk.view.cls in HOLLOW)
        dirs = {i[-1:] for i in lk.items}  # "→" source to target, "←" target to source
        if dirs in ({"→"}, {"←"}):  # all items flow one way: show it halfway along
            # The points run from the path's first end to its second.
            _mid_arrow(d, pts, along=(dirs == {"→"}) != lk.target_at_first_point)
    for v in g.pin_views:  # pins and ports: dots on their owner's border
        if v.rect:
            x, y, rw, rh = v.rect
            cx, cy = P(x + rw / 2, y + rh / 2)
            d.ellipse([cx - 2.5, cy - 2.5, cx + 2.5, cy + 2.5], fill="#1f4e79")
    for n, a, c in boxes:  # tags last, so that no line crosses them
        tag = str(n.num)
        tw = d.textlength(tag, font=font)
        d.rectangle([a[0] + 1, a[1] + 1, a[0] + tw + 5, a[1] + FONT_PX + 3], fill="#e4e4e4")
        d.text((a[0] + 3, a[1] + 1), tag, fill="black", font=font)
        room = c[0] - a[0] - tw - 10
        name = _name(ix, n.view) or (n.view.text or "")
        if room > 4 * FONT_PX * 0.5 and c[1] - a[1] >= FONT_PX + 2 and name:
            d.text((a[0] + tw + 8, a[1] + 1), _fit(d, name, font, room), fill="black", font=font)
    buf = io.BytesIO()
    img.save(buf, "PNG", compress_level=6)
    return buf.getvalue()


def _fit(d: ImageDraw.ImageDraw, text: str, font, width: float) -> str:
    """`text` on one line, cut with an ellipsis to fit `width` px (the legend has it all)."""
    if d.textlength(text, font=font) <= width:
        return text
    while text and d.textlength(text + "…", font=font) > width:
        text = text[:-1]
    return text + "…" if text else ""


def _polyline(d: ImageDraw.ImageDraw, pts: list[tuple[float, float]], dashed: bool) -> None:
    if not dashed:
        d.line(pts, fill="black", width=1)
        return
    for p, q in itertools.pairwise(pts):
        length = math.dist(p, q)
        steps = max(1, int(length // 5))
        for i in range(0, steps, 2):  # 5 px dashes, 5 px gaps
            t0, t1 = i / steps, min(1.0, (i + 1) / steps)
            d.line([(p[0] + (q[0] - p[0]) * t0, p[1] + (q[1] - p[1]) * t0),
                    (p[0] + (q[0] - p[0]) * t1, p[1] + (q[1] - p[1]) * t1)], fill="#333333", width=1)


def _arrowhead(d: ImageDraw.ImageDraw, p: tuple[float, float], q: tuple[float, float], hollow: bool) -> None:
    """An arrowhead at `q`, pointing away from `p`: a hollow triangle for generalization and
    realization, an open arrow otherwise."""
    ang = math.atan2(q[1] - p[1], q[0] - p[0])
    size = 10
    left = (q[0] - size * math.cos(ang - 0.45), q[1] - size * math.sin(ang - 0.45))
    right = (q[0] - size * math.cos(ang + 0.45), q[1] - size * math.sin(ang + 0.45))
    if hollow:
        d.polygon([q, left, right], outline="black", fill="white")
    else:
        d.line([left, q, right], fill="black", width=2)


def _mid_arrow(d: ImageDraw.ImageDraw, pts: list[tuple[float, float]], along: bool) -> None:
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
    d.polygon([tip, left, right], fill="black")
