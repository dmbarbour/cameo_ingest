# ADR-0013: Large diagrams in modules, large packages in parts

- **Status:** Accepted, 2026-09-30 (plan DV; the maintainer's decisions 1 to 4); updated on 2026-10-05 (Changes, below).
- **Sources:**
  - `docs/archive/plans/diagram-views-2026-09-30.md`;
  - FU-005, FU-011, FU-012, FU-022;
  - `docs/research/diagram-partitioning-2026-09-30.md`;
  - `docs/research/sandwiching-2026-09-30.md`.

## Context

- **Large diagrams:** a diagram of more than about 25 shapes is too large to read in one image at
  gemma-4's budget.
- **Large packages:** TMT has 119 packages over 12,000 characters, and one of 3.8 million
  characters (2,718 DOORS requirements). One long request loses the middle of a large package.

## Decision

- **Modules:**
  - a diagram of more than N shapes is split into modules of MIN to MAX shapes, by Louvain
    community detection (`networkx`, seed 1) on its connections, weighted by how close the shapes
    are drawn;
  - `igraph` and Leiden were rejected;
  - every shape is in exactly one module;
  - each module is drawn and described on its own, then the diagram as a whole from those
    descriptions;
  - thresholds N:MIN:MAX, default 25:6:25, calibrated per model (ADR-0015).
- **Parts:**
  - a package over 12,000 characters is summarized in parts of 3,000 to 12,000 characters,
    grouped the same way, with document order in place of geometry;
  - it is then summarized from its parts, through runs of at most 30.
- **Digests:** a package at least 80% instance specifications is summarized in one request, from
  a digest of its instances by classifier and slot (FU-022).
- **No sandwiching:** repeating the task after the input was not adopted; short parts keep inputs
  even.
- **Rounds:** LLM requests run in rounds: modules and parts first, then the descriptions and
  summaries built from their answers.

## Evidence

- **Geometric weights:** module boxes overlap by 18%, against 36% for plain Louvain. Modularity
  is 0.50 against 0.52, 16% of connections are cut, and it takes 3 ms per diagram.
- **Above 100,000 characters,** one request draws 13% of its names from the middle third, against
  21% in parts. Sandwiching skews further to the start (63%).

## Consequences

- **Sequence diagrams and swimlanes** are split like any other diagram, though time bands and
  partitions would be better boundaries (roadmap).
- **The package thresholds** are constants, not settings.

## Changes

- 2026-10-05: `--diagram-modules` is gone: the thresholds are calibrated or the default (ADR-0030). Before: `3c254db`.
