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
from .diagram_graph import DiagramGraph, Node
from .layout import View
from .model import ModelIndex
from .partition import Partition
from .text import one_line
from .vision import patch_sides

MAX_ZOOM = 2.0  # small diagrams are not blown up further than this
MARGIN = 8


@dataclass(frozen=True)
class SketchStyle:
    """Sizes a sketch is drawn with, in the image's pixels: found by hand for gemma-4 on
    DeepInfra (FU-012, FU-015), and calibrated for another model by `calibrate-vision` (plan VC)."""

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
FONT_PX, TITLE_PX = STYLE.font_px, STYLE.title_px
DASHED = {"Dependency", "Abstraction", "Realization", "Usage", "Include", "Extend", "InterfaceRealization"}
HOLLOW = {"Generalization", "Realization", "InterfaceRealization"}
ROUND = {"UseCase", "InitialNode", "ActivityFinalNode", "FlowFinalNode", "PseudoNode"}


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


def render_png(ix: ModelIndex, g: DiagramGraph, title: str, pixels: int = IMAGE_PIXELS,
               frame: Frame | None = None, style: SketchStyle = STYLE) -> bytes | None:
    """A sketch that fills the model's pixel budget (FU-015): shapes tagged with their legend
    numbers, connections with arrowheads at the target, pins as dots (FU-007, FU-008).

    With a `frame`, only its region is drawn, around the shapes in focus: other shapes are
    faded, and a connection leaving the picture ends in its far shape's number."""
    f = frame or Frame()
    FONT_PX, TITLE_PX = style.font_px, style.title_px  # the module's names, for this style
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
    W, H, scale = canvas(w, h, pixels, TITLE_PX)
    if f.outlines:  # room above the drawing for module labels
        pad = (FONT_PX + 16) / scale
        y0, h = y0 - pad, h + pad
        W, H, scale = canvas(w, h, pixels, TITLE_PX)
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
        _polyline(d, pts, dashed=lk.view.cls in DASHED, fill=None if shown else FADED_LINE, width=style.line_px)
        for seg in lk.more:
            if len(seg.points) >= 2:
                _polyline(d, [P(*p) for p in seg.points], dashed=lk.view.cls in DASHED,
                          fill=None if shown else FADED_LINE, width=style.line_px)
        if lk.directed:
            tip, prev = (pts[0], pts[1]) if lk.target_at_first_point else (pts[-1], pts[-2])
            _arrowhead(d, prev, tip, hollow=lk.view.cls in HOLLOW, fill="black" if shown else FADED_LINE,
                       size=style.arrow_px, stroke=style.head_stroke)
        dirs = {i[-1:] for i in lk.items}  # "→" source to target, "←" target to source
        if dirs in ({"→"}, {"←"}):  # all items flow one way: show it halfway along
            # The points run from the path's first end to its second.
            _mid_arrow(d, pts, along=(dirs == {"→"}) != lk.target_at_first_point,
                       fill="black" if shown else FADED_LINE, scale=style.arrow_px / 10)
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
        name = n.shown or n.view.text or ""
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
    ang = math.atan2(q[1] - p[1], q[0] - p[0])
    left = (q[0] - size * math.cos(ang - 0.45), q[1] - size * math.sin(ang - 0.45))
    right = (q[0] - size * math.cos(ang + 0.45), q[1] - size * math.sin(ang + 0.45))
    if hollow:
        d.polygon([q, left, right], outline=fill, fill="white")
    else:
        d.line([left, q, right], fill=fill, width=stroke)


def _mid_arrow(d: ImageDraw.ImageDraw, pts: list[tuple[float, float]], along: bool, fill: str = "black",
               scale: float = 1.0) -> None:
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
    tip = (m[0] + 6 * scale * math.cos(ang), m[1] + 6 * scale * math.sin(ang))
    left = (m[0] - 4 * scale * math.cos(ang - 1.2), m[1] - 4 * scale * math.sin(ang - 1.2))
    right = (m[0] - 4 * scale * math.cos(ang + 1.2), m[1] - 4 * scale * math.sin(ang + 1.2))
    d.polygon([tip, left, right], fill=fill)


# -- a large diagram's views (plan DV) -------------------------------------------------------------
def colour(num: int, light: bool) -> str:
    """Module `num`'s colour: a pale fill, or a dark outline. Hues step by the golden ratio,
    so neighbouring numbers differ."""
    r, g, b = colorsys.hsv_to_rgb((num * 0.618034) % 1.0, 0.22 if light else 0.75, 1.0 if light else 0.6)
    return f"#{int(r * 255):02x}{int(g * 255):02x}{int(b * 255):02x}"


def overview_png(ix: ModelIndex, part: Partition, title: str, pixels: int = IMAGE_PIXELS,
                 style: SketchStyle = STYLE) -> bytes | None:
    """The whole diagram, each module's shapes tinted and outlined with its number (M1...)."""
    frame = Frame(fills={k: colour(m, True) for k, m in part.module_of.items()},
                  outlines=[(f"M{m.num}", m.box, colour(m.num, False)) for m in part.modules])
    return render_png(ix, part.graph, f"{title}: {len(part.modules)} modules", pixels, frame, style)


def module_png(ix: ModelIndex, part: Partition, num: int, title: str, pixels: int = IMAGE_PIXELS,
               style: SketchStyle = STYLE) -> bytes | None:
    """Module `num` drawn on its own: its shapes numbered as in the diagram's legend, the
    rest of the diagram faded, and shapes of other modules it connects to keeping their
    numbers (at the picture's edge when they lie outside it)."""
    m = part.modules[num - 1]
    x0, y0, x1, y1 = m.box
    pad = max(20.0, 0.04 * max(x1 - x0, y1 - y0))
    frame = Frame(region=(x0 - pad, y0 - pad, x1 + pad, y1 + pad), focus=set(m.shapes), tagged=set(m.boundary))
    return render_png(ix, part.graph, f"{title}: module M{num} of {len(part.modules)}", pixels, frame, style)

