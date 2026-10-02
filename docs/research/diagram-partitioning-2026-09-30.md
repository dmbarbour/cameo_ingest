# Splitting large diagrams into modules

- **Date:** 2026-09-30
- **Asked by:** the maintainer, answering plan DV's question about `networkx`: "you could give it
  a try, perhaps contrast with some alternatives, see what works."
- **For:** plan step DV-02 in `docs/plans/diagram-views-2026-09-30.md`.
- **Method:** `scripts/partition_study.py` (retired; at tag `studies-2026-10-02`), run as
  `uv run --with networkx --with igraph python scripts/partition_study.py samples/Package_Delivery_Drone.mdzip samples/TMT.mdzip samples/SAF_FFDS.mdzip --draw DIR`.
  - **Diagrams:** the 57 with more than 25 shapes: 2 in the drone sample, 44 in TMT and 11 in
    SAF_FFDS. Most are activity diagrams, plus requirement, block, sequence and content
    diagrams. The largest has 140 shapes, and some SAF content diagrams have 43 shapes and no
    connections.
  - **The graph:** shapes are nodes, and connections join the shapes at their ends. Pins count
    as their owner.
  - **Bounds:** every method's modules are put through the same post-processing, to fit 6 to 25
    shapes. A module that is too large is split again, by the same method or else spatially. One
    that is too small is merged into the neighbour it shares most connections with, or else the
    nearest.

## Methods

| Method | What it does |
|---|---|
| `components` | Connected components, with nesting counted as a connection. |
| `spatial` | Recursive median cuts along the layout's longer side. Compact regions that ignore connections. |
| `nx_greedy` | `networkx` greedy modularity communities. |
| `nx_louvain` | `networkx` Louvain communities. |
| `nx_louvain_geo` | Louvain on weights that favour shapes close together. A connection counts up to 3 times as much when its shapes are near. Nesting adds a link, and each shape is weakly linked to its 2 nearest neighbours, so shapes with no connections join what they sit next to. |
| `ig_leiden` | `igraph`'s Leiden algorithm, optimizing modularity. |

## Results

| Method | Modules per diagram | Shapes in bounds | Connections cut | Modularity | Box overlap | ms per diagram |
|---|---|---|---|---|---|---|
| components | 2.5 | 93% | 18% | 0.30 | 15% | 0 |
| spatial | 2.5 | 100% | 25% | 0.29 | 15% | 0 |
| nx_greedy | 4.0 | 96% | 12% | 0.52 | 31% | 7 |
| nx_louvain | 4.0 | 96% | 12% | 0.52 | 36% | 2 |
| **nx_louvain_geo** | 4.1 | 98% | 16% | 0.50 | **18%** | 3 |
| ig_leiden | 4.0 | 96% | 12% | 0.52 | 34 to 35% | 1 |

**Box overlap** is the area where modules' bounding boxes overlap, as a share of the
diagram's area. It measures how much of other modules a crop of one module would show. Leiden is
seeded randomly, so its overlap varies by a point between runs.

- **The three pure-connectivity methods agree.** Greedy, Louvain and Leiden all find the same
  quality of communities (modularity 0.52, 12% of connections cut). But their modules are
  scattered across the layout, and a third of the diagram's area lies under overlapping module
  boxes. On graphs of at most 150 nodes, Leiden's advantages (guaranteed-connected communities,
  speed on large graphs) don't show, so `igraph`'s compiled dependency isn't justified.
- **Weighting by geometry halves the overlap** (18%), at a small cost in modularity (0.50) and
  cut connections (16%). Its modules are regions a reader can see.
  - `img/partition-acquire-and-lock-nx-louvain.png`: plain Louvain on TMT's "Acquire and Lock TT
    OIWFS/ODGW Logical Actual" (66 shapes). One module sprawls across the upper right and
    overlaps three others.
  - `img/partition-acquire-and-lock-nx-louvain-geo.png`: the same diagram with geometric
    weights, as six coherent regions.
- **Spatial cuts alone keep every module in bounds**, but they cut a quarter of the
  connections. They remain the fallback for groups that are still too large, and they suit
  diagrams without connections.
- **Connected components are too coarse:** mostly one big component.

## Decision

Use `networkx` (pure Python, BSD-licensed) Louvain with geometric weights, and fall back to
spatial cuts for any module that is still too large. `networkx` becomes a dependency; `igraph`
does not.

## Found along the way

- **Sequence diagrams** (5 of TMT's large diagrams) are ordered by time along one axis. Split
  them into bands along that axis, keeping every lifeline, rather than by connectivity.
- **Activity swimlanes are not nested in the layout.** TMT's partitions show as header cells
  along the top, and their actions are not their children. Swimlane membership would have to
  come from geometry (which header column an action falls under) or from the model
  (`inPartition`), and is a natural module boundary.
- **Densely cross-linked diagrams resist every method.** TMT's "Configure CSU" (92 shapes) has
  two columns with links fanning between them, and any split cuts many connections.
  Geometric weighting at least keeps each module to a contiguous run of one column.
