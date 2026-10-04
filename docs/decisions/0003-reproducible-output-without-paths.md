# ADR-0003: Per-project output is reproducible, and names no local path

- **Status:** Accepted, 2026-09-29.
- **Sources:**
  - BASE-015R1 to R4 (absorbing BASE-010);
  - RI's decision 2;
  - RF-01 (`docs/archive/plans/related-facts-2026-10-01.md`).

## Context

Two runs of one project differed in 24 of 42 files, and a copy at another path changed the text
of 15 chunks under the same ids. Retrieval and comparisons need the same input to give the same
bytes.

## Decision

- **Per-project files** carry no run id, times or local paths, only the token `sha256:<hex>`.
- **Paths live only in** `provenance.jsonl`, `state.sqlite`, `run.json` and `rag/meta/`, which
  resolves a chunk's sources.
- **Chunk text names a project** by a label ("TMT [9ffd7a2c]"), never a path or file name (RF-01).
- **Run outcomes** (LLM calls and failures) go to `run.json`, not the manifest.
- **Whatever must not depend on the hash seed is sorted** (index ids, a bug found in plan RA's
  CP7).

## Consequences

- **`treediff`** can show exactly what a change did, and every refactoring was checked with it.
- **Generated text** reproduces only while the LLM answer store is kept (ADR-0010).
