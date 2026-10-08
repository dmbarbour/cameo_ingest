# ADR-0028: `rag/` leaves out the LLM's summaries and diagram descriptions

- **Status:** Accepted, 2026-10-05 (plan RM; the maintainer: "If generated chunks are a big loss,
  then we must drop them as implemented"); superseded the same day by ADR-0029 (0.20.0), whose
  requests' answers return to `rag/` (Changes, below).
- **Sources:**
  - `docs/archive/plans/retrieval-measures-2026-10-05.md`;
  - `docs/research/ledgers-and-generated-2026-10-05.md`;
  - ADR-0007 (`rag/`), ADR-0027 (heuristics are defaults).

## Context

- **The maintainer's stack reads files** (ADR-0007): it can't weight or filter chunks by kind, so
  what `rag/` holds is what it searches.
- **Generated chunks crowd out answers.** On the 226 standing questions, without them every
  reranked system gains significantly (MRR@10 +0.026 to +0.038), and no measure of any system
  falls significantly. On 8 list questions, they make no difference.
- **It isn't grading:** of 39 questions where a generated window outranked the first answer, 5 were
  answered by it in other words. The rest name what a question names, and hold none of its facts.
- **Why:** the requests ask for a package's "main elements and how they relate", with the names
  as written, and 73% of package-summary inputs on the samples (85% of part summaries') carry no
  documentation at all. The answers are inventories of names. Diagram descriptions get names and
  arrows only, and narrate them.
- **The kinds stand in for each other:** leaving one out changes little, since another takes its
  place. Part descriptions (one module of a large diagram) help a little.
- **Image descriptions** hold what no other text does: what the vision model read in an image. The
  fiction has none, so they weren't measured.

## Decision

- **Left out of `rag/`:** `generated:summary`, `generated:diagram_description` and
  `generated:module_summary` (`rootfiles.Assembly.rag_without`). A tree's `rag/` drops them on its
  next run.
- **Kept in `rag/`:** `generated:module_description` and `generated:image_description`.
- **Kept everywhere else:** the pages show every summary and description, and `chunks.jsonl` keeps
  them, by kind, for a stack that can weight or filter them.
- **The requests are unchanged.** The LLM still writes them, for the pages and for validation.
- **Not a setting** (ADR-0027). `scripts/assemble_tree.py --rag-all` puts them back in a copy of a
  tree, to measure a change.

## Consequences

- Requests that ask for something retrieval can use (what a package is for, in other words than
  its names) are worth testing; if their answers stop crowding, they can return to `rag/`.

## Changes

- 2026-10-05: superseded by ADR-0029: the requests ask what a package or diagram is about, and
  `rag/` leaves nothing out again. Before: `80de425`.
- 2026-10-08: `exports.py` renamed `rootfiles.py` (review CQ-006). Before: `463e42e`.
