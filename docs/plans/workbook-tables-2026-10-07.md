# Plan: the workbook as a set of tables, 2026-10-07

- **Status:** In progress: CP1, the trial files are with the maintainer (WT-02).
- **Step prefix:** `WT`, so steps are `WT-01`, `WT-02` and so on.
- **Addresses:** TR-007 (`docs/reviews/trial-2026-10-06.md`), after the Find sheet's removal
  (0.24.2), and the maintainer, 2026-10-07:
  > "Let's attend to other things we could improve assuming a static collection of tables. Some
  > columns for the same sort of grouping information used in search pages could be useful for
  > searches and sorts?"

  > "About page to say how would just mean I'm responsible for doing it manually on one sheet after
  > another. No links to search page. Treat Excel workbook and Search page as independent,
  > stand-alone artifacts. We can eliminate the Search sheet if it isn't used any longer."

  > "let's get that trial file early; I can get you feedback about whether I'm told to
  > recover/repair the file and I can also try the slicers to see if they're what I'm imagining.
  > Then start pushing on the other elements."

## Why

The workbook is a set of tables that people filter, sort and browse with Excel alone. Its column
filters are its search. What helps them: columns that group items (by model version, lineage,
subject, package), Excel Tables (banded rows, headers that stay named), and slicers (always-shown
panels of buttons that filter a table by a column's values).

## What we know

- **No open-source Python writer makes slicers:** XlsxWriter 3.2.9 has none (an open "someday"
  request), nor openpyxl, nor rust_xlsxwriter. Aspose.Cells does, as a commercial .NET library.
- **XlsxWriter refuses Excel Tables in constant-memory mode,** which keeps memory flat on a large
  corpus.
- **Both are parts of the file that can be added after writing** (`.xlsx` is a zip of XML):
  - a table: `xl/tables/tableN.xml`, `<tableParts>` in the sheet, a relationship, a content type;
    the sheet's own autofilter and its `_FilterDatabase` name give way to the table's;
  - a table slicer (Excel 2013 and later, Excel for the web): `xl/slicerCaches/slicerCacheN.xml`
    (`x15:tableSlicerCache`, table id and column id, extension `{2F2917AC-EB37-4324-AD4E-5DD8C200BD13}`),
    `xl/slicers/slicerN.xml`, a drawing whose frame requires `sle15`, the worksheet's slicer list
    (`{3A4CF648-6AED-40f4-86FF-DC5316D8AED3}`), the workbook's slicer caches
    (`{46BE6895-7355-4a93-B00E-2C351335B9C9}`) and a `Slicer_<name>` defined name of `#N/A`. These
    identifiers are EPPlus's, a .NET library whose slicers Excel accepts.
- **Nothing here runs Excel:** LibreOffice opens the file, and ignores slicers. Whether Excel asks
  to repair it is the maintainer's to see.

## Steps

| Step | What | Status |
|---|---|---|
| WT-01 | **The trial file:** `xlsx_parts.py` adds tables and table slicers to a written workbook; `scripts/workbook_trial.py` writes two files from the study tree: every sheet a table, and the same with slicers on the Diagrams sheet (Project, Type, Subject). Well-formedness tests; opened in LibreOffice. | Done: `xlsx_parts.add_parts`; `scripts/workbook_trial.py`, run on the samples-and-fiction tree (9 tables, 3 slicers, 9.5 MB each): every part well formed, every relationship resolved, each table's columns its header row, opened by LibreOffice; `out/workbook-trial/`. `tests/test_catalog.py::test_tables_and_slicers_added` |
| WT-02 | **The maintainer's look:** repair prompts, and whether slicers are what was imagined. | |
| WT-03 | **The Search sheet goes** (its uses went with the Find sheet); the About sheet says what each sheet holds. | |
| WT-04 | **Columns to group, sort and filter by:** on each item's row, the model's newest-version mark and lineage; Subject (the suggested view; elements by their diagrams); Package 1, 2, 3; requirements' Satisfied, Verified and Traced marks and counts; a diagram's Shows and an element's Shown in. | |
| WT-05 | **Every sheet a table,** in the export, by `xlsx_parts`. | |
| WT-06 | **Slicers,** on the sheets and columns the trial settles. | |
| WT-07 | **Docs and release:** design/exports, README; a release check. | |

## Checkpoints

| Checkpoint | Steps | Delivers |
|---|---|---|
| CP1: the trial file | WT-01, WT-02 | Two files for the maintainer to open in Excel |
| CP2: the columns | WT-03, WT-04 | A workbook that groups and filters by model, lineage, subject and package |
| CP3: tables and slicers | WT-05, WT-06, WT-07 | The export, released |

## When to stop and ask

- **Excel asks to repair the trial file:** stop, and find which part it rejects (the
  tables-only file tells tables from slicers).
- **Slicers aren't what the maintainer imagined:** settle what is, before WT-06.
- **The columns double the workbook's size:** report, with which ones cost most.
