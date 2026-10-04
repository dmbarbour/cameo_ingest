# ADR-0021: Exports for people without tools: a workbook and a self-contained page

- **Status:** Accepted, 2026-10-02 (plan KX; the maintainer's answers). The maintainer's trial is
  pending.
- **Sources:**
  - `docs/archive/plans/keyword-export-2026-10-02.md`;
  - `docs/research/keyword-export-2026-10-02.md`;
  - `docs/research/export-scale-2026-10-02.md`;
  - `docs/design/exports.md`.

## Context

- **Where the corpus is read:** it is shared through SharePoint and read with common office tools;
  "neither Python nor a database can run where it is read".
- **Keyword search:** the RAG service can't do it, and embeddings rarely find a requirement by its
  id.
- **Links:** SharePoint links can't be had for now.

## Decision

- **Two formats from one set of records** (`index/catalog.jsonl`, written by `run`):
  - an Excel workbook;
  - a single, self-contained HTML page that searches in the browser (BM25).

  Downloading the page first is acceptable "so long as it's clear to end users". A trial decides
  between them.
- **A separate command,** `export`, not part of `run`.
- **No links to files:** the exports travel without the tree. Each item carries its text,
  qualified name and source (input path and `--meta`).
- **Scope:** every requirement, diagram and package, and every element with a name or
  documentation. Generated summaries are included, marked with their model.
- **Sketches in the page are optional** (`--sketches webp|svg`, default none), decoded only when
  opened.
- **"Long loads are acceptable, silent ones are not":** every phase shows progress.
- **The same tree gives the same bytes.**

## Consequences

- **The page:** comfortable to about 300,000 items and workable to about 600,000.
- **The workbook:** opens in Excel for the web up to about 780,000 items.
- **Larger corpora** need splitting (KX-11, proposed).
