# Research: do type hierarchy chunks help retrieval? 2026-10-04

**Question.** Plan TH (`docs/archive/plans/type-hierarchies-2026-10-04.md`) adds a chunk per type
hierarchy, as threads are for requirement derivations. Does it help questions about a model's
kinds, and does it hurt others?

**Method.**
- **A fictional hierarchy:** Port Calder's equipment catalogue now has types, three levels deep:
  - Field Device, the root;
  - its kinds: Signal Controller (3 models), Vehicle Detector, Priority Receiver (2 models), the
    push button and the modem;
  - Vehicle Detector's kinds: the loop detector, and a Non-intrusive Detector, with radar and video
    under it.
- **Questions** (`traffic.kinds()`, `out/eval/fiction/questions-th.jsonl`): four, each asked
  literally and as a paraphrase, graded in parts, one part per kind.
  - A part is held where a chunk says the kind is a kind of its general (the kind's own chunk, or
    its general's), or where a hierarchy of the catalogue lists it.
  - **k01**, the kinds of vehicle detector, spans two levels: only a hierarchy holds the whole
    answer.
  - **k02**, all ten device types, spans every level, and no single chunk holds it, since the
    hierarchy comes in two parts.
  - **k03** (priority receivers) and **k04** (controllers) are one level: the general's own chunk
    lists them too, so they are the controls.
- **The tree:** `out/v018/llm`, the samples and the fiction, 0.18.0 with the LLM. Retrieval ran on
  its `rag/` with hierarchy chunks (259) and without (`--no-hierarchies`), as in plan RF, over the
  210 standing questions and the 8 new ones.

## Results

**The 8 hierarchy questions, without → with:**

| System | coverage@10 | complete@10 | MRR@10 |
|---|---|---|---|
| BM25 | 0.41 → 0.44 | 0.12 → 0.25 | 0.32 → 0.32 |
| e5-large | 0.59 → 0.69 | 0.38 → 0.38 | 0.27 → 0.31 |
| e5-large + BM25 | 0.55 → 0.55 | 0.25 → 0.38 | 0.31 → 0.39 |
| BM25, reranked | 0.53 → 0.53 | 0.25 → 0.38 | 0.23 → 0.36 |
| e5-large, reranked | 0.44 → 0.53 | 0.25 → 0.38 | 0.22 → 0.33 |
| e5-large + BM25, reranked | 0.40 → 0.59 | 0.25 → 0.38 | 0.21 → 0.39 |

- **Every change is up or level, but none is significant:** eight questions are too few for the
  paired bootstrap.
- **Question by question,** for the hybrid reranked:
  - k01 asked literally gets its whole answer in one window (complete 0 → 1), the hierarchy;
  - k02 asked literally goes from no part to all ten (coverage 0 → 1.00), and as a paraphrase from
    0.20 to 0.70;
  - k03 asked literally ranks its answer first (MRR 0.50 → 1.00).
- **Three questions fail either way:** two paraphrases ("which ways of sensing traffic…") and k04
  asked literally. Neither the hierarchy nor the element chunks are found.

**The 210 standing questions:** no measure moved significantly. MRR@10 rose by at most 0.005, and
coverage and complete were unchanged.

## Decision

Keep hierarchy chunks, on by default (`--hierarchies`; since 2026-10-05, always, ADR-0027). They
hold answers that span the levels of a hierarchy, which no element chunk holds, and they cost the
other questions nothing measurable.

## Changes

- 2026-10-05: the decision notes that the `--hierarchies` switch is retired (ADR-0027). Before:
  `f2b13e2`.
