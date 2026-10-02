"""Large diagrams split into modules, and the views drawn of them (plan DV)."""

import io

from PIL import Image

from cameo_ingest import diagrams as dg
from cameo_ingest import modules as mod
from cameo_ingest.config import MODULES
from cameo_ingest.layout import View
from cameo_ingest.model import ModelIndex


def graph(rects: list[tuple[float, float, float, float]], links: list[tuple[int, int]],
          parents: dict[int, int] | None = None) -> dg.DiagramGraph:
    """Shapes numbered from 1 with the given rectangles, and directed links between them."""
    g = dg.DiagramGraph()
    for i, r in enumerate(rects, 1):
        up = (parents or {}).get(i)
        node = dg.Node(i, View(f"v{i}", "Action", None, rect=r, text=f"shape {i}"), f"shape {i}",
                       1 if up else 0, up)
        g.nodes.append(node)
        g.node_of[f"v{i}"] = node
    for a, b in links:
        ra, rb = rects[a - 1], rects[b - 1]
        pts = [(ra[0] + ra[2] / 2, ra[1] + ra[3] / 2), (rb[0] + rb[2] / 2, rb[1] + rb[3] / 2)]
        g.links.append(dg.Link(View(f"l{a}-{b}", "ControlFlow", None, points=pts), g.nodes[a - 1].view,
                               g.nodes[b - 1].view, True, "", "", [], False))
    return g


def chain(n: int, x0: float, y0: float = 0) -> list[tuple[float, float, float, float]]:
    """`n` shapes in rows of 5, 150 apart."""
    return [(x0 + 150 * (i % 5), y0 + 100 * (i // 5), 100, 40) for i in range(n)]


def two_clusters() -> dg.DiagramGraph:
    rects = chain(15, 0) + chain(15, 3000)
    links = [(i, i + 1) for i in range(1, 15)] + [(i, i + 1) for i in range(16, 30)] + [(15, 16)]
    return graph(rects, links)


def test_small_diagrams_are_not_split():
    assert mod.partition(graph(chain(25, 0), [(i, i + 1) for i in range(1, 25)])) is None


def test_clusters_become_modules():
    g = two_clusters()
    part = mod.partition(g)
    assert part is not None
    assert [m.shapes for m in part.modules] == [list(range(1, 16)), list(range(16, 31))]  # left one first
    assert [m.num for m in part.modules] == [1, 2]
    assert part.modules[0].boundary == [16] and part.modules[1].boundary == [15]
    assert [(lk.source.view_id, lk.target.view_id) for lk in part.crossing(g)] == [("v15", "v16")]
    inside, edge = part.links(g, 1)
    assert len(inside) == 14 and len(edge) == 1
    assert part.modules[0].box == (0, 0, 700, 240)
    again = mod.partition(two_clusters())
    assert again is not None and [m.shapes for m in again.modules] == [m.shapes for m in part.modules]


def test_every_shape_in_one_bounded_module():
    """Unconnected shapes (as on SAF's content diagrams) are grouped by where they sit."""
    rects = [(160 * (i % 9), 120 * (i // 9), 120, 60) for i in range(43)]
    part = mod.partition(graph(rects, []))
    assert part is not None
    shapes = [k for m in part.modules for k in m.shapes]
    assert sorted(shapes) == list(range(1, 44))
    assert all(MODULES[1] <= len(m.shapes) <= MODULES[2] for m in part.modules)
    assert set(part.module_of) == set(range(1, 44))


def test_containers_do_not_widen_crops():
    """A frame around shapes of several modules stays in one module, but that module's
    crop covers only its own shapes."""
    rects = [(-50, -50, 3900, 400), *chain(15, 0), *chain(15, 3000)]
    links = [(i, i + 1) for i in range(2, 16)] + [(i, i + 1) for i in range(17, 31)] + [(16, 17)]
    part = mod.partition(graph(rects, links, {i: 1 for i in range(2, 32)}))
    assert part is not None and len(part.modules) == 2
    assert all(m.box[2] - m.box[0] < 1000 for m in part.modules)
    assert sum(1 in m.shapes for m in part.modules) == 1


def test_module_and_overview_views():
    g = two_clusters()
    part = mod.partition(g)
    assert part is not None
    ix = ModelIndex()
    for png, mode in ((mod.overview_png(ix, g, part, "Activity: big"), "RGB"),
                      (mod.module_png(ix, g, part, 1, "Activity: big"), "L")):
        assert png is not None
        with Image.open(io.BytesIO(png)) as img:
            w, h = img.size
            assert img.mode == mode and w * h <= dg.IMAGE_PIXELS and w % 48 == 0 and h % 48 == 0
    # The crop is of module 1 alone, drawn larger than in the whole sketch.
    whole = dg.render_png(ix, g, "whole")
    assert whole is not None
    with Image.open(io.BytesIO(whole)) as a, Image.open(io.BytesIO(mod.module_png(ix, g, part, 1, "t") or b"")) as b:
        assert b.size[0] / 700 > a.size[0] / 3700


def test_leaving_a_box():
    box = (0, 0, 100, 100)
    assert dg._leaving([(50, 50), (150, 50)], box) == (100, 50)
    assert dg._leaving([(50, 50), (50, -50)], box) == (50, 0)
    assert dg._leaving([(50, 50), (60, 60)], box) is None
    assert dg._leaving([(50, 50), (60, 50), (60, 200)], box) == (60, 100)
