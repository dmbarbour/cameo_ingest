"""A diagram's sketch as SVG, for people (plan KX-05): the shapes, numbers, connections and names
that `sketch` draws for the vision model, as vectors in the diagram's own units, so that they
stay sharp at any zoom.

Each shape is a group with its element's key (`data-k`) and its full label as a tooltip
(`<title>`), so that a page can open a shape's element, and a reader can see a name that had to
be cut. Like the PNG, it is not a Cameo rendering: the diagram's page holds its text.
"""

from __future__ import annotations

from xml.sax.saxutils import escape as _escape
from xml.sax.saxutils import quoteattr as _quoteattr

from .diagram_graph import DiagramGraph, Node, drawing_order
from .drawing import DASHED, HOLLOW, ROUND, extent, flow_along, head_end, head_legs, mid_arrow
from .text import one_line, xml_safe

FONT = 11.0  # diagram units
CHAR = 0.56 * FONT  # an estimate of a character's width, to shorten names that don't fit
MARGIN = 10.0
TITLE = 22.0
INK, LINE, TAG = "#1f4e79", "#333333", "#e4e4e4"


def escape(text: str) -> str:
    """Text for SVG: escaped, without the characters XML forbids."""
    return _escape(xml_safe(text))


def quoteattr(text: str) -> str:
    return _quoteattr(xml_safe(text))


def _n(v: float) -> str:
    return f"{v:.1f}".rstrip("0").rstrip(".")


def _pts(pts: list[tuple[float, float]]) -> str:
    return " ".join(f"{_n(x)},{_n(y)}" for x, y in pts)


def _fit(text: str, width: float) -> str:
    text = one_line(text)
    room = int(width // CHAR)
    if len(text) <= room:
        return text
    return text[:room - 1] + "…" if room > 1 else ""


def _arrowhead(p: tuple[float, float], q: tuple[float, float], hollow: bool) -> str:
    left, right = head_legs(p, q, 9.0)
    if hollow:
        return f'<polygon points="{_pts([q, left, right])}" fill="white" stroke="{LINE}"/>'
    return f'<polyline points="{_pts([left, q, right])}" fill="none" stroke="{LINE}" stroke-width="1.5"/>'


def _outlines(shapes: list[Node]) -> list[str]:
    """Each shape's outline, outer before inner, with its element's key and full label."""
    out: list[str] = []
    for n in shapes:  # outlines first, outer before inner
        x, y, rw, rh = n.view.rect  # type: ignore[misc]
        rw, rh = max(rw, 3), max(rh, 3)
        key = f" data-k={quoteattr(n.view.element)}" if n.view.element else ""
        out.append(f'<g class="s"{key}><title>{escape(f"[{n.num}] {n.label}")}</title>')
        if n.view.cls in ROUND:
            out.append(f'<ellipse cx="{_n(x + rw / 2)}" cy="{_n(y + rh / 2)}" rx="{_n(rw / 2)}" ry="{_n(rh / 2)}" '
                       f'fill="white" stroke="{INK}"/>')
        elif n.view.cls == "Bar":
            out.append(f'<rect x="{_n(x)}" y="{_n(y)}" width="{_n(rw)}" height="{_n(rh)}" fill="black"/>')
        else:
            out.append(f'<rect x="{_n(x)}" y="{_n(y)}" width="{_n(rw)}" height="{_n(rh)}" fill="white" '
                       f'fill-opacity="0.9" stroke="{INK}"/>')
        out.append("</g>")
    return out


def _trees(g: DiagramGraph) -> list[str]:
    """A tree's bars, and a head at the base when every member points there; the members keep
    their own heads too, at the bar: the model reads directions better so than from one head (plan SK)."""
    out: list[str] = []
    for t in g.trees:
        (a, b), (c, e) = t.vertical, t.horizontal
        kinds = {m.view.cls for m in t.members}
        dash = ' stroke-dasharray="5 4"' if kinds & DASHED else ""
        what = "/".join(sorted(kinds))
        out.append(f'<g><title>{escape(f"{what} of [{t.parent.num if t.parent else chr(63)}]")}</title>'
                   f'<polyline points="{_pts([a, b])}" fill="none" stroke="{LINE}"{dash}/>'
                   f'<polyline points="{_pts([c, e])}" fill="none" stroke="{LINE}"{dash}/>'
                   f'{_arrowhead(b, a, bool(kinds & HOLLOW)) if t.to_parent else ""}</g>')
    return out


def _links(g: DiagramGraph) -> list[str]:
    """Each connection: its segments, its head, an arrow halfway along a flow, and what it is as a
    tooltip."""
    out: list[str] = []
    for lk in g.links:
        if len(lk.view.points) < 2:
            continue
        dash = ' stroke-dasharray="5 4"' if lk.view.cls in DASHED else ""
        parts = [f'<polyline points="{_pts(seg.points)}" fill="none" stroke="{LINE}"{dash}/>'
                 for seg in [lk.view, *lk.more] if len(seg.points) >= 2]
        pts = lk.view.points
        if lk.directed:
            parts.append(_arrowhead(*head_end(lk, pts), lk.view.cls in HOLLOW))
        along = flow_along(lk)
        if along is not None:  # all items flow one way: an arrow halfway along
            parts.append(f'<polygon points="{_pts(mid_arrow(pts, along))}" fill="{LINE}"/>')
        s, t = g.node(lk.source), g.node(lk.target)
        what = "; ".join(x for x in (lk.label, lk.verb, ", ".join(i.text for i in lk.items)) if x)
        tip_text = f"[{s.num if s else '?'}] {lk.view.cls}{': ' + what if what else ''} [{t.num if t else '?'}]"
        out.append(f"<g><title>{escape(tip_text)}</title>{''.join(parts)}</g>")
    return out


def _marks(g: DiagramGraph) -> list[str]:
    """Connector circles where a flow breaks off, with where it goes; pins and ports as dots."""
    out: list[str] = []
    for v, label in g.connectors:
        if v.rect:
            x, y, rw, rh = v.rect
            r = max(3.0, min(rw, rh) / 2)
            out.append(f'<circle cx="{_n(x + rw / 2)}" cy="{_n(y + rh / 2)}" r="{_n(r)}" fill="white" stroke="{INK}"/>')
            out.append(f'<text x="{_n(x + rw / 2 + r + 2)}" y="{_n(y + rh / 2 + 4)}">{escape(label)}</text>')
    for v in g.pin_views:
        if v.rect:
            x, y, rw, rh = v.rect
            out.append(f'<circle cx="{_n(x + rw / 2)}" cy="{_n(y + rh / 2)}" r="2.5" fill="{INK}"/>')
    return out


def _names(shapes: list[Node]) -> list[str]:
    """Each shape's number tag and name, last, so that no line crosses them."""
    out: list[str] = []
    for n in shapes:  # numbers and names last, so that no line crosses them
        x, y, rw, rh = n.view.rect  # type: ignore[misc]
        key = f" data-k={quoteattr(n.view.element)}" if n.view.element else ""
        tag = str(n.num)
        tw = len(tag) * CHAR + 4
        name = n.shown or n.view.text or ""
        out.append(f'<g class="s"{key}><title>{escape(f"[{n.num}] {n.label}")}</title>'
                   f'<rect x="{_n(x + 1)}" y="{_n(y + 1)}" width="{_n(tw)}" height="{_n(FONT + 3)}" fill="{TAG}"/>'
                   f'<text x="{_n(x + 3)}" y="{_n(y + FONT)}">{tag}</text>')
        room = rw - tw - 8
        if name and room > 3 * CHAR and rh >= FONT + 2:
            out.append(f'<text x="{_n(x + tw + 6)}" y="{_n(y + FONT)}">{escape(_fit(name, room))}</text>')
        out.append("</g>")
    return out


def render_svg(g: DiagramGraph, title: str) -> str | None:
    """The whole diagram as SVG text; None when it has nothing to draw."""
    box = extent(g)
    if box is None:
        return None
    x0, y0 = box[0] - MARGIN, box[1] - MARGIN - TITLE
    w, h = box[2] - x0 + MARGIN, box[3] - y0 + MARGIN
    out = [(f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="{_n(x0)} {_n(y0)} {_n(w)} {_n(h)}" '
            f'width="{_n(w)}" height="{_n(h)}" font-family="Segoe UI, Arial, sans-serif" font-size="{_n(FONT)}">'),
           f'<rect x="{_n(x0)}" y="{_n(y0)}" width="{_n(w)}" height="{_n(h)}" fill="white"/>',
           (f'<text x="{_n(x0 + MARGIN)}" y="{_n(y0 + 15)}" font-weight="bold">'
            f'{escape(_fit(title, w - 2 * MARGIN))}</text>')]
    shapes = drawing_order(g)
    out += _outlines(shapes) + _trees(g) + _links(g) + _marks(g) + _names(shapes)
    out.append("</svg>")
    return "\n".join(out)
