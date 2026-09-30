# Plan: diagram views for large diagrams, 2026-09-30

- **Status:** Draft, awaiting the maintainer's review of the open questions
- **Step prefix:** `DV`, so steps are `DV-01`, `DV-02` and so on
- **Addresses:** FU-011R1 in `docs/reviews/followup-2026-09-30.md`; builds on FU-007, FU-008 and
  FU-012 (the legend, clearer marks, drawing at the model's image size), which are fixed
  first, inside that review

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
in this order:
1. **The modeller's groups:** shapes nested in a shape (a part's internal parts, a use-case
   subject, a package or frame on the diagram) and activity partitions (swimlanes).
2. **Connected components** of what remains.
3. **Communities** within a component that is still too large: modularity-based community
   detection, with edge weights raised for shapes that sit close together. Modellers place
   related shapes near each other, and control and object flows are chained. Communities are
   merged or split until each fits.

Every node belongs to exactly one module. Hubs connected to many modules (a central part or
block) stay in the module with most of their connections, and are listed as a boundary node
of the others.

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

### Output

- **Diagram page:** the overview, then for each module its thumbnail, legend, connections and
  generated summary side by side, then the whole-diagram description.
- **Chunks:** one `generated:module_description` chunk per module, whose metadata carries the
  diagram and the module's shape numbers and element ids. One `generated:diagram_description`
  for the whole. The extracted (non-generated) diagram chunk lists modules too, so a search
  for an element finds its module.

## Steps

| Step | Work | Status |
|---|---|---|
| DV-01 | The diagram graph: nodes with stable numbers and nesting, edges with model direction and item flows. The legend, text lists and sketch all built from it. Unit tests. | Done, with the review's FU-001, FU-002, FU-007 and FU-008 fixes |
| DV-02 | Partitioning: the modeller's groups, components, communities with geometric weights and size bounds, and boundary nodes. Unit tests on small graphs; module statistics over TMT (how many modules per diagram, and their sizes). | Not started |
| DV-03 | Views: module crops with faded boundary nodes, and the overview with module outlines, all at the model's image size. | Not started |
| DV-04 | Requests and output: `module-description@v1` and `diagram-synthesis@v1`; module chunks; the page layout; the request log records module and view. | Not started |
| DV-05 | Evaluation: spot-check sets before and after, on the drone's `Perform Delivery Operations` and a sample of large TMT diagrams. | Not started |
| DV-06 | Docs: README (diagram pages, module chunks) and the review's status. | Not started |

## Open questions for the maintainer

1. **A dependency for community detection.** `networkx` (pure Python, widely used) gives
   modularity-based communities out of the box. Is it acceptable, or should a small
   implementation be written in-house?
2. **Thresholds.** A diagram counts as large at about 25 shapes, and modules aim for 8 to 25
   shapes. Should these be settings, or constants tuned on the samples?
3. **Module chunks.** Should modules be separate chunks in the RAG output (proposed: yes, since
   a question often concerns one part of a big diagram), or only sections of the diagram page?
