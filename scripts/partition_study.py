#!/usr/bin/env python3
"""Compare ways of splitting large diagrams into modules (plan DV-02).

    uv run --with networkx --with igraph python scripts/partition_study.py samples/TMT.mdzip ... [--draw DIR]

Every diagram with more than --large shapes is split by each method into modules of
--min to --max shapes, using the same post-processing for all methods. A module that is too
large is split again, by the method or else spatially. One that is too small is merged into
the module it shares most connections with, or else the nearest. For each method, the script
reports modules per diagram, the share of shapes in modules within bounds, the share of
connections cut, modularity, the overlap of module bounding boxes (overlapping crops show
other modules' shapes), and time.
"""

from __future__ import annotations

import argparse
import colorsys
import math
import statistics
import time
from collections import defaultdict
from pathlib import Path

from cameo_ingest import diagrams as dg
from cameo_ingest import semantics as sem
from cameo_ingest.archive import discover
from cameo_ingest.pipeline import load_layouts, parse_project

Modules = list[set[int]]


class Graph:
    """A diagram as an undirected weighted graph of its shapes."""

    def __init__(self, g: dg.DiagramGraph):
        self.nodes = [n.num for n in g.nodes if n.view.rect]
        keep = set(self.nodes)
        self.rect = {n.num: n.view.rect for n in g.nodes if n.num in keep}
        self.center = {k: (r[0] + r[2] / 2, r[1] + r[3] / 2) for k, r in self.rect.items()}
        self.parent = {n.num: n.parent for n in g.nodes if n.num in keep and n.parent in keep}
        self.edges: dict[tuple[int, int], float] = defaultdict(float)
        for lk in g.links:
            a = g.node_of.get(lk.source.view_id or "") if lk.source else None
            b = g.node_of.get(lk.target.view_id or "") if lk.target else None
            if a and b and a.num != b.num and a.num in keep and b.num in keep:
                self.edges[(min(a.num, b.num), max(a.num, b.num))] += 1.0

    def sub(self, members: set[int]) -> dict[tuple[int, int], float]:
        return {e: w for e, w in self.edges.items() if e[0] in members and e[1] in members}


# -- methods: each returns modules for a set of shapes, before bounding ------------------------
def m_components(G: Graph, members: set[int]) -> Modules:
    """Connected components, with nesting counted as a connection."""
    up = {k: k for k in members}

    def find(k: int) -> int:
        while up[k] != k:
            up[k] = up[up[k]]
            k = up[k]
        return k

    pairs = list(G.sub(members)) + [(c, p) for c, p in G.parent.items() if c in members and p in members]
    for a, b in pairs:
        up[find(a)] = find(b)
    groups: dict[int, set[int]] = defaultdict(set)
    for k in members:
        groups[find(k)].add(k)
    return list(groups.values())


def kd_split(G: Graph, members: set[int], size: int) -> Modules:
    """Split along the longer side at the median until every part has at most `size` shapes:
    compact, non-overlapping regions that ignore connections."""
    if len(members) <= size:
        return [members]
    xs = [G.center[k][0] for k in members]
    ys = [G.center[k][1] for k in members]
    axis = 0 if max(xs) - min(xs) >= max(ys) - min(ys) else 1
    ordered = sorted(members, key=lambda k: G.center[k][axis])
    half = len(ordered) // 2
    return kd_split(G, set(ordered[:half]), size) + kd_split(G, set(ordered[half:]), size)


def m_spatial(G: Graph, members: set[int], size: int = 25) -> Modules:
    return kd_split(G, members, size)


def _nx(G: Graph, members: set[int], weights: dict | None = None):
    import networkx as nx

    H = nx.Graph()
    H.add_nodes_from(members)
    for (a, b), w in (weights or G.sub(members)).items():
        H.add_edge(a, b, weight=w)
    return nx, H


def m_nx_greedy(G: Graph, members: set[int]) -> Modules:
    nx, H = _nx(G, members)
    return [set(c) for c in nx.community.greedy_modularity_communities(H, weight="weight")]


def m_nx_louvain(G: Graph, members: set[int]) -> Modules:
    nx, H = _nx(G, members)
    return [set(c) for c in nx.community.louvain_communities(H, weight="weight", seed=1)]


def geo_weights(G: Graph, members: set[int]) -> dict[tuple[int, int], float]:
    """Connections weighted up for shapes close together; nesting and the 2 nearest
    neighbours linked weakly, so that unconnected shapes join what they sit next to."""
    ms = sorted(members)
    dists = [math.dist(G.center[a], G.center[b]) for a in ms for b in ms if a < b]
    scale = statistics.median(dists) if dists else 1.0
    w: dict[tuple[int, int], float] = defaultdict(float)
    for (a, b), v in G.sub(members).items():
        w[(a, b)] += v * (1 + 2 * math.exp(-math.dist(G.center[a], G.center[b]) / (0.3 * scale)))
    for c, p in G.parent.items():
        if c in members and p in members:
            w[(min(c, p), max(c, p))] += 1.0
    for a in ms:
        near = sorted((math.dist(G.center[a], G.center[b]), b) for b in ms if b != a)[:2]
        for _, b in near:
            w[(min(a, b), max(a, b))] += 0.3
    return w


def m_nx_louvain_geo(G: Graph, members: set[int]) -> Modules:
    nx, H = _nx(G, members, geo_weights(G, members))
    return [set(c) for c in nx.community.louvain_communities(H, weight="weight", seed=1)]


def m_ig_leiden(G: Graph, members: set[int]) -> Modules:
    import igraph as ig

    ms = sorted(members)
    index = {k: i for i, k in enumerate(ms)}
    sub = G.sub(members)
    H = ig.Graph(n=len(ms), edges=[(index[a], index[b]) for a, b in sub])
    part = H.community_leiden(objective_function="modularity", weights=list(sub.values()) or None, n_iterations=-1)
    return [{ms[i] for i in c} for c in part]


METHODS = {
    "components": m_components,
    "spatial": m_spatial,
    "nx_greedy": m_nx_greedy,
    "nx_louvain": m_nx_louvain,
    "nx_louvain_geo": m_nx_louvain_geo,
    "ig_leiden": m_ig_leiden,
}


# -- bounding and metrics ------------------------------------------------------------------------
def bound(G: Graph, method, lo: int, hi: int) -> Modules:
    todo, done = [set(G.nodes)], []
    first = True
    while todo:
        m = todo.pop()
        if len(m) <= hi and not first:
            done.append(m)
            continue
        parts = method(G, m) if method is not m_spatial else kd_split(G, m, hi)
        first = False
        if len(parts) <= 1 and len(m) > hi:
            parts = kd_split(G, m, hi)
        if len(parts) <= 1:
            done.append(m)
        else:
            todo += parts
    while len(done) > 1:
        done.sort(key=len)
        small = done[0]
        if len(small) >= lo:
            break
        def closeness(o: set[int], small: set[int] = small) -> tuple[float, float]:
            link = sum(w for (a, b), w in G.edges.items() if (a in small and b in o) or (b in small and a in o))
            return link, -min(math.dist(G.center[a], G.center[b]) for a in small for b in o)
        others = [o for o in done[1:] if len(o) + len(small) <= hi] or done[1:]
        best = max(others, key=closeness)
        best |= small
        done = done[1:]
    return done


def bbox(G: Graph, m: set[int]) -> tuple[float, float, float, float]:
    xs = [v for k in m for v in (G.rect[k][0], G.rect[k][0] + G.rect[k][2])]
    ys = [v for k in m for v in (G.rect[k][1], G.rect[k][1] + G.rect[k][3])]
    return min(xs), min(ys), max(xs), max(ys)


def metrics(G: Graph, mods: Modules, lo: int, hi: int) -> dict[str, float]:
    of = {k: i for i, m in enumerate(mods) for k in m}
    total = sum(G.edges.values())
    cut = sum(w for (a, b), w in G.edges.items() if of[a] != of[b])
    q = 0.0
    if total:
        deg: dict[int, float] = defaultdict(float)
        for (a, b), w in G.edges.items():
            deg[a] += w
            deg[b] += w
        for i, m in enumerate(mods):
            inside = sum(w for (a, b), w in G.edges.items() if of[a] == i and of[b] == i)
            q += inside / total - (sum(deg[k] for k in m) / (2 * total)) ** 2
    boxes = [bbox(G, m) for m in mods]
    X0, Y0, X1, Y1 = bbox(G, set(G.nodes))
    area = max(1.0, (X1 - X0) * (Y1 - Y0))
    overlap = 0.0
    for i in range(len(boxes)):
        for j in range(i + 1, len(boxes)):
            a, b = boxes[i], boxes[j]
            overlap += max(0.0, min(a[2], b[2]) - max(a[0], b[0])) * max(0.0, min(a[3], b[3]) - max(a[1], b[1]))
    return {"modules": len(mods), "in_bounds": sum(len(m) for m in mods if lo <= len(m) <= hi) / len(G.nodes),
            "cut": cut / total if total else 0.0, "modularity": q, "overlap": overlap / area}


def draw(G: Graph, mods: Modules, path: Path, title: str) -> None:
    from PIL import Image, ImageDraw, ImageFont

    X0, Y0, X1, Y1 = bbox(G, set(G.nodes))
    s = min(1400 / max(1.0, X1 - X0), 900 / max(1.0, Y1 - Y0))
    img = Image.new("RGB", (int((X1 - X0) * s) + 40, int((Y1 - Y0) * s) + 60), "white")
    d = ImageDraw.Draw(img)
    font = ImageFont.load_default(size=14)
    d.text((10, 5), title, fill="black", font=font)

    def P(x, y):
        return (x - X0) * s + 20, (y - Y0) * s + 40

    for (a, b) in G.edges:
        d.line([P(*G.center[a]), P(*G.center[b])], fill="#bbbbbb")
    for i, m in enumerate(mods):
        r, g, b = colorsys.hsv_to_rgb(i / max(1, len(mods)), 0.55, 0.95)
        color = (int(r * 255), int(g * 255), int(b * 255))
        for k in m:
            x, y, w, h = G.rect[k]
            d.rectangle([P(x, y), P(x + w, y + h)], fill=color, outline="black")
        bx = bbox(G, m)
        d.rectangle([P(bx[0], bx[1]), P(bx[2], bx[3])], outline=color, width=3)
        d.text(P(bx[0], bx[1]), f"M{i + 1}", fill="black", font=font)
    img.save(path)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("samples", nargs="+", type=Path)
    ap.add_argument("--large", type=int, default=25, help="split diagrams with more shapes than this")
    ap.add_argument("--min", type=int, default=6)
    ap.add_argument("--max", type=int, default=25)
    ap.add_argument("--draw", type=Path, help="draw the 3 largest diagrams' partitions, per method, into DIR")
    args = ap.parse_args()

    results: dict[str, list[dict[str, float]]] = defaultdict(list)
    drawn: list[tuple[int, str, Graph]] = []
    for sample in args.samples:
        for proj in discover(sample.read_bytes(), sample.name):
            ix = parse_project(proj)
            rels = {r.id: r for r in sem.relationships(ix)}
            flows = sem.item_flows(ix)
            for did, layout in load_layouts(proj, ix).items():
                G = Graph(dg.build(ix, layout, rels, flows))
                if len(G.nodes) <= args.large:
                    continue
                drawn.append((len(G.nodes), f"{sample.stem} {ix.diagrams[did].name}", G))
                for name, method in METHODS.items():
                    t0 = time.perf_counter()
                    mods = bound(G, method, args.min, args.max)
                    m = metrics(G, mods, args.min, args.max)
                    m["ms"] = (time.perf_counter() - t0) * 1000
                    m["edges"] = len(G.edges)
                    results[name].append(m)
    n = len(next(iter(results.values())))
    print(f"{n} diagrams with more than {args.large} shapes; modules bounded to {args.min}..{args.max} shapes\n")
    print("| method | modules per diagram | shapes in bounds | connections cut | modularity | box overlap | ms per diagram |")
    print("|---|---|---|---|---|---|---|")
    for name, rs in results.items():
        with_edges = [r for r in rs if r["edges"]]
        print(f"| {name} | {statistics.mean(r['modules'] for r in rs):.1f} | {statistics.mean(r['in_bounds'] for r in rs):.0%} "
              f"| {statistics.mean(r['cut'] for r in with_edges):.0%} | {statistics.mean(r['modularity'] for r in with_edges):.2f} "
              f"| {statistics.mean(r['overlap'] for r in rs):.0%} | {statistics.mean(r['ms'] for r in rs):.0f} |")
    if args.draw:
        args.draw.mkdir(parents=True, exist_ok=True)
        for size, title, G in sorted(drawn, key=lambda x: -x[0])[:3]:
            for name, method in METHODS.items():
                mods = bound(G, method, args.min, args.max)
                safe = "".join(c if c.isalnum() else "_" for c in title)[:60]
                draw(G, mods, args.draw / f"{safe}__{name}.png", f"{title} ({size} shapes): {name}, {len(mods)} modules")
        print(f"\ndrawings in {args.draw}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
