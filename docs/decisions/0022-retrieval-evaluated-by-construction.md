# ADR-0022: Retrieval evaluated by construction, with paired comparisons

- **Status:** Accepted, 2026-09-30 to 2026-10-02 (plan RE's decisions; plan RA's checks).
- **Sources:**
  - `docs/archive/plans/retrieval-evaluation-2026-09-30.md`;
  - `docs/research/fictional-projects-2026-10-01.md`;
  - `docs/research/chunk-styles-2026-10-01.md`;
  - `docs/design/evaluation.md`.

## Context

- **No gold set:** the maintainer "doesn't know the samples well enough" to write one.
- **The production stack** isn't ours to control: it cuts 512-token windows, with dense retrieval.
- **Local models** are out: the machine has 8 cores, 15 GB and no GPU, and a local embedding run
  coincided with a crash.

## Decision

- **Simulate the stack:** 512-token windows with 64 of overlap, cut on e5-large's tokenizer.
- **Answers known by construction:** fictional projects, ours to share, with planted facts and
  questions graded by rule (`source`, `parts`, `fact`, `element`).
  - A test checks the answer key.
  - LLM judges grade the rest; the lower grade wins when the two main judges disagree.
- **DeepInfra only:** for embeddings, rerankers and judges. A model DeepInfra doesn't serve gets a
  stand-in, reported as such.
- **Changes are compared paired:** the same questions, a paired bootstrap of 4,000 rounds at 95%.
  With 75 to 88 questions, MRR differences under about 0.07 are noise.

## Consequences

- **Every change to the output was checked against retrieval:** chunk styles, the cross index,
  refactoring, and plan SK's release check.
- **Scores before 2026-10-02** (KOIS's re-basing) are not comparable with later ones.
