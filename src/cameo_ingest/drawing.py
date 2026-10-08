"""What the sketches draw, apart from how (review CQ-013): the kinds of line and shape, the
conventions a sketch uses, a drawing's extent, and the geometry of arrowheads and of the arrow
halfway along a flow. `sketch` draws them with Pillow for the vision model, `sketch_svg` as SVG
for people; each keeps its own sizes and colours.
"""

from __future__ import annotations

import itertools
import math

from .diagram_graph import DiagramGraph, Link, Node

Point = tuple[float, float]

DASHED = {"Dependency", "Abstraction", "Realization", "Usage", "Include", "Extend", "InterfaceRealization",
          "LinkAttribute"}  # the last: an association to its class, as UML draws it (plan SK)
HOLLOW = {"Generalization", "Realization", "InterfaceRealization"}
ROUND = {"UseCase", "InitialNode", "ActivityFinalNode", "FlowFinalNode", "PseudoNode"}
SEQUENCE = {"SequenceLifeline", "LifeLineLine", "Activation"}


def conventions(g: DiagramGraph, focus: set[int] | None = None) -> set[str]:
    """The drawing conventions a sketch of `g` uses (around the shapes in `focus`, for a module's
    view), named as `prompts.GUIDE`'s sentences are, so that a request explains only those (plan SK)."""
    def seen(n: Node | None) -> bool:
        return n is not None and (focus is None or n.num in focus)

    nodes = [n for n in g.nodes if seen(n)]
    links = [lk for lk in g.links if seen(g.node(lk.source)) or seen(g.node(lk.target))]
    found = {"tags"} if nodes else set()
    if any(n.parent is not None for n in nodes):
        found.add("nesting")
    classes = {n.view.cls for n in nodes}
    if "RectangularShape" in classes:
        found.add("frames")
    if "Bar" in classes:
        found.add("bars")
    if classes & SEQUENCE:
        found.add("sequence")
    kinds = {lk.view.cls for lk in links}
    if kinds - {"LinkAttribute"}:
        found.add("open")
    if any(lk.directed and lk.view.cls in HOLLOW for lk in links):
        found.add("hollow")
    if kinds & DASHED - {"LinkAttribute"}:
        found.add("dashed")
    if "LinkAttribute" in kinds:
        found.add("association-class")
    for t in g.trees:
        if any(m in links for m in t.members):
            found.add("tree" if t.to_parent else "containment" if any(m.view.cls == "ContainmentLink"
                                                                      for m in t.members) else "open")
    if any(seen(g.node(v)) for v in g.pin_views):
        found.add("pins")
    if any(flow_along(lk) is not None for lk in links):
        found.add("flows")
    if g.connectors:
        found.add("breaks")
    return found


def extent(g: DiagramGraph) -> tuple[float, float, float, float] | None:
    """The diagram's drawn extent, (x0, y0, x1, y1) in its own units: shapes, connections and
    trees' bars; None when it draws nothing."""
    xs: list[float] = []
    ys: list[float] = []
    for n in g.nodes:
        if n.view.rect:
            x, y, w, h = n.view.rect
            xs += [x, x + w]
            ys += [y, y + h]
    for pts in itertools.chain((lk.view.points for lk in g.links), ((*t.vertical, *t.horizontal) for t in g.trees)):
        for x, y in pts:
            xs.append(x)
            ys.append(y)
    return (min(xs), min(ys), max(xs), max(ys)) if xs else None


def head_end(lk: Link, pts: list[Point]) -> tuple[Point, Point]:
    """(the point before it, the tip): where a directed connection's arrowhead goes, its target's
    end of `pts`, the connection's points as drawn."""
    return (pts[1], pts[0]) if lk.target_at_first_point else (pts[-2], pts[-1])


def head_legs(p: Point, q: Point, size: float) -> tuple[Point, Point]:
    """An arrowhead's two legs, at `q`, pointing away from `p`."""
    ang = math.atan2(q[1] - p[1], q[0] - p[0])
    return ((q[0] - size * math.cos(ang - 0.45), q[1] - size * math.sin(ang - 0.45)),
            (q[0] - size * math.cos(ang + 0.45), q[1] - size * math.sin(ang + 0.45)))


def flow_along(lk: Link) -> bool | None:
    """Whether every item a connection conveys flows along its points' order (True) or against it
    (False); None when they don't all flow one way."""
    ways = {i.way for i in lk.items}
    if ways not in ({"→"}, {"←"}):
        return None
    return (ways == {"→"}) != lk.target_at_first_point  # the points run from the path's first end


def mid_arrow(pts: list[Point], along: bool, scale: float = 1.0) -> list[Point]:
    """A small triangle halfway along a polyline, pointing along its points' order or against it:
    (tip, left, right)."""
    lengths = [math.dist(p, q) for p, q in itertools.pairwise(pts)]
    half, i = sum(lengths) / 2, 0
    while i < len(lengths) - 1 and half > lengths[i]:
        half -= lengths[i]
        i += 1
    p, q = pts[i], pts[i + 1]
    t = half / lengths[i] if lengths[i] else 0.5
    m = (p[0] + (q[0] - p[0]) * t, p[1] + (q[1] - p[1]) * t)
    ang = math.atan2(q[1] - p[1], q[0] - p[0]) + (0 if along else math.pi)
    return [(m[0] + 6 * scale * math.cos(ang), m[1] + 6 * scale * math.sin(ang)),
            (m[0] - 4 * scale * math.cos(ang - 1.2), m[1] - 4 * scale * math.sin(ang - 1.2)),
            (m[0] - 4 * scale * math.cos(ang + 1.2), m[1] - 4 * scale * math.sin(ang + 1.2))]
