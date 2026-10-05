# ADR-0027: Heuristics are defaults, not switches; what shapes hold is shown

- **Status:** Accepted, 2026-10-05 (plan IS; the maintainer: "A").
- **Sources:**
  - `docs/archive/plans/inside-shapes-2026-10-05.md`;
  - `docs/research/inside-shapes-2026-10-05.md`;
  - `docs/design/diagrams.md`.

## Context

Plan IS added what a drawn diagram's shapes hold (compartment members, triggers) to its page and
chunk.
- **It gains:** on questions that start from a diagram, coverage@10 rose from 0.03–0.25 to
  0.77–1.00, for every system.
- **It costs:** the 210 standing questions lost a little, significantly (nDCG@10 −0.003 to −0.010;
  one question out of the top 10 for three systems).

A switch, on by default, was proposed so that a RAG stack's owner could turn it off. The
maintainer declined:

> "I think trying to explain and understand when and why to turn it off would be infeasible in
> practice. Ultimately, this project is one big pile of 'pretty good heuristics' and asking users
> to control them independently would be a recipe for confusion."

## Decision

- **What shapes hold is shown,** on the page and in the details chunk, always.
- **A heuristic gets a measured default, not a switch.** A trade-off measured as a net gain is
  taken. The tool doesn't hand users settings whose effect they can't judge. Settings stay for what
  users can judge: their models, their endpoint, what their stack reads (`rag/`), and where output
  goes.

## Consequences

- New heuristics come with a measurement and a default, and no flag.
- The existing switches for heuristics (`--threads`, `--hierarchies`, `--cross-index`,
  `--line-refs`) predate this decision. They are to be reviewed (roadmap).
