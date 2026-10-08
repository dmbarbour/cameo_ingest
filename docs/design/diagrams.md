# Design: diagrams, sketches and modules

How a diagram's layout becomes text, a sketch for the vision model, an SVG for people, and modules
when it is large. Decisions: ADR-0005, 0012, 0013, 0017, 0018. Calibration of the sizes:
`docs/design/vision-calibration.md`.

## Layout streams

Each diagram's layout is a `BINARY-<uuid>` entry whose root is `<mdOwnedViews>` (`layout.py`). A
stream is recognized by its first start tag, not a fixed byte count (BASE-013): TMT's begin with
a 55-byte declaration. Each `mdElement` is a view:
- `elementClass` (the shape's kind);
- an optional `elementID`;
- absolute `geometry` ("x, y, w, h" for shapes, "x1, y1; x2, y2; …" for paths);
- nested `mdOwnedViews`;
- for paths, `linkFirstEndID` and `linkSecondEndID`.

**Cameo's conventions the reader depends on:**
- **Path ends:** a directed path's target is its first end (`linkFirstEndID`), in every measured
  case.
- **Trees:** a tree of generalizations (and of containment or dependencies) is a `Tree` view:
  - a horizontal bar (`horizontalBarLeft`, `horizontalBarRight`, `horizontalBarY`);
  - a vertical bar from the base shape (`baseShape`, at `verticalBarX` from its left edge, from
    `verticalBarY`).

  Each member names it by `treeID` and runs only from its other end to the bar. In the samples the
  base is above the bar in 464 trees, below in 39.
- **Label boxes:** `AssociationTextBox` and `MessageSignature` are nested in their connection's
  view, and show its name, or a message's signature with its arguments.
- **References:** `<file>#<id>` references resolve to the element when its id is in the model
  (FU-019).

**Elements shown** (`Diagram.shown`) feed the elements' "Shown in diagrams", the catalog and the
tables:
- **A drawn diagram:** the elements its layout draws.
- **A diagram without a layout** (tables, mostly): its `usedObjects`, which Cameo writes as
  `href='#id'`. For a table, these are its rows when last saved, and its page lists them as
  "Elements shown when last saved".

A drawn diagram's `usedObjects` also name what is shown inside shapes (compartments, triggers).
They aren't elements shown, but the diagram says what its shapes hold (below).

**Shown inside its shapes** (`view.inside_shapes`, plan IS, ADR-0027, 0.19.0):
- **What:** each element a drawn diagram uses (`Diagram.used`, `usedObjects` as saved) but doesn't
  draw.
- **Placed:** under the shape or line drawn for its owner, or its owner's owner, up to three
  levels. That covers a block's properties, operations and ports, a transition's trigger, and a
  state's regions and do-activities.
- **Its line:** the holder's legend number and label, then what it holds by kind: "[1] «Block»
  Drone: properties battery; operations charge()".
- **Not checked:** elements whose owner isn't drawn (mostly an internal block diagram's
  connectors, whose owner is the frame) are counted, not listed.
- **Where:** on the page and in the diagram's details chunk. No LLM request reads it.
- **Measured:** questions that start from a diagram gain greatly (coverage@10 from 0.03–0.25 to
  0.77–1.00), and the 210 standing questions lose a little (nDCG@10 −0.003 to −0.010), mostly to
  Port Calder's corridor diagrams naming every intersection
  (`docs/research/inside-shapes-2026-10-05.md`). Kept, with no switch.

## The graph and the text

`diagram_graph.build` turns a layout into numbered nodes (shapes) and links (connections).
`diagram_text.describe` turns those into the legend and connection list, which pages and requests
share.
- **Shapes:**
  - numbered in layout order, nested by their views;
  - pins and ports (`ATTACHED`) belong to their owner, and read as "Owner.pin";
  - decorations are never shapes: text boxes, connector ends, roles, note anchors, diagram shapes,
    connector circles, and the label boxes (`DECORATION`).
- **Directions** come from the model's relationship. Without one, Cameo's first-end-is-target rule
  applies (FU-001). A sample-run invariant checks every directed edge.
- **Connections:**
  - read "[a] source →[kind: name]→ [b] target", with the dependency's verb ("is derived from",
    "satisfies") from `semantics.RELATIONS`, or "[a] —[kind]— [b]" for undirected ones;
  - a connector's item flows read "carries X →" (FU-002);
  - a flow broken into two segments at connector circles is joined into one connection (FU-017);
  - a label box's text joins its connection's when the model's names don't already say it: "Start
    System (Sig StartTheSystem)" (0.14.1).
- **Trees:** `DiagramGraph.trees` lists each tree:
  - its base shape;
  - its bars;
  - its members;
  - whether every member points at the base (`to_parent`).

## The sketch (`sketch.py`)

A PNG redrawn from the layout for the vision model (ADR-0012):
- **Size:** it fills the pixel budget at the diagram's aspect ratio, sides in whole 48 px patches,
  enlarged at most 2× (`MAX_ZOOM`).
- **Shapes:**
  - drawn in nesting order, then larger first (`diagram_graph.drawing_order`), so that a frame
    lies under the shapes it encloses, as in Cameo (plan SK);
  - each tagged with its number in a grey box, with its name on one line, cut with "…" by
    bisection (FU-023);
  - initial and final nodes and use cases are ellipses; fork and join bars are filled.
- **Connections:**
  - solid, or dashed for dependency-like kinds (`DASHED`, including an association class's link,
    `LinkAttribute`);
  - a hollow triangle for generalization and realization (`HOLLOW`), and an open arrowhead
    otherwise, at the target;
  - a mid-line arrow when all of a connection's items flow one way;
  - pins and ports as dots on their owner; connector circles labelled "to N" and "from N".
- **Trees:**
  - the bars are drawn;
  - when every member points at the base, the base gets a head in the members' style, and each
    member keeps its own head at the bar too (ADR-0018);
  - bars are dashed for dependency-like kinds, and a containment tree has no head.
- **Sizes** come from a `SketchStyle(font_px, arrow_px, line_px)` (the title is `font_px + 6`, an
  arrowhead's stroke `line_px + 1`), calibrated per model.
- **Modules:** a module's view (`module_png`) draws the module's shapes in full and fades the rest.
  Shapes of other modules it connects to keep their numbers, at the picture's edge when outside
  it. The overview (`overview_png`) tints and outlines each module, labelled M1, M2…
- **Validation:** `render_png(drawn=…)` reports each shape's name as drawn, which validation scores
  against (`docs/design/vision-calibration.md`).

**Reading guides** (ADR-0017): `drawing.conventions(graph, focus)` names the drawing conventions a
sketch uses, around a module's own shapes for a module. Each request then explains just those,
with the template's sentences (`prompts.GUIDE`):
- `tags`, `nesting`, `frames`;
- `open`, `hollow`, `tree`, `containment`;
- `dashed`, `association-class`;
- `pins`, `flows`, `breaks`;
- `bars`, `sequence`.

## The SVG, for people

`sketch_svg.render_svg` writes an SVG beside each PNG (plan KX), in the same drawing order and
notation:
- each shape is a group with `data-k` (its element) and a `<title>` tooltip giving its number and
  full label;
- connections carry a tooltip of their kind, name and ends.

The search page can show it when exported with `--sketches svg`.

## Large diagrams: modules

ADR-0013 (`partition.py`).
- **When:** a diagram of more than N shapes is split into modules of MIN to MAX shapes
  (default 25:6:25, calibrated per model).
- **How:** Louvain community detection (`networkx`, seed 1) on the connections, weighted by how
  close the shapes are drawn:
  - a connection counts `1 + 2·exp(−d / (0.3 · median distance))`;
  - nesting adds 1.0;
  - each shape's 2 nearest neighbours add 0.3 each.

  Communities are merged and cut to fit MIN to MAX, preferring merges that stay within MAX, ranked
  by link weight, then distance. Spatial median cuts are the fallback.
- **Shapes without a rectangle** join their container's module, else the one they link to most.
- **Numbering:** M1, M2… run in reading order, in rows a third of the diagram's height, left to
  right. A module's box leaves out containers that reach into other modules. The legend tags each
  shape "(M k)".
- **Packages** are split the same way, with document order in place of geometry:
  - a relationship counts `1 + 2·exp(−gap / 5)`;
  - nesting adds 1.0;
  - adjacent sections add 0.3;
  - neighbouring parts that fit together are joined.

**Evidence** (`docs/research/diagram-partitioning-2026-09-30.md`):
- **Geometric weights:** module boxes overlap 18% against 36% for plain Louvain; modularity 0.50;
  16% of connections cut; 98% of modules in bounds; 3 ms per diagram.
- **Leiden's** advantages don't show on graphs this small.
- **Sequence diagrams** would split better in time bands, and activity diagrams along their
  partitions (roadmap).

## Measured faults

Plan SK surveyed 3,246 diagrams in the samples (25,409 shapes, 21,795 connections):
- **Trees:** 503 trees, holding 2,111 of 3,083 generalizations. In 326 of them, no path reached
  the parent before the bars were drawn.
- **Frames:** 310 shapes were hidden under frames, in 80 diagrams.
- **Labels and links:** 54 association and 111 message label boxes, and 67 association-class
  links.

**Still open** (roadmap):
- **Sequence diagrams:** messages join activations, while models name the lifelines.
- **Undrawn ends:** some connections end at views that aren't drawn as shapes.
- **Messy layouts:** in a few, a tree's bar runs along an unrelated shape.
