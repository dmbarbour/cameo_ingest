"""Turn diagram layouts into (a) deterministic node/edge text and (b) a PNG sketch.

The sketch is not a faithful Cameo rendering: boxes, labels and connector paths only,
enough for a vision model (or a human) to see structure and arrangement. The
node/edge text is the authoritative, deterministic description.
"""

from __future__ import annotations

import io
import textwrap
from dataclasses import dataclass

from PIL import Image, ImageDraw, ImageFont

from .layout import Layout, View
from .model import ModelIndex
from .text import md_inline

MAX_SIDE = 2000
MARGIN = 20
# Views that only decorate another view (labels, ends); described through their owner.
DECORATION = {"TextBox", "TextBoxWithIcon", "ConnectorEnd", "Role", "NoteAnchor", "DiagramShape"}
DIRECTED = {
    "ControlFlow", "ObjectFlow", "Dependency", "Abstraction", "Realization", "Usage", "Include",
    "Extend", "Generalization", "InformationFlow", "Transition", "FlowConnector", "Message",
    "InterfaceRealization", "Containment",
}


@dataclass
class Edge:
    view: View
    source: View | None
    target: View | None


def element_label(ix: ModelIndex, v: View) -> str:
    if v.element and v.element in ix.elements:
        el = ix.elements[v.element]
        st = ix.stereotype_names(el.id)
        name = el.name or ""
        if not name:  # e.g. CallBehaviorAction: show the invoked behavior
            for role in ("behavior", "operation", "signal", "event"):
                tgt = next((t for r, t in el.refs if r == role), None)
                if tgt:
                    name = ix.label(tgt)
                    break
        t = [r for r, _ in el.refs if r == "type"]
        if t:
            tid = next(tgt for r, tgt in el.refs if r == "type")
            name = f"{name} : {ix.label(tid)}"
        pre = f"«{st[0]}» " if st else ""
        return (pre + name).strip() or f"({el.kind})"
    if v.element:  # element from a used project / library
        return v.element.rsplit("#", 1)[-1] if "#" in v.element else v.element
    return v.text or ""


def edges(layout: Layout) -> list[Edge]:
    by_id = layout.by_view_id()
    return [Edge(v, by_id.get(v.first or ""), by_id.get(v.second or ""))
            for v in layout.views if v.is_path and (v.first or v.second)]


def _anchor_owner(v: View | None, by_id: dict[str, View]) -> View | None:
    """For a pin / port / end, the shape it is attached to."""
    if v is None:
        return None
    p = by_id.get(v.parent or "")
    return p if p is not None and p.cls not in ("DiagramFrame",) and p.rect else None


def describe(ix: ModelIndex, layout: Layout, link) -> tuple[list[str], list[str]]:
    """Markdown bullet lines for (nodes, edges). `link(id)` renders an element reference."""
    by_id = layout.by_view_id()

    def ref(v: View | None) -> str:
        if v is None:
            return "?"
        if v.element and v.element in ix.elements:
            # Linkable elements (blocks, requirements...) get a link; features such as
            # parts and ports read better as "«stereotype» name : Type".
            linked = link(v.element)
            base = linked if linked.startswith("[") else md_inline(element_label(ix, v))
        else:
            base = md_inline(element_label(ix, v)) or v.cls
        owner = _anchor_owner(v, by_id)
        if owner is not None and v.cls in ("Pin", "Port", "ObjectNode", "ParameterNode"):
            return f"{md_inline(element_label(ix, owner)) or owner.cls}.{base}"
        return base

    nodes = []
    for v in layout.views:
        if v.is_path or v.cls in DECORATION or v.cls == "DiagramFrame":
            continue
        if not v.element and not v.text:
            continue
        indent = "  " * max(0, v.depth - (1 if _in_frame(v, by_id) else 0))
        label = ref(v) if v.element else f'"{md_inline(v.text or "")}"'
        nodes.append(f"{indent}- {v.cls}: {label}")
    edge_lines = []
    for e in edges(layout):
        v = e.view
        name = ""
        if v.element and v.element in ix.elements:
            el = ix.elements[v.element]
            st = ix.stereotype_names(el.id)
            name = " ".join([f"«{s}»" for s in st] + ([md_inline(el.name)] if el.name else []))
            conveyed = [md_inline(ix.label(t)) for r, t in el.refs if r == "conveyed"]
            if conveyed:
                name += f" (conveys {', '.join(conveyed)})"
        arrow = "→" if v.cls in DIRECTED else "—"
        edge_lines.append(f"- {ref(e.source)} {arrow}[{v.cls}{': ' + name.strip() if name.strip() else ''}]"
                          f"{arrow} {ref(e.target)}")
    return nodes, edge_lines


def _in_frame(v: View, by_id: dict[str, View]) -> bool:
    cur = by_id.get(v.parent or "")
    while cur is not None:
        if cur.cls == "DiagramFrame":
            return True
        cur = by_id.get(cur.parent or "")
    return False


def render_png(ix: ModelIndex, layout: Layout, title: str) -> bytes | None:
    b = layout.bounds()
    if b is None:
        return None
    x0, y0, x1, y1 = b
    w, h = max(1.0, x1 - x0), max(1.0, y1 - y0)
    scale = min(1.5, MAX_SIDE / max(w, h))
    W, H = int(w * scale) + 2 * MARGIN, int(h * scale) + 2 * MARGIN + 24
    img = Image.new("L", (W, H), "white")
    d = ImageDraw.Draw(img)
    font = ImageFont.load_default(size=max(9, int(12 * scale)))
    tfont = ImageFont.load_default(size=16)
    d.text((MARGIN, 4), title, fill="black", font=tfont)

    def P(x: float, y: float) -> tuple[float, float]:
        return (x - x0) * scale + MARGIN, (y - y0) * scale + MARGIN + 24

    for v in sorted((v for v in layout.views if v.rect), key=lambda v: v.depth):
        x, y, rw, rh = v.rect  # type: ignore[misc]
        a, c = P(x, y), P(x + rw, y + rh)
        if c[0] - a[0] < 2 or c[1] - a[1] < 2:
            continue
        if v.cls in ("TextBox", "TextBoxWithIcon"):
            if v.text:
                d.text(a, v.text, fill="#333333", font=font)
            continue
        outline = "#999999" if v.cls == "DiagramFrame" else "#1f4e79"
        if v.cls in ("UseCase", "InitialNode", "ActivityFinalNode", "PseudoNode"):
            d.ellipse([a, c], outline=outline, width=1)
        else:
            d.rectangle([a, c], outline=outline, width=1)
        label = element_label(ix, v) if min(c[0] - a[0], c[1] - a[1]) >= 16 else ""
        if label:
            chars = max(4, int((c[0] - a[0]) / max(5, 6 * scale)))
            text = "\n".join(textwrap.wrap(label, chars)[:3])
            d.multiline_text((a[0] + 3, a[1] + 2), text, fill="black", font=font)
    for v in layout.views:
        if len(v.points) < 2:
            continue
        pts = [P(*p) for p in v.points]
        dashed = v.cls in ("Dependency", "Abstraction", "Realization", "Usage", "Include", "Extend")
        d.line(pts, fill="#555555" if dashed else "black", width=1)
        if v.cls in DIRECTED:
            _arrow(d, pts[-2], pts[-1], hollow=v.cls in ("Generalization", "Realization", "InterfaceRealization"))
    buf = io.BytesIO()
    img.save(buf, "PNG", compress_level=6)
    return buf.getvalue()


def _arrow(d: ImageDraw.ImageDraw, p: tuple[float, float], q: tuple[float, float], hollow: bool) -> None:
    import math

    ang = math.atan2(q[1] - p[1], q[0] - p[0])
    size = 9
    left = (q[0] - size * math.cos(ang - 0.4), q[1] - size * math.sin(ang - 0.4))
    right = (q[0] - size * math.cos(ang + 0.4), q[1] - size * math.sin(ang + 0.4))
    if hollow:
        d.polygon([q, left, right], outline="black", fill="white")
    else:
        d.line([left, q, right], fill="black", width=1)
