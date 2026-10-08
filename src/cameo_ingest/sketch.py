"""A diagram's sketch: drawn at the size the vision model sees (FU-012), its shapes tagged with
the numbers of the legend, so that full labels live in the text instead of being wrapped into
boxes (FU-008). A `Frame` narrows a sketch to one module of a large diagram, or colours the
modules in an overview (plan DV).

The sketch is not a faithful Cameo rendering; the text (`diagram_text`) is the authoritative
description.
"""

from __future__ import annotations

import colorsys
import io
import itertools
import math
from dataclasses import dataclass, field

from PIL import Image, ImageDraw, ImageFont

from .config import IMAGE_PIXELS, SKETCH
from .diagram_graph import DiagramGraph, Node, drawing_order
from .drawing import DASHED, HOLLOW, ROUND, extent, flow_along, head_end, head_legs, mid_arrow
from .partition import Partition
from .text import one_line
from .vision import patch_sides

MAX_ZOOM = 2.0  # small diagrams are not blown up further than this
MARGIN = 8


@dataclass(frozen=True)
class SketchStyle:
    """Sizes a sketch is drawn with, in the image's pixels: the tree's own settings, else the vision
    model's calibration (plan VA), else the uncalibrated defaults (`config.SKETCH`)."""

    font_px: int = SKETCH[0]  # names, number tags and the title
    arrow_px: float = SKETCH[1]  # an arrowhead's legs
    line_px: int = SKETCH[2]  # connections

    @property
    def title_px(self) -> int:
        return self.font_px + 6

    @property
    def head_stroke(self) -> int:
        return self.line_px + 1


STYLE = SketchStyle()
FONT_PX, TITLE_PX = STYLE.font_px, STYLE.title_px  # the defaults; a sketch draws with its style's


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


def canvas(w: float, h: float, pixels: int = IMAGE_PIXELS, title_px: int = TITLE_PX) -> tuple[int, int, float]:
    """(width, height, scale) for drawing w x h diagram units, with margins and a title
    line, within `pixels` at the diagram's own aspect ratio, sides in whole patches."""
    # Solve (w s + 2m)(h s + 2m + t) = pixels for the scale s.
    m, t = MARGIN, title_px
    a, b, c = w * h, w * (2 * m + t) + h * 2 * m, 2 * m * (2 * m + t) - pixels
    s = min((-b + math.sqrt(b * b - 4 * a * c)) / (2 * a), MAX_ZOOM)
    W, H = patch_sides(w * s + 2 * m, h * s + 2 * m + t)
    return W, H, max(0.01, min((W - 2 * m) / w, (H - 2 * m - t) / h))


@dataclass
class _Pen:
    """A sketch being drawn: its image, where diagram units land, and what is in focus."""

    d: ImageDraw.ImageDraw
    frame: Frame
    style: SketchStyle
    font: ImageFont.ImageFont
    x0: float
    y0: float
    scale: float
    W: int
    H: int

    def P(self, x: float, y: float) -> tuple[float, float]:
        return (x - self.x0) * self.scale + MARGIN, (y - self.y0) * self.scale + MARGIN + self.style.title_px

    def lit(self, n: Node | None) -> bool:
        return self.frame.focus is None or (n is not None and n.num in self.frame.focus)

    def line(self, shown: bool) -> str | None:
        return None if shown else FADED_LINE

    def head(self, shown: bool) -> str:
        return "black" if shown else FADED_LINE


def render_png(g: DiagramGraph, title: str, pixels: int = IMAGE_PIXELS,
               frame: Frame | None = None, style: SketchStyle = STYLE, drawn: dict[int, str] | None = None,
               ) -> bytes | None:
    """A sketch that fills the model's pixel budget (FU-015): shapes tagged with their legend
    numbers, connections with arrowheads at the target, pins as dots (FU-007, FU-008).

    With a `frame`, only its region is drawn, around the shapes in focus: other shapes are
    faded, and a connection leaving the picture ends in its far shape's number. `drawn`, if
    given, gets each shape in focus's name as drawn ("" when none fits), for validation."""
    f = frame or Frame()
    box = f.region if f.region is not None else extent(g)
    if box is None:
        return None
    x0, y0, x1, y1 = box
    w, h = max(1.0, x1 - x0), max(1.0, y1 - y0)
    W, H, scale = canvas(w, h, pixels, style.title_px)
    if f.outlines:  # room above the drawing for module labels
        pad = (style.font_px + 16) / scale
        y0, h = y0 - pad, h + pad
        W, H, scale = canvas(w, h, pixels, style.title_px)
    img = Image.new("RGB" if f.fills or f.outlines else "L", (W, H), "white")
    pen = _Pen(ImageDraw.Draw(img), f, style, ImageFont.load_default(size=style.font_px), x0, y0, scale, W, H)
    _title(pen, title)
    boxes = _shapes(pen, g)
    _trees(pen, g)
    stubs = _links(pen, g)
    _connectors_and_pins(pen, g)
    tagged = _names(pen, boxes, drawn)
    _outlines(pen)
    if f.region is not None:
        _stubs(pen, stubs, tagged)
        pen.d.rectangle([0, 0, W, style.title_px - 1], fill="white")  # shapes cut by the region stop below the title
        _title(pen, title)
        pen.d.line([(0, style.title_px - 1), (W, style.title_px - 1)], fill=FADED_LINE)
    buf = io.BytesIO()
    img.save(buf, "PNG", compress_level=6)
    return buf.getvalue()


Box = tuple[Node, tuple[float, float], tuple[float, float]]


def _title(pen: _Pen, title: str) -> None:
    pen.d.text((MARGIN, 2), _fit(pen.d, title, pen.font, pen.W - 2 * MARGIN), fill="black", font=pen.font)


def _shapes(pen: _Pen, g: DiagramGraph) -> list[Box]:
    """Each shape's outline, outer before inner; their corners, for the names drawn last."""
    boxes = []
    for n in drawing_order(g):
        x, y, rw, rh = n.view.rect  # type: ignore[misc]
        a, c = pen.P(x, y), pen.P(x + rw, y + rh)
        c = (max(c[0], a[0] + 3), max(c[1], a[1] + 3))
        ink, fill = (INK if pen.lit(n) else FADED), pen.frame.fills.get(n.num, "white")
        if n.view.cls in ROUND:
            pen.d.ellipse([a, c], outline=ink, fill=fill, width=1)
        elif n.view.cls == "Bar":  # fork and join bars
            pen.d.rectangle([a, c], fill="black" if pen.lit(n) else FADED)
        else:
            pen.d.rectangle([a, c], outline=ink, fill=fill, width=1)
        boxes.append((n, a, c))
    return boxes


def _trees(pen: _Pen, g: DiagramGraph) -> None:
    """A tree's bars, and a head at the base when every member points there; the members keep their
    own heads too, at the bar: the model reads directions better so than from one head (plan SK)."""
    for t in g.trees:
        shown = pen.lit(t.parent) or any(pen.lit(g.node(m.source)) or pen.lit(g.node(m.target)) for m in t.members)
        kinds = {m.view.cls for m in t.members}
        for a, b in (t.vertical, t.horizontal):
            _polyline(pen.d, [pen.P(*a), pen.P(*b)], dashed=bool(kinds & DASHED), fill=pen.line(shown),
                      width=pen.style.line_px)
        if t.to_parent:
            _arrowhead(pen.d, pen.P(*t.vertical[1]), pen.P(*t.vertical[0]), hollow=bool(kinds & HOLLOW),
                       fill=pen.head(shown), size=pen.style.arrow_px, stroke=pen.style.head_stroke)


def _links(pen: _Pen, g: DiagramGraph) -> list[tuple[int, tuple[float, float]]]:
    """Each connection: its line, its head, and an arrow halfway along a flow; returns, for a
    frame's region, where connections leave the picture, with their far shapes' numbers."""
    stubs = []
    region = pen.frame.region is not None
    for lk in g.links:
        if len(lk.view.points) < 2:
            continue
        pts = [pen.P(*p) for p in lk.view.points]
        s, t = g.node(lk.source), g.node(lk.target)
        shown = pen.lit(s) or pen.lit(t)
        dashed = lk.view.cls in DASHED
        for seg in (lk.view, *lk.more):
            if len(seg.points) >= 2:
                _polyline(pen.d, pts if seg is lk.view else [pen.P(*p) for p in seg.points], dashed=dashed,
                          fill=pen.line(shown), width=pen.style.line_px)
        if lk.directed:
            prev, tip = head_end(lk, pts)
            _arrowhead(pen.d, prev, tip, hollow=lk.view.cls in HOLLOW, fill=pen.head(shown),
                       size=pen.style.arrow_px, stroke=pen.style.head_stroke)
        along = flow_along(lk)
        if along is not None:  # all items flow one way: show it halfway along
            pen.d.polygon(mid_arrow(pts, along, pen.style.arrow_px / 10), fill=pen.head(shown))
        if region and shown and not (pen.lit(s) and pen.lit(t)):
            far = t if pen.lit(s) else s
            far_first = (far is t) == lk.target_at_first_point  # the far end is at the first point
            out = _leaving(pts[::-1] if far_first else pts, (0, pen.style.title_px, pen.W, pen.H))
            if far is not None and out is not None:
                stubs.append((far.num, out))
    return stubs


def _connectors_and_pins(pen: _Pen, g: DiagramGraph) -> None:
    """Small circles where a flow's segments break off, with where they go; pins and ports as dots
    on their owner's border."""
    for v, label in g.connectors:
        if v.rect:
            x, y, rw, rh = v.rect
            cx, cy = pen.P(x + rw / 2, y + rh / 2)
            r = max(3.0, min(rw, rh) * pen.scale / 2)
            pen.d.ellipse([cx - r, cy - r, cx + r, cy + r], outline=INK, fill="white")
            pen.d.text((cx + r + 2, cy - pen.style.font_px / 2 - 1), label, fill="black", font=pen.font)
    for v in g.pin_views:
        if v.rect:
            x, y, rw, rh = v.rect
            cx, cy = pen.P(x + rw / 2, y + rh / 2)
            pen.d.ellipse([cx - 2.5, cy - 2.5, cx + 2.5, cy + 2.5], fill=INK if pen.lit(g.node(v)) else FADED)


def _names(pen: _Pen, boxes: list[Box], drawn: dict[int, str] | None) -> set[int]:
    """Each shape's number tag and name, last, so that no line crosses them; returns the faded
    shapes whose numbers were drawn."""
    d, f, font, font_px, W, H, title_px = pen.d, pen.frame, pen.font, pen.style.font_px, pen.W, pen.H, pen.style.title_px
    tagged: set[int] = set()
    for n, a, c in boxes:
        if not pen.lit(n) and (n.num not in f.tagged or c[0] <= 0 or a[0] >= W or c[1] <= title_px or a[1] >= H):
            continue  # context only, or out of the picture (then marked where its connections leave)
        text_fill = "black" if pen.lit(n) else FADED_TEXT
        if not pen.lit(n):  # a boundary shape cut by the picture's edge keeps its number in view
            a = (min(max(a[0], 0), W - 40), min(max(a[1], title_px), H - font_px - 4))
            tagged.add(n.num)
        tw = 0.0
        if f.tags or not pen.lit(n):
            tag = str(n.num)
            tw = d.textlength(tag, font=font)
            d.rectangle([a[0] + 1, a[1] + 1, a[0] + tw + 5, a[1] + font_px + 3], fill="#e4e4e4" if pen.lit(n) else FADED_TAG)
            d.text((a[0] + 3, a[1] + 1), tag, fill=text_fill, font=font)
        room = c[0] - a[0] - tw - 10
        name = n.shown or n.view.text or ""
        text = _fit(d, name, font, room) if room > 4 * font_px * 0.5 and c[1] - a[1] >= font_px + 2 and name else ""
        if text:
            d.text((a[0] + tw + 8, a[1] + 1), text, fill=text_fill, font=font)
        if drawn is not None and pen.lit(n):
            drawn[n.num] = text
    return tagged


def _outlines(pen: _Pen) -> None:
    """An overview's modules: each outlined in its colour, its label outside the outline's top left
    corner, so that it hides no shape's number (there is room above the drawing)."""
    big = ImageFont.load_default(size=pen.style.font_px + 4)
    for label, (bx0, by0, bx1, by1), colour in pen.frame.outlines:
        a, c = pen.P(bx0, by0), pen.P(bx1, by1)
        pen.d.rectangle([a[0] - 3, a[1] - 3, c[0] + 3, c[1] + 3], outline=colour, width=2)
        lw, lh = pen.d.textlength(label, font=big) + 8, pen.style.font_px + 9
        top = max(pen.style.title_px, a[1] - 3 - lh)
        pen.d.rectangle([a[0] - 3, top, a[0] - 3 + lw, top + lh], fill=colour)
        pen.d.text((a[0] + 1, top + 1), label, fill="white", font=big)


def _stubs(pen: _Pen, stubs: list[tuple[int, tuple[float, float]]], tagged: set[int]) -> None:
    """In a frame's region: the number of each far shape where its connections leave the picture,
    once, unless the shape's own number is already in view."""
    d, font, font_px = pen.d, pen.font, pen.style.font_px
    seen = tagged
    for num, (px, py) in stubs:
        if num in seen:
            continue
        seen.add(num)
        tag = str(num)
        tw = d.textlength(tag, font=font)
        px = min(max(px - tw / 2 - 2, 1), pen.W - tw - 6)
        py = min(max(py - font_px / 2 - 1, pen.style.title_px + 1), pen.H - font_px - 4)
        d.rectangle([px, py, px + tw + 4, py + font_px + 2], fill=FADED_TAG, outline=FADED)
        d.text((px + 2, py), tag, fill=FADED_TEXT, font=font)


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


def _polyline(d: ImageDraw.ImageDraw, pts: list[tuple[float, float]], dashed: bool, fill: str | None = None,
              width: int = 1) -> None:
    if not dashed:
        d.line(pts, fill=fill or "black", width=width)
        return
    for p, q in itertools.pairwise(pts):
        length = math.dist(p, q)
        steps = max(1, int(length // 5))
        for i in range(0, steps, 2):  # 5 px dashes, 5 px gaps
            t0, t1 = i / steps, min(1.0, (i + 1) / steps)
            d.line([(p[0] + (q[0] - p[0]) * t0, p[1] + (q[1] - p[1]) * t0),
                    (p[0] + (q[0] - p[0]) * t1, p[1] + (q[1] - p[1]) * t1)], fill=fill or "#333333", width=width)


def _arrowhead(d: ImageDraw.ImageDraw, p: tuple[float, float], q: tuple[float, float], hollow: bool,
               fill: str = "black", size: float = 10, stroke: int = 2) -> None:
    """An arrowhead at `q`, pointing away from `p`: a hollow triangle for generalization and
    realization, an open arrow otherwise."""
    left, right = head_legs(p, q, size)
    if hollow:
        d.polygon([q, left, right], outline=fill, fill="white")
    else:
        d.line([left, q, right], fill=fill, width=stroke)


# -- a large diagram's views (plan DV) -------------------------------------------------------------
def colour(num: int, light: bool) -> str:
    """Module `num`'s colour: a pale fill, or a dark outline. Hues step by the golden ratio,
    so neighbouring numbers differ."""
    r, g, b = colorsys.hsv_to_rgb((num * 0.618034) % 1.0, 0.22 if light else 0.75, 1.0 if light else 0.6)
    return f"#{int(r * 255):02x}{int(g * 255):02x}{int(b * 255):02x}"


def overview_png(part: Partition, title: str, pixels: int = IMAGE_PIXELS,
                 style: SketchStyle = STYLE) -> bytes | None:
    """The whole diagram, each module's shapes tinted and outlined with its number (M1...)."""
    frame = Frame(fills={k: colour(m, True) for k, m in part.module_of.items()},
                  outlines=[(f"M{m.num}", m.box, colour(m.num, False)) for m in part.modules])
    return render_png(part.graph, f"{title}: {len(part.modules)} modules", pixels, frame, style)


def module_png(part: Partition, num: int, title: str, pixels: int = IMAGE_PIXELS,
               style: SketchStyle = STYLE, drawn: dict[int, str] | None = None) -> bytes | None:
    """Module `num` drawn on its own: its shapes numbered as in the diagram's legend, the
    rest of the diagram faded, and shapes of other modules it connects to keeping their
    numbers (at the picture's edge when they lie outside it)."""
    m = part.modules[num - 1]
    x0, y0, x1, y1 = m.box
    pad = max(20.0, 0.04 * max(x1 - x0, y1 - y0))
    frame = Frame(region=(x0 - pad, y0 - pad, x1 + pad, y1 + pad), focus=set(m.shapes), tagged=set(m.boundary))
    return render_png(part.graph, f"{title}: module M{num} of {len(part.modules)}", pixels, frame, style, drawn)

