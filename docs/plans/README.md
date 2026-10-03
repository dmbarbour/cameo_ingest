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
| [Searching the corpus without tools](keyword-export-2026-10-02.md) | CP1 to CP4 done (0.8.0 to 0.8.3): a workbook and a self-contained search page, made by `cameo-ingest export` from one set of records, sketches in the page optional; the maintainer's trial (CP5) pending | The tentative plan for keyword search and an export; plan RE's finding that embeddings rarely find a requirement by its id |
| [Labels for references outside a project](used-project-labels-2026-10-02.md) | Done (2026-10-02, 0.9.0): raw ids and library fragments in the samples' chunks fell from 17,056 to 3,268; about $1 of LLM requests change at the next live run | The tentative plan for labels from used projects: 12,987 references in the samples read as raw ids or library fragments |
| [Versions of a model, and removing projects](project-versions-2026-10-03.md) | Done (2026-10-03, 0.10.0): `scan`, `projects`, `groups`, `remove`, `restore`; on the samples it finds the TMT pair and nothing else | The maintainer's sources: 282 Cameo files, many of them versions of one model; list projects, group them by shared element ids, remove what isn't wanted |
| [Calibrating sketches to the vision model](vision-calibration-2026-10-03.md) | Done 2026-10-03 (0.12.0: gemma-4's figures as the uncalibrated defaults) | The tentative plan for vision calibration by eye chart: sketch constants found by hand for gemma-4 on DeepInfra |
| [Calibrating to the configured vision model, and validating on real sketches](vision-autocalibration-2026-10-03.md) | Done 2026-10-03 (0.13.0) | Calibration automatic for whichever vision model is configured, with fallbacks rather than gemma-4's values as defaults, and expected quality measured on the tree's own sketches |
| [Sketches that read as drawn, and a release check with the LLM](sketch-ambiguities-2026-10-03.md) | Done 2026-10-03 (0.14.1): trees, frames, labels, reading guides; the release check held retrieval | Plan VA's follow-ups: generalization trees, frames over shapes, label shapes and association-class lines that validation found ambiguous; then one LLM run of the samples, with retrieval, before the real corpus |

## Deferred indefinitely

- **`.mdzipx` SVGs** (maintainer, 2026-10-02): link each diagram's SVG to its diagram and use
  it in place of the sketch. None of the maintainer's 282 Cameo files (125 or more unique) is
  an `.mdzipx`, and no public sample exists. Taken up again only if one turns up.

## Tentative

These plans are not yet written. The last two come from the maintainer; the others come from
the roadmap in the top-level `README.md`.

- **Recompute tables and matrices.** Cameo computes table and matrix rows when it displays
  them, and the rows are not stored in the file. Rebuild the common cases (requirement
  tables, allocation and dependency matrices) from the table configuration and the model.
  BASE-001 is fixed, so the configuration is now read (scope, row types, columns).
- **Attachments.** Link `BINARY-*` images and documents to the elements that own them, and
  convert PDF and Office attachments to text. An image's description could then be asked with
  what owns it: its name, kind and documentation. Today the request says "nothing says which
  element owns it or where it appears" (plan SK, 2026-10-03).
- **Chunk splitting.** Split very large requirement and member sections so that downstream
  chunkers don't have to. Long tagged values are already cut on pages (FU-020).
- **Better module boundaries.** Split sequence diagrams into bands along the time axis, and
  activity diagrams along their partitions (swimlanes, from the model's `inPartition`),
  rather than by connectivity alone. Both were found in plan DV's partitioning study.
- **Keyword search from the command line.** A keyword index of the whole tree, built with the
  output and searchable from the command line. This is for when Python can run where the corpus
  is read. The export for office tools is plan KX (`keyword-export-2026-10-02.md`).
- **Type hierarchies for search** (the maintainer, 2026-10-03: "seems like it might be useful
  if it's something Cameo provides/assumes, esp. for search").
  - **Today:** an element's text gives one level only: a parent lists its direct
    specializations, and a child what it specializes.
  - **The plan:** a chunk per hierarchy, every kind at every level, indented, as plan RF's
    threads do for requirements. Large hierarchies would be cut by subtree. Later, through the
    cross index, the kinds that specialize a shared library type in several models.
  - **The samples:** mostly one level. TMT has 24 hierarchies, 6 of two levels or more, up to 4
    deep, the largest of 53 kinds. Profiles and metamodels are large: NIST_M-SysML has one of
    1,861 kinds, 9 deep. No model has a generalization set.
  - **Cameo's role:** it draws a hierarchy as a tree, but the hierarchy is the model's
    generalizations. Plan SK draws the trees in sketches.

