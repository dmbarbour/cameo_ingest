"""A diagram's graph as text: a legend of numbered shapes, and connections between those
numbers (FU-008). It is the authoritative description: the sketch is drawn from the same graph
but is not a faithful Cameo rendering."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

from . import semantics as sem
from .diagram_graph import DiagramGraph, Link, Node
from .layout import View
from .model import ModelIndex
from .partition import Partition
from .text import md_inline


@dataclass(frozen=True)
class Refs:
    """How `describe` refers to elements: `target(id)` is the link to an element's page, or None
    for no link (an element without a page, or text for an LLM request); `esc` escapes text for
    Markdown, or leaves it as it is. Deciding by the target, never by what a label looks like,
    keeps a label that starts with "[" from passing for a link (AR-002)."""

    target: Callable[[str], str | None] = lambda _id: None
    esc: Callable[[str], str] = lambda text: text


PLAIN = Refs()  # no links and no escapes: text for an LLM request (AR-002)


def markdown(target: Callable[[str], str | None]) -> Refs:
    """Links to pages, with labels escaped for Markdown."""
    return Refs(target, md_inline)


def describe(ix: ModelIndex, g: DiagramGraph, refs: Refs = PLAIN, nodes: list[Node] | None = None,
             links: list[Link] | None = None, where=None) -> tuple[list[str], list[str]]:
    """Bullet lines for (legend, connections). `refs` links shapes to element pages and escapes
    for Markdown; PLAIN gives the lists as in the LLM request. `nodes` and `links` narrow the
    lists (to a module), indenting from the shallowest shape; `where(node)` adds text after each
    shape, such as its module."""

    def ref(n: Node) -> str:
        v = n.view
        dest = refs.target(v.element) if v.element and v.element in ix.elements else None
        if dest is not None:  # blocks, requirements...: a link, with the stereotype
            st = sem.shown_stereotypes(ix, v.element)
            return (f"«{st[0]}» " if st else "") + f"[{refs.esc(sem.label(ix, v.element))}]({dest})"
        return refs.esc(n.label) or v.cls

    def end(view: View | None) -> str:
        node = g.node_of.get(view.view_id or "") if view is not None else None
        if node is None:
            return "(not shown)"
        pin = g.pins.get(view.view_id or "")
        return f"[{node.num}] {ref(node)}" + (f".{refs.esc(pin)}" if pin else "") + (where(node) if where else "")

    shapes = g.nodes if nodes is None else nodes
    top = min((n.depth for n in shapes), default=0)
    legend = [f"{'  ' * (n.depth - top)}- [{n.num}] {n.view.cls}: {ref(n)}{where(n) if where else ''}" for n in shapes]
    lines = []
    for lk in g.links if links is None else links:
        arrow = "→" if lk.directed else "—"
        detail = "; ".join(x for x in (refs.esc(lk.label), lk.verb,
                                       "carries " + ", ".join(refs.esc(i) for i in lk.items) if lk.items else "")
                           if x)
        lines.append(f"- {end(lk.source)} {arrow}[{lk.view.cls}{': ' + detail if detail else ''}]{arrow} "
                     f"{end(lk.target)}")
    return legend, lines


def module_lists(ix: ModelIndex, part: Partition, num: int,
                 refs: Refs = PLAIN) -> tuple[list[str], list[str], list[str]]:
    """Module `num`'s (legend, connections within it, connections with other modules), as
    bullet lines; without links or escapes unless `refs` gives them. Shapes of other modules
    read '[n] label (in M<j>)'."""
    g = part.graph
    shapes = set(part.modules[num - 1].shapes)
    inside, edge = part.links(num)

    def where(n: Node) -> str:
        return "" if n.num in shapes else f" (in M{part.module_of[n.num]})"

    legend, lines = describe(ix, g, refs, nodes=[n for n in g.nodes if n.num in shapes], links=inside)
    _, boundary = describe(ix, g, refs, nodes=[], links=edge, where=where)
    return legend, lines, boundary


def crossing_lines(ix: ModelIndex, part: Partition, refs: Refs = PLAIN) -> list[str]:
    """Connections between modules, each end followed by '(in M<j>)'."""
    return describe(ix, part.graph, refs, nodes=[], links=part.crossing(),
                    where=lambda n: f" (in M{part.module_of[n.num]})")[1]
