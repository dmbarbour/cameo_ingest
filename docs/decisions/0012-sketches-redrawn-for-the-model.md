# ADR-0012: Sketches redrawn from the layout, numbered, at the model's budget

- **Status:** Accepted, 2026-09-30. Sizes calibrated per model since 2026-10-03 (ADR-0015).
- **Sources:**
  - FU-007, FU-008, FU-012, FU-015, FU-016, FU-017;
  - `docs/research/gemma4-images-2026-09-30.md`.

## Context

The file holds layouts, not Cameo's renderings. A vision model reads text and arrows only above
its own limits, and a host may shrink a large image to a fixed budget: gemma-4 on DeepInfra sees
280 soft tokens of 48 × 48 px.

## Decision

- **Sketches are redrawn from layout data,** and never presented as Cameo renderings.
- **Numbered:** each shape carries its legend number in a tag, and its name on one line, cut with
  "…". The legend has the full label.
- **Notation:**
  - a hollow triangle for generalization and realization;
  - an open arrowhead otherwise, at the target;
  - dashed lines for dependencies;
  - mid-line arrows for item flows;
  - pins and ports as dots on their owner;
  - connector ends and roles not drawn;
  - broken flows joined, with circles labelled "to N" and "from N".
- **The budget:** sketches fill the pixel budget at the diagram's aspect ratio, with sides in
  whole 48 px patches, enlarged at most 2×. Embedded images are only scaled down.
- **Requests:** each request gets the sketch with the legend and connections as text, so a weak
  model has less room to invent.
- **For people:** an SVG sketch is written beside each PNG.

## Consequences

- **Calibrated per model:** sizes, budget and image order are now measured for each model
  (ADR-0015).
- **Validation** measures what a model reads from them (ADR-0016).
