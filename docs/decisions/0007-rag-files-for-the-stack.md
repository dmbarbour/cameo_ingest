# ADR-0007: `rag/` files sized to one window, with sources by label

- **Status:** Accepted, 2026-10-01 (RE-11, RF-01); updated on 2026-10-05 (Changes, below).
- **Sources:**
  - plan RE's decision 14 (`docs/archive/plans/retrieval-evaluation-2026-09-30.md`);
  - plan RF's RF-01 and the maintainer's answers;
  - `docs/research/chunk-styles-2026-10-01.md`.

## Context

- **The maintainer's RAG stack** reads only `.md`, `.txt`, `.pdf`, `.docx`, `.pptx` and `.json`
  files, not JSONL, so provenance must travel in the text.
- **It cuts text into 512-token windows** with some overlap.
- **The tracing that matters** is from whatever the RAG returns back to the source file:
  "requirements to source files".

## Decision

- **One file per chunk:** `rag/text/<project>/<sha256 of the text>.txt`, ending with a source
  line, and `rag/meta/<project>/<sha256>.json` beside it. Every kind, since 0.20.0 (ADR-0029); 0.19.1
  left out the LLM's summaries and diagram descriptions (ADR-0028).
- **Sized to one window:** a file fits one 512-token window (`plain.WINDOW`, with 100 tokens kept
  for the source line), by an estimate fitted to e5's tokenizer.
- **The source line:** `--rag-source trace` (the default) gives the project and trace locator;
  `id` gives short ids that `rag/meta/_sources.json` resolves to files.
- **No paths or file names in chunk text** (ADR-0003). `rag/meta` carries `source_id`,
  `source_file` and `source_files`.
- **The output tree** comes from `-o`, or else `CAMEO_INGEST_TREE`, or else `./ingest_tree` (plan CF,
  0.20.2).

## Consequences

- **Fit:** 3 of 43,552 files in `rag/` exceed 512 tokens, against 9% of chunks before.
- **Retrieval:** MRR changed by −0.02 to +0.02, within noise.
- **Smaller limits:** a model with a smaller limit (MiniLM's 256) sees only the start of each file.

## Changes

- 2026-10-05: `rag/` leaves out the LLM's summaries and diagram descriptions (ADR-0028). Before:
  `3c254db`.
- 2026-10-05: every kind in `rag/` again, since 0.20.0 (ADR-0029). Before: `80de425`.
- 2026-10-05: the output tree from `CAMEO_INGEST_TREE` or `./ingest_tree`, where it came from
  `CAMEO_INGEST_DEST` (plan CF). Before: `463e42e`.
