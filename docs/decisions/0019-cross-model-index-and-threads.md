# ADR-0019: An index of identifiers across models, and requirement threads

- **Status:** Accepted, 2026-10-01 (plan RF; the maintainer's answers 1 to 5); updated on 2026-10-05
  (Changes, below).
- **Sources:**
  - `docs/archive/plans/related-facts-2026-10-01.md`;
  - `docs/research/related-facts-2026-10-01.md`;
  - `docs/research/rerankers-2026-10-01.md`;
  - AR-006.

## Context

- **The corpus:** models from rival companies, with "little guidance beyond 'provide models in
  Cameo'", so no structure can be assumed for requirements.
- **What tracing matters:** from whatever the RAG returns back to the source file. Tracing within
  a model is "an opportunistic convenience".
- **Repetition:** "Repetition is welcome where it helps comprehension."

## Decision

- **The identifier index:** `CROSSREF.md` and `index:id` chunks list every identifier held by two
  or more elements, across all models, with each place. It is on.
- **Threads:** derivation trees of requirements, with what satisfies and verifies them, are
  `trace:thread` chunks. They are on, since they cost nothing measurable. Each project also has a
  `THREADS.md`.
- **Line references** (`[project:chunk]` on each line of an assembled chunk) are off.

## Evidence

- **The index:** coverage@10 rose from 0.77 to 0.97.
- **Threads:** no significant effect either way, after AR-006 corrected the grading.
- **Line references:** each costs about 15 tokens per line. Without them, complete@10 rose from
  0.20 to 0.60.

## Consequences

Facet lists were deferred: TMT's tags run to hundreds of requirements per value (roadmap).

## Changes

- 2026-10-05: the index, threads and line references are fixed defaults, no longer switches
  (ADR-0027); the decision no longer names the flags. Before: `f2b13e2`.
