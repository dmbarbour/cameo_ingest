# Research: a Find sheet that searches on demand, portably across Excel, 2026-10-07

TR-007 (`docs/reviews/trial-2026-10-06.md`): the workbook's Find sheet "should have a search
button and, if feasible, some indicator that it has started and of progress". The maintainer
asked for a solution "relatively portable across Excel versions... if there's an old solution that
has remained stable that should be preferred over a solution tuned to the most recent version".
Web research only (Microsoft's documentation first); nothing here was timed.

## Now

The Find sheet holds one dynamic-array `SORTBY(FILTER(…))` over the Search sheet. It recomputes
on every change to the words, which is slow on a large workbook, gives no sign of work, and
fails as `#NAME?` in Excel 2019 and earlier (FILTER, SORTBY and LET are Excel 2021 and 365).

## What was found

- **No button without macros.** `.xlsm` files are blocked in many organizations and don't run in
  Excel for the web; Office Scripts need setup per user; XlsxWriter's `insert_button` needs VBA.
- **A trigger cell is the portable stand-in.** A Data Validation list (`Off`, `Run`) works in
  every version, on the web and on the Mac. Microsoft 365's in-cell checkbox (2024; XlsxWriter's
  `insert_checkbox`, 3.2.2) shows as TRUE/FALSE elsewhere. A form-control checkbox has no
  XlsxWriter support and can't be used in Excel for the web.
- **Manual calculation mode is a trap.** On the desktop it is one setting for the whole
  application: the first workbook opened sets it, so a manual workbook either opens as automatic,
  or stops the user's other workbooks from recalculating. XlsxWriter's manual mode also leaves
  every formula at its stored value until F9.
- **Excel doesn't prune its recalculation:** everything downstream of a changed cell is computed
  again, even where an intermediate value is the same. So the gate must be `IF(trigger, …)`
  inside every costly formula. A nested `IF` stops early; `AND`, `OR`, `IFS` and `SWITCH`
  evaluate every argument.
- **Old functions extract matching rows well:** a helper column of hits (one `SEARCH` test a
  word, nested `IF`s, the rarest word first), then the first K hits by `INDEX`/`MATCH` from the
  last one found. An exact `MATCH` stops at the first hit, so only as many rows are read as it
  takes to find K. `SMALL` or `AGGREGATE` over a whole column, once an output row, reads it all
  each time. Microsoft's own advice is helper columns in place of large array formulas, and exact
  ranges in place of whole columns.
- **Progress shows only in the desktop status bar** ("Calculating (N threads): x%"). Excel
  redraws after calculating, so no cell can say "searching…" during a search; a cell can say
  what was searched and how many matched, after.
- **Built in, everywhere:** AutoFilter's Text Filters > Contains, and its search box (its list
  shows 10,000 values, but it filters every row); Ctrl+F, Find All (one phrase, in order).
  Advanced Filter is not in Excel for the web.

## The design it points to

| Part | How | Excel |
|---|---|---|
| Trigger | E2, a Data Validation list, `Off` or `Run` | 2010 to 365, web, Mac |
| Words | B2:D2 as now, or one box split by formula | all |
| Search text | written by the tool as a value: Id, Name, Where and Text joined with a separator a word can't span | all |
| Hits | a helper column on the Search sheet: `IF(trigger<>"Run", FALSE, nested IF(ISNUMBER(SEARCH(word, text))…))` | all |
| Results | the first K hits (200), each found by `MATCH(TRUE, …)` from the one before; the columns by `INDEX` | all |
| Status | a cell: "Search is off: set E2 to Run", or "N matches; the first K shown", and the words searched, so that changed words grey the results (conditional formatting) | all |
| Order | the Search sheet's own order, which the tool can make best-first; no ranking by score, which would read every match | all |
| Fallback, written on the sheet | AutoFilter on the Search sheet; Ctrl+F | all |

## Not known

- **Speed:** nothing was timed at 100,000 to 1,000,000 rows (SEARCH on joined text against FIND
  on lowered text; helper columns against a gated FILTER), nor the file size that a million
  helper formulas add (Excel for the web opens at most 100 MB).
- **Progress outside the Windows desktop,** on the web or the Mac.
- **Wildcards:** SEARCH and MATCH read `*`, `?` and `~` as wildcards; typed ones need escaping.
- Our own Excel is LibreOffice, which has INDEX, MATCH and SEARCH but not FILTER: the design can
  be tested there for correctness, but its speed in Excel is for the maintainer's trial.

## Sources

- Microsoft: [How Excel determines the calculation mode](https://learn.microsoft.com/en-us/troubleshoot/microsoft-365-apps/excel/current-mode-of-calculation);
  [Change formula recalculation](https://support.microsoft.com/en-us/office/change-formula-recalculation-iteration-or-precision-in-excel-73fc7dac-91cf-4d36-86e8-67124f6bcce4);
  [Improving calculation performance](https://learn.microsoft.com/en-us/office/vba/excel/concepts/excel-performance/excel-improving-calculation-performance);
  [Tips for optimizing performance obstructions](https://learn.microsoft.com/en-us/office/vba/excel/concepts/excel-performance/excel-tips-for-optimizing-performance-obstructions);
  [Using check boxes in Excel](https://support.microsoft.com/en-us/excel/using-check-boxes-in-excel);
  [Form controls](https://support.microsoft.com/en-us/excel/form-controls);
  [Filter by using advanced criteria](https://support.microsoft.com/en-us/excel/filter-by-using-advanced-criteria);
  [Filter data in a range or table](https://support.microsoft.com/en-us/office/filter-data-in-a-range-or-table-01832226-31b5-4568-8806-38c37dcc180e);
  [Excel for the web service description](https://learn.microsoft.com/en-us/office365/servicedescriptions/office-online-service-description/excel-online);
  [Excel status bar options](https://support.microsoft.com/en-us/office/excel-status-bar-options-6055ecd9-e20f-4a7a-a611-4481bd488c55).
- FastExcel, [short-circuiting IF, CHOOSE, IFS and SWITCH](https://fastexcel.wordpress.com/2023/01/03/short-circuiting-excel-formulas-if-choose-ifs-and-switch/).
- XlsxWriter: [data validation](https://xlsxwriter.readthedocs.io/working_with_data_validation.html),
  [formulas](https://xlsxwriter.readthedocs.io/working_with_formulas.html),
  [checkboxes](https://xlsxwriter.readthedocs.io/example_checkbox.html),
  [autofilters](https://xlsxwriter.readthedocs.io/working_with_autofilters.html).

## Changes
