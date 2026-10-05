# ADR-0026: Type hierarchies as assembled chunks, beside threads

- **Status:** Accepted, 2026-10-04 (plan TH; the maintainer asked for them "esp. for search"). The
  switch was retired on 2026-10-05: hierarchy chunks are always on (ADR-0027).
- **Sources:**
  - `docs/archive/plans/type-hierarchies-2026-10-04.md`;
  - `docs/research/type-hierarchies-2026-10-04.md`;
  - ADR-0019 (threads), `docs/design/output-and-chunks.md`.

## Context

Each kind's chunk says what it is a kind of, and a general's chunk lists its direct kinds. A
question whose answer spans the levels of a hierarchy ("what kinds of vehicle detector?", where
some are kinds of a kind) has its answer spread over several chunks, none of which holds it all.

## Decision

- **A chunk per type hierarchy** in each model (`index:hierarchy`, method `assembled`):
  - each kind once, level by level, with its kind word and the first sentence of its
    documentation;
  - rooted at a general with no general in the project, or at a type outside it that two or more
    of its kinds specialize;
  - cut into parts that repeat their ancestors, as threads are (ADR-0019).
- **In the tree's chunks,** always. Each project keeps `index/hierarchies.jsonl` and
  `HIERARCHIES.md`.

## Consequences

- On Port Calder's fictional hierarchy, answers that span levels come back whole in one window
  (complete@10 from 0.25 to 0.38 for most systems), at no measurable cost to the 210 standing
  questions. With eight questions, nothing is significant.
- Kinds that specialize a shared library type across models (TMT's and TMT-2024x's
  `MonteCarloAnalysis`) are listed per model, not yet brought together across models.
