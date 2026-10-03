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
| [Related facts brought together](related-facts-2026-10-01.md) | Completed 2026-10-01; facet lists deferred | The maintainer's request to bring related facts and requirements together for keyword search, tracing and provenance |
| [Refactoring after the architecture review](refactoring-2026-10-02.md) | Done (2026-10-02, 0.7.2): every checkpoint checked; every review finding fixed; retrieval held; the new summaries adopted | AR-003R2 to AR-026: stages 2 to 4 of the review's remediation order, with the maintainer's decisions (Markdown chunks, studies and old templates retired; `cameo-ingest[eval]`) |
| [Searching the corpus without tools](keyword-export-2026-10-02.md) | Proposed 2026-10-02, revised with the maintainer's answers: a workbook and a self-contained search page, made by `cameo-ingest export` from one set of records; sketches in the page an experiment; then a trial | The tentative plan for keyword search and an export; plan RE's finding that embeddings rarely find a requirement by its id |
| [Labels for references outside a project](used-project-labels-2026-10-02.md) | Done (2026-10-02, 0.9.0): raw ids and library fragments in the samples' chunks fell from 17,056 to 3,268; about $1 of LLM requests change at the next live run | The tentative plan for labels from used projects: 12,987 references in the samples read as raw ids or library fragments |

## Deferred indefinitely

- **`.mdzipx` SVGs** (maintainer, 2026-10-02): link each diagram's SVG to its diagram and use
  it in place of the sketch. None of the maintainer's 282 Cameo files (125 or more unique) is
  an `.mdzipx`, and no public sample exists. Taken up again only if one turns up.

## Tentative

These plans are not yet written. The last comes from the maintainer; the others come from the
roadmap in the top-level `README.md`.

- **Recompute tables and matrices.** Cameo computes table and matrix rows when it displays
  them, and the rows are not stored in the file. Rebuild the common cases (requirement
  tables, allocation and dependency matrices) from the table configuration and the model.
  BASE-001 is fixed, so the configuration is now read (scope, row types, columns).
- **Attachments.** Link `BINARY-*` images and documents to the elements that own them, and
  convert PDF and Office attachments to text.
- **Chunk splitting.** Split very large requirement and member sections so that downstream
  chunkers don't have to. Long tagged values are already cut on pages (FU-020).
- **Better module boundaries.** Split sequence diagrams into bands along the time axis, and
  activity diagrams along their partitions (swimlanes, from the model's `inPartition`),
  rather than by connectivity alone. Both were found in plan DV's partitioning study.
- **Keyword search from the command line.** A keyword index of the whole tree, built with the
  output and searchable from the command line. This is for when Python can run where the corpus
  is read. The export for office tools is plan KX (`keyword-export-2026-10-02.md`).
- **Vision calibration by "eye chart".** Sketches are drawn for what gemma-4 on DeepInfra is
  known to see: the 645,120-pixel budget, 48-pixel patches, 12-pixel text, and diagrams split
  above 25 shapes (FU-012, FU-015, `docs/research/gemma4-images-2026-09-30.md`). The
  maintainer's `semantic_pdf_diff` now has a stable eye chart, surveyed in
  `docs/research/eye-chart-reuse-2026-10-02.md`.
  - **Its findings:** the budget is right for gemma-4. The text has a 1.2–1.6× margin. Our
    arrowheads may be small enough to be read reversed now and then.
  - **The proposal:** a `calibrate-vision` command, from about 350 lines adapted to Pillow (not
    PyMuPDF, which is AGPL). It would draw about 56 cards in the sketches' own terms and derive
    the budget, font, arrowhead, line and module settings for the configured model, at a few
    cents a run.
