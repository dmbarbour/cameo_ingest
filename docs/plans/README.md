# Plans

Plans live in `docs/plans/<name>-<YYYY-MM-DD>.md`. Remediation that can be finished before
its review closes is written into the review itself (`docs/reviews/`) and is not listed
here.

## Index

| Plan | Status | Addresses |
|---|---|---|
| [Resumable, content-addressed ingest](resumable-ingest-2026-09-29.md) | Completed 2026-09-29 | BASE-008R1, BASE-016R2, BASE-017R1, BASE-021R1 |
| [Measuring LLM enrichment quality](llm-quality-2026-09-30.md) | LQ-01 to LQ-03 done; judge panel (LQ-04 to LQ-06) deferred | FU-006R1 (and measures fixes for FU-001, FU-002, FU-004, FU-005) |
| [Modular views of large diagrams and packages](diagram-views-2026-09-30.md) | Completed 2026-09-30 | FU-011R1, FU-005R1, FU-012R2 |
| [Retrieval evaluation](retrieval-evaluation-2026-09-30.md) | In progress: plain chunks judged better and made the default (0.5.0); fictional projects with answers by construction (RE-10); the spot check remains | The README's RAG advice; chunk sizes |
| [Related facts brought together](related-facts-2026-10-01.md) | In progress: source files first (RF-01) | The maintainer's request to bring related facts and requirements together for keyword search, tracing and provenance |

## Tentative

These plans are not yet written. The last comes from the maintainer; the others come from the
roadmap in the top-level `README.md`.

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
- **Chunk splitting.** Split very large requirement and member sections so that downstream
  chunkers don't have to. Long tagged values are already cut on pages (FU-020).
- **Better module boundaries.** Split sequence diagrams into bands along the time axis, and
  activity diagrams along their partitions (swimlanes, from the model's `inPartition`),
  rather than by connectivity alone. Both were found in plan DV's partitioning study.
- **Keyword search over the corpus, and an export to search without tools.** (The concordance
  in plan RF, related facts, would cover part of this.) The retrieval
  baseline (`docs/research/retrieval-baseline-2026-10-01.md`) found that embeddings almost never
  find a requirement by its id, where keyword search (BM25) does nine times in ten; but the
  production stack can't take keyword search yet. Investigate:
  - a keyword index of the whole tree, built with the output and searchable from the command
    line;
  - an export that needs no special tools: one workbook for the whole corpus, with ids, names,
    requirement texts, documentation and where each item is (file and anchor), searchable with
    Ctrl+F in Excel. The per-project CSV tables and `LEDGER.md` are a start, but are split by
    project.
- **Vision calibration by "eye chart".** Sketches are drawn for what gemma-4 on DeepInfra is
  known to see: the 645,120-pixel budget, 48-pixel patches, 12-pixel text, and diagrams split
  above 25 shapes (FU-012, FU-015, `docs/research/gemma4-images-2026-09-30.md`). Those values
  were found by hand and hold for one model on one host. The maintainer is building an
  automated eye-chart test in another project (a semantic PDF diff), which measures what a
  vision model can actually read. Once it matures, investigate adopting it here, to calibrate
  the pixel budget, text size, line weights and module thresholds for whichever model and
  endpoint are configured, in place of the gemma-4 constants.
