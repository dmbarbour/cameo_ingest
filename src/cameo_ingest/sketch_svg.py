"""A diagram's sketch as SVG, for people (plan KX-05): the shapes, numbers, connections and names
that `sketch` draws for the vision model, as vectors in the diagram's own units, so that they
stay sharp at any zoom.

Each shape is a group with its element's key (`data-k`) and its full label as a tooltip
(`<title>`), so that a page can open a shape's element, and a reader can see a name that had to
be cut. Like the PNG, it is not a Cameo rendering: the diagram's page holds its text.
"""

from __future__ import annotations

import math
from xml.sax.saxutils import escape, quoteattr

from .diagram_graph import DiagramGraph
from .layout import View
from .model import ModelIndex
from .sketch import DASHED, HOLLOW, ROUND
from .text import one_line

FONT = 11.0  # diagram units
CHAR = 0.56 * FONT  # an estimate of a character's width, to shorten names that don't fit
MARGIN = 10.0
TITLE = 22.0
INK, LINE, TAG = "#1f4e79", "#333333", "#e4e4e4"


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
    ang = math.atan2(q[1] - p[1], q[0] - p[0])
    size = 9.0
    left = (q[0] - size * math.cos(ang - 0.45), q[1] - size * math.sin(ang - 0.45))
    right = (q[0] - size * math.cos(ang + 0.45), q[1] - size * math.sin(ang + 0.45))
    if hollow:
        return f'<polygon points="{_pts([q, left, right])}" fill="white" stroke="{LINE}"/>'
    return f'<polyline points="{_pts([left, q, right])}" fill="none" stroke="{LINE}" stroke-width="1.5"/>'


def _mid_arrow(pts: list[tuple[float, float]], along: bool) -> str:
    lengths = [math.dist(p, q) for p, q in zip(pts, pts[1:], strict=False)]
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
    return f'<polygon points="{_pts([tip, left, right])}" fill="{LINE}"/>'


def render_svg(ix: ModelIndex, g: DiagramGraph, title: str) -> str | None:
    """The whole diagram as SVG text; None when it has nothing to draw."""
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
    x0, y0 = min(xs) - MARGIN, min(ys) - MARGIN - TITLE
    w, h = max(xs) - x0 + MARGIN, max(ys) - y0 + MARGIN
    out = [f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="{_n(x0)} {_n(y0)} {_n(w)} {_n(h)}" '
           f'width="{_n(w)}" height="{_n(h)}" font-family="Segoe UI, Arial, sans-serif" font-size="{_n(FONT)}">',
           f'<rect x="{_n(x0)}" y="{_n(y0)}" width="{_n(w)}" height="{_n(h)}" fill="white"/>',
           f'<text x="{_n(x0 + MARGIN)}" y="{_n(y0 + 15)}" font-weight="bold">'
           f'{escape(_fit(title, w - 2 * MARGIN))}</text>']

    def end(view: View | None):
        return g.node_of.get(view.view_id or "") if view is not None else None

    shapes = sorted((n for n in g.nodes if n.view.rect), key=lambda n: n.depth)
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
    for lk in g.links:
        if len(lk.view.points) < 2:
            continue
        dash = ' stroke-dasharray="5 4"' if lk.view.cls in DASHED else ""
        parts = [f'<polyline points="{_pts(seg.points)}" fill="none" stroke="{LINE}"{dash}/>'
                 for seg in [lk.view, *lk.more] if len(seg.points) >= 2]
        pts = lk.view.points
        if lk.directed:
            tip, prev = (pts[0], pts[1]) if lk.target_at_first_point else (pts[-1], pts[-2])
            parts.append(_arrowhead(prev, tip, lk.view.cls in HOLLOW))
        dirs = {i[-1:] for i in lk.items}
        if dirs in ({"→"}, {"←"}):
            parts.append(_mid_arrow(pts, along=(dirs == {"→"}) != lk.target_at_first_point))
        s, t = end(lk.source), end(lk.target)
        what = "; ".join(x for x in (lk.label, lk.verb, ", ".join(lk.items)) if x)
        tip_text = f"[{s.num if s else '?'}] {lk.view.cls}{': ' + what if what else ''} [{t.num if t else '?'}]"
        out.append(f"<g><title>{escape(tip_text)}</title>{''.join(parts)}</g>")
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
    out.append("</svg>")
    return "\n".join(out)
