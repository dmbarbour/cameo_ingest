# ADR-0017: Tell the model how to read the image

- **Status:** Accepted, 2026-10-03 (plan SK, SK-08 and SK-09).
- **Sources:**
  - `docs/archive/plans/sketch-ambiguities-2026-10-03.md`;
  - `docs/research/sketch-ambiguities-2026-10-03.md`.

## Context

Validation showed a model reading a correct sketch against its notation: Qwen3-VL listed a clean
tree's 12 generalizations from parent to child, against the triangles. The maintainer: "a prompt
informs how to read a diagram when we're clearly in a position to know. Not only should we do so
here, we could also look for other cases where our local knowledge of Cameo could help a model
process an image."

## Decision

- **Reading guides:** each request that sends a sketch explains the drawing conventions that
  sketch uses, one sentence each:
  - number tags, nesting, frames;
  - arrowheads and triangles, trees, containment;
  - dashed dependencies, association classes;
  - pins, item flows, connector circles;
  - fork and join bars, sequence diagrams.
- **Chosen per sketch:** `drawing.conventions` finds them from the diagram's graph, around a
  module's own shapes for a module.
- **Versioned:** the sentences are fragments of the template version (ADR-0009). They are in
  `diagram-description` (v6), `module-description` (v3) and validation's `eye-sketch` (v2).

## Evidence

On the same 48 sketches:
- **gemma-4** found 80% of connections rather than 75%, and invented a third fewer.
- **Qwen3-VL** found 77% rather than 71%.

## Consequences

- **The principle extends:** wherever the pipeline knows what the model can't see, the request
  says so.
- **Next case:** embedded images, which could be described with the element that owns them, once
  attachments are linked (roadmap).

## Changes

- 2026-10-08: `sketch.conventions` moved to `drawing.conventions` (review CQ-013). Before: `3c254db`.
