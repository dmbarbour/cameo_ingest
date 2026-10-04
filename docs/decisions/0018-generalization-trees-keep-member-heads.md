# ADR-0018: Trees drawn with each member's head kept

- **Status:** Accepted, 2026-10-03 (plan SK, SK-01).
- **Sources:**
  - `docs/research/sketch-ambiguities-2026-10-03.md`;
  - `docs/design/diagrams.md`.

## Context

Cameo draws a tree of generalizations as a horizontal bar, a vertical bar up to the parent, and a
short stub from each child. The bars are a view of their own (`Tree`), which the layout reader
skipped. In the samples, 2,111 of 3,083 generalizations are in trees, and in 326 trees no path
reached the parent: floating arrowheads pointed at nothing.

## Decision

- **The bars are drawn,** from the `Tree` view.
- **The tree's own head:** when every member points at the base, the base gets a head in the
  members' style, hollow for generalizations. Bars are dashed for dependency-like kinds, and a
  containment tree has no head.
- **Each member keeps its own head** at the bar too (option B). The UML style, one head only
  (option A), was measured and rejected.

## Evidence

On 68 members, gemma-4 found the right way round:
- **41** before the bars were drawn;
- **39** with one head only;
- **50** with the members' heads kept.

## Consequences

- **Qwen3-VL** reads clean trees top-down, like an organization chart. Reading guides help it
  only a little (ADR-0017). Directions reach descriptions as text anyway.
