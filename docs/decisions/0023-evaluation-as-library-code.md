# ADR-0023: Evaluation code is library code; finished studies retire to a tag

- **Status:** Accepted, 2026-10-01 (the maintainer's decisions 2 and 3; AR-020, AR-021, AR-026).
- **Sources:**
  - `docs/archive/reviews/architecture-2026-10-01.md`;
  - `docs/archive/plans/refactoring-2026-10-02.md`.

## Context

Every retrieval measure rested on untested script code. Two fictional corpora were graded by
different rules. Finished studies accumulated in the tree.

## Decision

- **The evaluation is a package,** `cameo_ingest.evaluation`:
  - grading, systems, reports and records, tested;
  - scripts hold only arguments;
  - `run.json` is written beside the rankings, so the judges cut the same windows.
- **An optional extra:** numpy and tokenizers are the `eval` extra (`cameo-ingest[eval]`), and
  `evaluation.require()` names it when missing. The ingest never imports `evaluation`.
- **Finished studies are deleted from the tree** and cited by tag `studies-2026-10-02`, with
  retired templates.

## Consequences

Evaluation runs are reproducible from `run.json`, and the fiction is graded by one set of rules.
