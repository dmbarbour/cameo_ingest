"""Large diagrams split into modules that can each be drawn and read on their own (plan DV).

A diagram with more than `LARGE` shapes is split by Louvain community detection
(`networkx`) on its connections, weighted up for shapes that sit close together, with
nesting and each shape's two nearest neighbours as weak links, so that shapes with no
connections join what they sit next to. A module with more than `MAX_SHAPES` shapes is
split again, by communities or else by median cuts of the layout; one with fewer than
`MIN_SHAPES` joins the module it is most connected to, or else the nearest. The choice is
compared with alternatives in docs/research/diagram-partitioning-2026-09-30.md.

Every shape belongs to exactly one module. Shape numbers stay those of the whole diagram's
legend, so a module's shapes can be found in the diagram's sketch and text.
"""

from __future__ import annotations

import colorsys
import itertools
import math
import statistics
from collections import defaultdict
from dataclasses import dataclass

from . import diagrams as dg
from .diagrams import DiagramGraph, Link
from .model import ModelIndex

LARGE = 25  # split diagrams with more shapes than this
MIN_SHAPES = 6
MAX_SHAPES = 25
DEFAULTS = (LARGE, MIN_SHAPES, MAX_SHAPES)


def thresholds(spec: str | None) -> tuple[int, int, int]:
    """The --diagram-modules setting, 'N:MIN:MAX', as numbers; empty for the defaults. N = 0
    never splits. A lever for tuning and tests: the defaults should serve."""
    if not spec:
        return DEFAULTS
    try:
        large, lo, hi = (int(x) for x in spec.split(":"))
    except ValueError:
        raise ValueError(f"--diagram-modules expects N:MIN:MAX, such as 25:6:25, not {spec!r}") from None
    if large < 0 or not 1 <= lo <= hi or hi < 2:
        raise ValueError(f"--diagram-modules {spec}: needs N >= 0 and 1 <= MIN <= MAX, MAX >= 2")
    return large, lo, hi

Box = tuple[float, float, float, float]  # x0, y0, x1, y1 in diagram coordinates


@dataclass
class Module:
    num: int  # M1, M2... in reading order, top rows first
    shapes: list[int]  # shape numbers, as in the diagram's legend
    box: Box  # the region to draw: the module's shapes, less containers reaching into other modules
    boundary: list[int]  # shapes of other modules connected to this one


@dataclass
class Partition:
    modules: list[Module]
    module_of: dict[int, int]  # shape number -> module number

    def module_of_end(self, g: DiagramGraph, view) -> int | None:
        node = g.node_of.get(view.view_id or "") if view is not None else None
        return self.module_of.get(node.num) if node else None

    def links(self, g: DiagramGraph, k: int) -> tuple[list[Link], list[Link]]:
        """Module `k`'s (internal, boundary) connections."""
        inside, edge = [], []
        for lk in g.links:
            ends = {self.module_of_end(g, lk.source), self.module_of_end(g, lk.target)}
            if ends == {k}:
                inside.append(lk)
            elif k in ends:
                edge.append(lk)
        return inside, edge

    def crossing(self, g: DiagramGraph) -> list[Link]:
        """Connections between different modules."""
        out = []
        for lk in g.links:
            a, b = self.module_of_end(g, lk.source), self.module_of_end(g, lk.target)
            if a is not None and b is not None and a != b:
                out.append(lk)
        return out


class _Graph:
    """Things to group, as an undirected weighted graph: a diagram's shapes that have a
    rectangle, each of size 1 and placed at its centre."""

    def __init__(self, g: DiagramGraph):
        self.size: dict[int, float] = defaultdict(lambda: 1.0)
        self.nodes = [n.num for n in g.nodes if n.view.rect]
        keep = set(self.nodes)
        self.rect = {n.num: n.view.rect for n in g.nodes if n.num in keep}
        self.center = {k: (r[0] + r[2] / 2, r[1] + r[3] / 2) for k, r in self.rect.items()}  # type: ignore[index]
        self.parent = {n.num: n.parent for n in g.nodes if n.num in keep and n.parent in keep}
        self.edges: dict[tuple[int, int], float] = defaultdict(float)
        for lk in g.links:
            a = g.node_of.get(lk.source.view_id or "") if lk.source else None
            b = g.node_of.get(lk.target.view_id or "") if lk.target else None
            if a and b and a.num != b.num and a.num in keep and b.num in keep:
                self.edges[(min(a.num, b.num), max(a.num, b.num))] += 1.0

    def sub(self, members: set[int]) -> dict[tuple[int, int], float]:
        return {e: w for e, w in self.edges.items() if e[0] in members and e[1] in members}

    def total(self, members: set[int]) -> float:
        return sum(self.size[k] for k in members)

    def weights(self, members: set[int]) -> dict[tuple[int, int], float]:
        """Connections weighted up to 3 times for shapes close together; nesting, and each
        shape's 2 nearest neighbours, as weaker links."""
        ms = sorted(members)
        dists = [math.dist(self.center[a], self.center[b]) for a in ms for b in ms if a < b]
        scale = statistics.median(dists) if dists else 1.0
        w: dict[tuple[int, int], float] = defaultdict(float)
        for (a, b), v in self.sub(members).items():
            w[(a, b)] += v * (1 + 2 * math.exp(-math.dist(self.center[a], self.center[b]) / (0.3 * scale)))
        for c, p in self.parent.items():
            if c in members and p in members:
                w[(min(c, p), max(c, p))] += 1.0
        for a in ms:
            near = sorted((math.dist(self.center[a], self.center[b]), b) for b in ms if b != a)[:2]
            for _, b in near:
                w[(min(a, b), max(a, b))] += 0.3
        return w

    def communities(self, members: set[int]) -> list[set[int]]:
        import networkx as nx

        H = nx.Graph()
        H.add_nodes_from(sorted(members))
        for (a, b), v in sorted(self.weights(members).items()):
            H.add_edge(a, b, weight=v)
        return [set(c) for c in nx.community.louvain_communities(H, weight="weight", seed=1)]

    def cut(self, members: set[int], size: float) -> list[set[int]]:
        """Cuts along the longer side, halving the size, until every part is at most `size`
        (or a single node)."""
        if self.total(members) <= size or len(members) < 2:
            return [members]
        xs = [self.center[k][0] for k in members]
        ys = [self.center[k][1] for k in members]
        axis = 0 if max(xs) - min(xs) >= max(ys) - min(ys) else 1
        ordered = sorted(members, key=lambda k: (self.center[k][axis], k))
        whole, run, half = self.total(members), 0.0, len(ordered) - 1
        for i, k in enumerate(ordered[:-1]):  # the first cut that passes the middle
            run += self.size[k]
            if 2 * (run + self.size[ordered[i + 1]]) > whole:
                half = max(1, i + 1)
                break
        return self.cut(set(ordered[:half]), size) + self.cut(set(ordered[half:]), size)

    def bounded(self, lo: float, hi: float) -> list[set[int]]:
        todo: list[set[int]] = [set(self.nodes)]
        done: list[set[int]] = []
        first = True
        while todo:
            m = todo.pop()
            if self.total(m) <= hi and not first:
                done.append(m)
                continue
            parts = self.communities(m)
            first = False
            if len(parts) <= 1 and self.total(m) > hi:
                parts = self.cut(m, hi)
            if len(parts) <= 1:
                done.append(m)
            else:
                todo += sorted(parts, key=min)
        while len(done) > 1:
            done.sort(key=self.total)
            small = done[0]
            if self.total(small) >= lo:
                break

            def closeness(o: set[int], small: set[int] = small) -> tuple[float, float]:
                link = sum(w for (a, b), w in self.edges.items() if (a in small and b in o) or (b in small and a in o))
                return link, -min(math.dist(self.center[a], self.center[b]) for a in small for b in o)

            others = [o for o in done[1:] if self.total(o) + self.total(small) <= hi] or done[1:]
            max(others, key=closeness).update(small)
            done = done[1:]
        return done


class _Sequence(_Graph):
    """A package's sections in document order, sized in characters: order plays the part of
    a diagram's geometry, since modellers put related elements together."""

    def __init__(self, sizes: list[float], parents: list[int | None], links: list[tuple[int, int]]):
        n = len(sizes)
        self.nodes = list(range(n))
        self.size = dict(enumerate(sizes))
        self.center = {k: (float(k), 0.0) for k in self.nodes}
        self.parent = {k: p for k, p in enumerate(parents) if p is not None}
        self.edges = defaultdict(float)
        for a, b in links:
            if a != b:
                self.edges[(min(a, b), max(a, b))] += 1.0

    def weights(self, members: set[int]) -> dict[tuple[int, int], float]:
        """Relationships weighted up to 3 times for sections a few places apart; nesting, and
        each section's neighbours in order, as weaker links. Linear in the sections, where
        a diagram's all-pairs distances would not be."""
        w: dict[tuple[int, int], float] = defaultdict(float)
        for (a, b), v in self.sub(members).items():
            w[(a, b)] += v * (1 + 2 * math.exp(-(b - a) / 5))
        for c, p in self.parent.items():
            if c in members and p in members:
                w[(min(c, p), max(c, p))] += 1.0
        ordered = sorted(members)
        for a, b in itertools.pairwise(ordered):
            w[(a, b)] += 0.3
        return w


def sequence_partition(sizes: list[float], parents: list[int | None], links: list[tuple[int, int]],
                       lo: float, hi: float) -> list[list[int]]:
    """Groups of items (indices in document order) of `lo` to `hi` in total size where they can
    be: a package's sections, each sized by its text. Groups come in document order."""
    if sum(sizes) <= hi:
        return [list(range(len(sizes)))]
    groups = sorted((sorted(g) for g in _Sequence(sizes, parents, links).bounded(lo, hi)), key=lambda g: g[0])
    # Neighbouring groups that fit together are joined: communities of a list of unrelated
    # sections (such as requirements imported from DOORS) are arbitrary runs of it, and
    # fewer, fuller parts mean fewer requests and a shallower summary.
    packed = [groups[0]]
    for g in groups[1:]:
        if sum(sizes[i] for i in packed[-1]) + sum(sizes[i] for i in g) <= hi:
            packed[-1] = sorted(packed[-1] + g)
        else:
            packed.append(g)
    return packed


def partition(g: DiagramGraph, large: int = LARGE, lo: int = MIN_SHAPES, hi: int = MAX_SHAPES) -> Partition | None:
    """Modules of a diagram with more than `large` shapes; None for a smaller one, or when
    `large` is 0."""
    if not large or len(g.nodes) <= large:
        return None
    G = _Graph(g)
    if len(G.nodes) <= large:
        return None
    groups = G.bounded(lo, hi)
    of = {k: i for i, m in enumerate(groups) for k in m}
    # Shapes without a rectangle go with the shape they are nested in, or else with the module
    # they share most connections with, or else with the first.
    by_num = {n.num: n for n in g.nodes}
    for n in g.nodes:
        if n.num in of:
            continue
        up = n.parent
        while up is not None and up not in of:
            up = by_num[up].parent
        if up is None:
            votes: dict[int, int] = defaultdict(int)
            for lk in g.links:
                ends = [g.node_of.get(v.view_id or "") for v in (lk.source, lk.target) if v is not None]
                if any(e is n for e in ends):
                    for e in ends:
                        if e is not None and e.num in of:
                            votes[of[e.num]] += 1
            of[n.num] = max(votes, key=lambda i: (votes[i], -i)) if votes else 0
        else:
            of[n.num] = of[up]
        groups[of[n.num]].add(n.num)

    children: dict[int, list[int]] = defaultdict(list)
    for n in g.nodes:
        if n.parent is not None:
            children[n.parent].append(n.num)

    def inside(k: int, members: set[int]) -> bool:
        """`k` and every shape nested in it belong to `members`."""
        return all(c in members and inside(c, members) for c in children.get(k, []))

    boxes = []
    for m in groups:
        own = [k for k in m if k in G.rect and inside(k, m)] or [k for k in m if k in G.rect]
        rects = [G.rect[k] for k in own]
        boxes.append((min(r[0] for r in rects), min(r[1] for r in rects),  # type: ignore[index]
                      max(r[0] + r[2] for r in rects), max(r[1] + r[3] for r in rects)))  # type: ignore[index]
    # Reading order: rows of a third of the diagram's height, left to right within a row.
    top = min(b[1] for b in boxes)
    row = max(1.0, (max(b[3] for b in boxes) - top) / 3)
    order = sorted(range(len(groups)), key=lambda i: (int(((boxes[i][1] + boxes[i][3]) / 2 - top) // row),
                                                     (boxes[i][0] + boxes[i][2]) / 2, min(groups[i])))
    renum = {old: new + 1 for new, old in enumerate(order)}
    module_of = {k: renum[i] for k, i in of.items()}
    boundary: dict[int, set[int]] = defaultdict(set)
    for lk in g.links:
        a = g.node_of.get(lk.source.view_id or "") if lk.source else None
        b = g.node_of.get(lk.target.view_id or "") if lk.target else None
        if a and b and module_of[a.num] != module_of[b.num]:
            boundary[module_of[a.num]].add(b.num)
            boundary[module_of[b.num]].add(a.num)
    modules = [Module(renum[i], sorted(groups[i]), boxes[i], sorted(boundary[renum[i]])) for i in order]
    return Partition(modules, module_of)


# -- views ----------------------------------------------------------------------------------------
def colour(num: int, light: bool) -> str:
    """Module `num`'s colour: a pale fill, or a dark outline. Hues step by the golden ratio,
    so neighbouring numbers differ."""
    r, g, b = colorsys.hsv_to_rgb((num * 0.618034) % 1.0, 0.22 if light else 0.75, 1.0 if light else 0.6)
    return f"#{int(r * 255):02x}{int(g * 255):02x}{int(b * 255):02x}"


def overview_png(ix: ModelIndex, g: DiagramGraph, part: Partition, title: str,
                 pixels: int = dg.IMAGE_PIXELS) -> bytes | None:
    """The whole diagram, each module's shapes tinted and outlined with its number (M1...)."""
    frame = dg.Frame(fills={k: colour(m, True) for k, m in part.module_of.items()},
                     outlines=[(f"M{m.num}", m.box, colour(m.num, False)) for m in part.modules])
    return dg.render_png(ix, g, f"{title}: {len(part.modules)} modules", pixels, frame)


def module_png(ix: ModelIndex, g: DiagramGraph, part: Partition, num: int, title: str,
               pixels: int = dg.IMAGE_PIXELS) -> bytes | None:
    """Module `num` drawn on its own: its shapes numbered as in the diagram's legend, the
    rest of the diagram faded, and shapes of other modules it connects to keeping their
    numbers (at the picture's edge when they lie outside it)."""
    m = part.modules[num - 1]
    x0, y0, x1, y1 = m.box
    pad = max(20.0, 0.04 * max(x1 - x0, y1 - y0))
    frame = dg.Frame(region=(x0 - pad, y0 - pad, x1 + pad, y1 + pad), focus=set(m.shapes), tagged=set(m.boundary))
    return dg.render_png(ix, g, f"{title}: module M{num} of {len(part.modules)}", pixels, frame)


# -- text -----------------------------------------------------------------------------------------
def module_lists(ix: ModelIndex, g: DiagramGraph, part: Partition, num: int,
                 refs: dg.Refs = dg.PLAIN) -> tuple[list[str], list[str], list[str]]:
    """Module `num`'s (legend, connections within it, connections with other modules), as
    Markdown bullet lines; without links unless `refs` gives them. Shapes of other modules
    read '[n] label (in M<j>)'."""
    shapes = set(part.modules[num - 1].shapes)
    inside, edge = part.links(g, num)

    def where(n: dg.Node) -> str:
        return "" if n.num in shapes else f" (in M{part.module_of[n.num]})"

    legend, lines = dg.describe(ix, g, refs, nodes=[n for n in g.nodes if n.num in shapes], links=inside)
    _, boundary = dg.describe(ix, g, refs, nodes=[], links=edge, where=where)
    return legend, lines, boundary


def crossing_lines(ix: ModelIndex, g: DiagramGraph, part: Partition, refs: dg.Refs = dg.PLAIN) -> list[str]:
    """Connections between modules, each end followed by '(in M<j>)'."""
    return dg.describe(ix, g, refs, nodes=[], links=part.crossing(g),
                       where=lambda n: f" (in M{part.module_of[n.num]})")[1]


def module_values(ix: ModelIndex, g: DiagramGraph, part: Partition, num: int, diagram: str) -> dict[str, str]:
    """The text slots of a module-description request."""
    legend, lines, boundary = module_lists(ix, g, part, num)
    return {"DIAGRAM": diagram, "MODULE": f"M{num} of {len(part.modules)}", "LEGEND": "\n".join(legend),
            "CONNECTIONS": "\n".join(lines) or "(none)", "BOUNDARY": "\n".join(boundary) or "(none)"}


def synthesis_values(ix: ModelIndex, g: DiagramGraph, part: Partition, diagram: str,
                     texts: list[str | None]) -> dict[str, str]:
    """The text slots of a diagram-synthesis request, from the modules' descriptions."""
    modules = "\n\n".join(f"M{m.num} ({len(m.shapes)} shapes): {text or '(not described)'}"
                           for m, text in zip(part.modules, texts, strict=True))
    return {"DIAGRAM": diagram, "MODULES": modules,
            "CROSSING": "\n".join(crossing_lines(ix, g, part)) or "(none)"}
