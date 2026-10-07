"""Versions of fictional projects (plan SB): models that share most of their element ids, as a
later save, a fork and an unchanged copy do. Kept out of `PROJECTS`, so the fiction and its
questions, and the retrieval baselines built on them, don't change.

Each version is its base project, built again, then changed as a later save would change it:
elements and a diagram added, elements renamed and moved, every existing id kept. `VERSIONS`
maps a name to (the base's prefix, the builder); `shared` says how much of each id set the two
share.
"""

from __future__ import annotations

import re
from collections.abc import Callable
from xml.sax.saxutils import quoteattr

from . import kiosk, orchard, traffic
from .builder import Project

ADDED_BLOCK = [("Rated Power", None, "120 W"), ("Mass", None, "2.4 kg"), ("Service Interval", None, "6 months")]


def _rename(p: Project, key: str, new: str) -> None:
    node = p.nodes[key]
    old = quoteattr(p.names[key])
    if f"name={old}" not in node.head:
        raise ValueError(f"{p.prefix}: no name to rename on {key!r}")
    node.head = node.head.replace(f"name={old}", f"name={quoteattr(new)}", 1)
    p.names[key] = new


def _move(p: Project, key: str, to: str) -> None:
    owner = p.nodes[p._owner_package(key)]
    owner.children.remove(p.nodes[key])
    p.nodes[to].children.append(p.nodes[key])


def _blocks(p: Project) -> list[str]:
    return [k for k, kind in p.kinds.items() if kind == "Class" and k in p.parts and not k.startswith("v_")]


def _add_package(p: Project, key: str, name: str, blocks: int, doc: str, near: list[str]) -> list[str]:
    """A package of `blocks` new blocks, and a diagram of them with `near` (existing blocks)."""
    p.package(key, name, doc=doc)
    added = []
    for i in range(1, blocks + 1):
        b = p.block(f"v_{key}_{i}", f"{name.split()[-1]} Unit {i}", key, f"Added in this version: unit {i} of {name}.",
                    values=ADDED_BLOCK)
        added.append(b)
    p.diagram(f"v_{key}_d", f"{name} Overview", "SysML Block Definition Diagram", key, added + near, cols=4)
    return added


def kestrel_later() -> Project:
    """A later save of Kestrel Orchard Irrigation: a phase-2 package and its diagram, three blocks
    renamed and one moved (about 90% of ids shared: the model is small)."""
    p = orchard.build()
    p.folder, p.saved = "versions/kestrel-2026-03", (2026, 3, 2, 9, 30, 0)
    blocks = _blocks(p)
    _add_package(p, "v_phase2", "Phase 2 Frost Protection", 1, "Frost protection added for the second season.",
                 blocks[:2])
    for k in blocks[2:5]:
        _rename(p, k, p.names[k] + " (rev B)")
    _move(p, blocks[5], "v_phase2")
    return p


def port_calder_fork() -> Project:
    """A fork of the Port Calder traffic signals, taken over by another city: a large package of
    its own, and a fifth of the blocks renamed (about 60% of ids shared)."""
    p = traffic.build()
    p.folder, p.file_name, p.saved = "versions/fork", "Eastport_Traffic_Signals.mdzip", (2026, 4, 15, 14, 0, 0)
    base = len(ids(p))
    blocks = _blocks(p)
    n = 0
    while len(ids(p)) < base / 0.6:
        n += 1
        _add_package(p, f"v_east{n}", f"Eastport District {n}", 6, f"Eastport's own district {n} signal plan.",
                     blocks[:1])
    for k in blocks[1::5]:
        _rename(p, k, "Eastport " + p.names[k])
    return p


def ashgrove_copy() -> Project:
    """The Ashgrove kiosk saved again, unchanged, in another folder (every id shared)."""
    p = kiosk.build()
    p.folder, p.saved = "versions/copy", (2026, 2, 1, 8, 0, 0)
    return p


VERSIONS: dict[str, tuple[str, Callable[[], Project]]] = {
    "kestrel-later": ("kois", kestrel_later), "port-calder-fork": ("pct", port_calder_fork),
    "ashgrove-copy": ("abk", ashgrove_copy)}


def ids(p: Project) -> set[str]:
    return set(re.findall(r"xmi:id='([^']+)'", p.xmi()))


def shared(a: Project, b: Project) -> tuple[float, float]:
    """The share of a's ids that b has, and of b's that a has."""
    x, y = ids(a), ids(b)
    return len(x & y) / len(x), len(x & y) / len(y)
