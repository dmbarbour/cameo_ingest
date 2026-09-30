# Plans

Plans live in `docs/plans/<name>-<YYYY-MM-DD>.md`. Remediation that can be finished before
its review closes is written into the review itself (`docs/reviews/`) and is not listed
here.

## Index

| Plan | Status | Addresses |
|---|---|---|
| [Resumable, content-addressed ingest](resumable-ingest-2026-09-29.md) | Completed 2026-09-29 | BASE-008R1, BASE-016R2, BASE-017R1, BASE-021R1 |
| [Measuring LLM enrichment quality](llm-quality-2026-09-30.md) | Accepted; in progress (LQ-01, LQ-02 done) | FU-006R1 (and measures fixes for FU-001, FU-002, FU-004, FU-005) |

## Tentative

These plans are not yet written. The first comes from the LLM quality plan's open question
4; the others come from the roadmap in the top-level `README.md`.

- **Retrieval evaluation.** A set of questions of the kinds the README's RAG advice targets
  ("why does requirement R exist?", "list the activity diagrams", "which models came from
  supplier X?"), each with the chunks that should answer it. Measure how often those chunks
  come back from `chunks.jsonl` with plain vector search, and with keyword search alongside.
  Then use the results to guide chunking, ledgers and metadata.

- **Recompute tables and matrices.** Cameo computes table and matrix rows when it displays
  them, and the rows are not stored in the file. Rebuild the common cases (requirement
  tables, allocation and dependency matrices) from the table configuration and the model.
  BASE-001 is fixed, so the configuration is now read (scope, row types, columns).
- **Labels from used projects.** References into used projects (the `proxy.*` entries), such
  as SysML library types, currently show as raw ids. Read the proxy snapshots for their
  labels only, without ingesting their content.
- **`.mdzipx` SVGs.** Link each diagram's SVG to its diagram and use it instead of the
  sketch. This needs a real sample and an SVG rasterizer such as `cairosvg` or `resvg`.
- **Attachments.** Link `BINARY-*` images and documents to the elements that own them, and
  convert PDF and Office attachments to text.
- **Chunk splitting.** Split very large requirement and tagged-value sections so that
  downstream chunkers don't have to.
