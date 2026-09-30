# Plan: modular views of large diagrams and packages, 2026-09-30

- **Status:** Accepted on 2026-09-30, with the maintainer's answers under Decisions, and widened
  to large packages (FU-005). In progress.
- **Step prefix:** `DV`, so steps are `DV-01`, `DV-02` and so on
- **Addresses:** FU-011R1 and FU-005R1 in `docs/reviews/followup-2026-09-30.md`. It builds on
  FU-007, FU-008, FU-012 and FU-015 (the legend, clearer marks, drawing at the model's pixel
  budget), which are fixed first, inside that review.

## Goals

1. **Readable pieces.** A diagram too large to read in one image the model sees (768 × 768 px
   on the current endpoint) is split into modules that each are readable.
2. **Meaningful splits.** Modules follow the modeller's own grouping where there is one, and
   otherwise how the shapes connect and where they sit, so that each module can be understood
   and summarized on its own.
3. **One view for people and the model.** Each module gets a thumbnail, a legend (numbers to
   full labels) and a summary side by side. The whole diagram gets an overview with the
   modules outlined, and a description built from the module summaries.
4. **Nothing silently dropped.** No shape or connection is cut to fit a limit: everything
   belongs to a module, and connections between modules are listed at the level above.

5. **Large packages too.** A package too large for one good summary (FU-005: the drone
   sample's 36,000 to 50,000-character packages were cut to 12,000) is split into modules of
   related elements. Each is summarized on its own, and the package summary is built from
   them.
6. **Robust long prompts.** Gemma-4's context is large (about 262,000 tokens), but models
   attend unevenly across a long context. Long requests are "sandwiched": the short headers
   and the instructions are repeated after the long input, to focus the answer.

## Decisions

All decisions were made on 2026-09-30.

| # | Question | Decision |
|---|---|---|
| 1 | Community detection library | Try `networkx` and contrast it with alternatives on the samples, then keep what works. |
| 2 | Thresholds | Settings, if convenient, as levers for tuning and testing; users should never need them, so good defaults are built in. |
| 3 | Module chunks | Yes: each module is a separate chunk, with enough provenance to locate it within its diagram. |
| 4 | Large packages (FU-005) | Investigate the same kind of modular breakdown for very large packages, and sandwiching for long prompts. |

## Design

### The diagram graph

One model of a diagram serves the legend, the text lists, the sketches and the partitioning:
- **Nodes:** the shapes, each with a stable number, its nesting parent and its rectangle.
- **Edges:** the connections, with direction from the model (FU-001), relationship kind,
  stereotype, and conveyed items (FU-002).

Pins and ports attach to their owner node. Decorations (connector ends, roles, text boxes)
are not nodes; their text goes to the element they label.

### Partitioning

A diagram is **large** when its shapes can't be drawn legibly at the model's image size. As a
rule of thumb, that means more than about 25 shapes, or a bounding box whose scale factor
would bring text below about 11 px. Small diagrams keep a single view. Large ones are split
as DV-02 found best (`docs/research/diagram-partitioning-2026-09-30.md`):
1. **Communities:** Louvain community detection (`networkx`) on the connections, weighted up
   to 3 times for shapes that sit close together. Modellers place related shapes near each
   other, so modules are regions that can be cropped. Nesting and each shape's two nearest
   neighbours are weaker links, so a nested shape tends to stay with its container, and shapes
   with no connections join what they sit next to.
2. **Bounds:** a module over 25 shapes is split again, by communities or else by median cuts
   of the layout. One under 6 joins the module it is most connected to, or else the nearest.
3. **Later refinements**, found in DV-02:
   - **Sequence diagrams:** split into bands along the time axis.
   - **Swimlanes:** activity partitions as module boundaries, from the model's `inPartition`.

Every node belongs to exactly one module. Hubs connected to many modules (a central part or
block) stay in the module with most of their connections, and are listed as a boundary node
of the others. A container whose shapes fall in several modules belongs to one of them,
but a module's crop is set by its other shapes, so it isn't widened to the container's size.

### Views and requests

- **Module view:** a crop of the diagram around the module, drawn at the model's image size,
  with its shapes numbered. Boundary nodes appear faded at the edge, with their numbers.
- **Module request (`module-description@v1`):** the module view, its legend, its internal
  connections, and its boundary connections, labelled with the other modules. The request
  asks what the module does or represents.
- **Overview:** the whole diagram, small, with each module's outline and number (M1, M2...).
- **Diagram request (`diagram-synthesis@v1`):** the overview, the module summaries, and the
  connections between modules. The request asks for the diagram's meaning as a whole.
- **Small diagrams:** a single request with `diagram-description@v2` (FU-009R1).

### Large packages

Measured on the samples (DV-05): TMT has 119 packages over the old 12,000-character cut, 15 over
200,000 and one of 3.8 million (2,718 requirements imported from DOORS, with no relationships
between them). Many large packages have no internal relationships, so document order and
nesting carry most of the structure.

- **Candidate modules**, from what the model already records about the package:
  - nested classifiers and their members (a block with its parts, ports and operations);
  - relationship clusters (a requirement tree linked by «deriveReqt», blocks joined by
    associations and item flows, activities with their allocations);
  - elements of one kind or stereotype, when nothing connects them.

  The same partitioning code as for diagrams runs on the element graph (containment plus
  relationships), with a size bound in characters of section text rather than in shapes.
- **Requests:**
  - **`module-summary@v1`:** a module's sections.
  - **`package-summary` (a new version):** the module summaries, plus the package's own section
    and member list, so the whole package reaches the model with nothing cut.
- **Sandwiching:** long requests (package modules, and any request over a threshold) repeat
  the package or diagram header and the instructions after the input.
- **Chunks:** one `generated:module_summary` per package module, with the element ids it
  covers.

### Output

- **Diagram page:** the overview, then for each module its thumbnail, legend, connections and
  generated summary side by side, then the whole-diagram description.
- **Chunks:** one `generated:module_description` chunk per module. Its provenance locates it in
  the diagram:
  - the diagram's locator;
  - the module number and the diagram's module count;
  - the module's shape numbers (as in the legend) and element ids;
  - its bounding box in diagram coordinates;
  - the file and anchor of its section on the diagram page.

  There is one `generated:diagram_description` for the whole diagram. The extracted
  (non-generated) diagram chunk lists the modules too, so a search for an element finds its
  module.

## Steps

| Step | Work | Status |
|---|---|---|
| DV-01 | The diagram graph: nodes with stable numbers and nesting, edges with model direction and item flows. The legend, text lists and sketch all built from it. Unit tests. | Done, with the review's FU-001, FU-002, FU-007 and FU-008 fixes |
| DV-02 | Partitioning, compared: `networkx` communities against alternatives (connected components with the modeller's groups, label propagation, spatial clustering of the layout, and `igraph`'s Leiden if it earns its dependency). Measure module sizes, edges cut, geometric compactness and speed on the drone sample and TMT, then keep what works. Write the results up as a research note. | Done: `docs/research/diagram-partitioning-2026-09-30.md`; networkx Louvain with geometric weights, with spatial cuts as the fallback |
| DV-03 | Diagram views: module crops with faded boundary nodes, and the overview with module outlines, all at the pixel budget. | Done: `modules.py` (`partition`, `module_png`, `overview_png`) and `diagrams.Frame`; review findings FU-016 to FU-019 fixed along the way |
| DV-04 | Diagram requests and output: `module-description@v1` and a synthesis request; module chunks with their provenance; the page layout; thresholds as settings with built-in defaults. | Done: `module-description`, `diagram-synthesis` (asked once the modules are answered), both at v2 after the first live run, whose answers named modules by number ("sends it to M2"); a section and a `generated:module_description` chunk per module, whose `module` metadata gives its number and count, shapes, element ids, box, anchor and image; the overview replaces a large diagram's sketch; `--diagram-modules N:MIN:MAX` (default 25:6:25); version 0.3.0 |
| DV-05 | Package modules: the element graph, partitioning by section size, `module-summary@v1`, a new `package-summary` built from modules, and chunks. | Done: a package over 12,000 characters is split into parts of 3,000 to 12,000 (`modules.sequence_partition`: Louvain on nesting, relationships and document order, then neighbouring parts packed); `module-summary@v1` per part, then `package-synthesis@v1` from the parts' summaries, through runs of at most 30; a "Parts, summarized" section and a `generated:module_summary` chunk per part or run, naming its elements; found FU-020 and FU-021 on the way; version 0.4.0 |
| DV-06 | Sandwiching for long requests, compared with and without on the same items. | Not started |
| DV-07 | Evaluation: spot-check sets before and after, on the drone's large activity diagram and packages, and a sample of large TMT diagrams and packages. | Not started |
| DV-08 | Docs: README (modules on diagram and package pages, module chunks, settings) and the review's status. | Not started |

## Open questions for the maintainer

All answered on 2026-09-30: see Decisions.
