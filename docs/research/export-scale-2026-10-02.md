# Research: how large a corpus the exports can hold, 2026-10-02

**Question.** The maintainer has about 125 unique Cameo models (282 files), and suspects that
all of them will not fit one search page or workbook. At what size do the exports of plan KX
(`CATALOG.xlsx`, `SEARCH.html`) stop being usable, and what should be done beyond it?

**Method.**
- **The corpus:** the catalogs of the samples and the fiction with their LLM summaries
  (`out/kx/llm`: 27 models, 74,407 items), copied 1, 2, 4, 8 and 16 times.
  - In each copy, every id-like token gets a suffix (`REQ-1-OAD-1050-R3`), in every text, so
    that each copy brings ids of its own, as new models would.
  - Ordinary words are shared between copies. A real corpus has a larger vocabulary, but the
    index's memory is mostly postings and text, which this models.
- **The exports:** written by the library's own writers.
- **The browser:** each page opened in headless Chrome, in real time, driven over the DevTools
  protocol.
  - **Recorded:** when the HTML was parsed, the page's own phase timings, five searches, the JS
    heap, and the peak memory of the cgroup holding Chrome and the driver.
  - **Limits:** Chrome was capped at 5 GB, and everything ran at low priority beside other work.
    Repeated runs differ by up to about 30%.
- **The scripts:** `scale.py`, `scale_browser.js` and `scale_series.sh`, kept in the session's
  scratch space. The method is all here, so that the series can be redone.

## Results

**The search page:**

| Copies | Models | Items | File | Export | Ready in | Unpacking | Indexing | JS heap | Peak (Chrome) |
|---|---|---|---|---|---|---|---|---|---|
| 1 | 27 | 74,407 | 9.6 MB | 10 s | 3.9 s | 1.0 s | 2.5 s | 168 MB | 0.9 GB |
| 2 | 54 | 148,814 | 19 MB | 22 s | 6.7 s | 2.1 s | 4.0 s | 341 MB | 1.1 GB |
| 4 | 108 | 297,628 | 38 MB | 75 s | 14.7 s | 4.1 s | 9.2 s | 797 MB | 2.0 GB |
| 8 | 216 | 595,256 | 76 MB | 149 s | 29.1 s | 8.4 s | 18.0 s | 1.3 GB | 3.2 GB |
| 16 | 432 | 1,190,512 | 153 MB | 199 s | 47.6 s | 18.6 s | 25.4 s | 2.7 GB | 5.2 GB (the cap was 5.4) |

- **The HTML parses fast:** the browser reads even 153 MB in about 2 s. Unpacking and indexing
  are the cost, and the page shows both as they happen.
- **Searching stays fast at every size:** an id in 0.01–0.02 s, a prefix in 0.01–0.03 s.
  Common words ("the system shall", 819,000 hits at 16 copies) take 0.5 s, and a phrase 0.7 s.
- **SVG sketches** add about half to the file (117 MB against 76 MB at 8 copies). They add
  little to load time and memory, since they are decoded only when opened.
- **Roughly:** loading takes about 50 µs per item on this machine, and the browser about
  650 MB plus 3.8 KB per item.

**The workbook:**

| Copies | `Search` rows | File | Export | Export memory |
|---|---|---|---|---|
| 1 | 74,407 | 9.5 MB | 21 s | 202 MB |
| 2 | 148,814 | 19 MB | 35 s | 238 MB |
| 4 | 297,628 | 38 MB | 75 s | 239 MB |
| 8 | 595,256 | 76 MB | 144 s | 239 MB |
| 16 | 1,048,575, cut short at Excel's limit (of 1,190,512) | 145 MB | 265 s | 243 MB |

- **Its size grows** by about 128 bytes an item.
- **Excel for the web opens it from SharePoint up to 100 MB,** which is about 780,000 items.
  Desktop Excel has no such limit, but grows slow with a file this size.
- **The `Search` sheet stops at 1,048,575 rows,** and the `About` sheet says so.

**What makes a corpus large: the items, not the number of models or their size.**

| | |
|---|---|
| Items per model in the samples | median 269, mean 2,756 |
| The two TMT models | 27,409 and 26,330 items, 72% of all |
| NIST's model, 2.8 MB | 10,751 items |
| A 14 MB library | 574 items |
| Items per MB of `.mdzip` | from 40 to 3,900, so file size predicts little |

The `Projects` sheet, and `export`'s report, give each model's items once it is ingested.

## What scale is viable

| Items | Search page | Workbook |
|---|---|---|
| Up to about 300,000 | Comfortable: ready in about 15 s here, 2 GB in the browser | Comfortable: under 40 MB, opens on the web |
| 300,000–600,000 | Workable on a PC with 8 GB or more: about 30 s, 3 GB | Works on the web up to about 780,000 items |
| Beyond that | Split: a minute or more, and 4–5 GB, too much for an ordinary office PC with other work open | Split, or desktop only; the `Search` sheet is cut at 1.05 million |

**Assumptions:**
- An older office PC may take one and a half to two times as long as this machine.
- Memory is what fails first: a browser tab that runs out of memory crashes. A long wait, by
  contrast, shows its progress.

**For the maintainer's corpus,** if its 125 models were like the samples on average (2,756 items),
it would hold about 345,000 items. That is at the edge of comfortable for the page and well
within the workbook's limits. A handful of TMT-sized models would double that, though, so the
corpus's own count decides: ingest it, then read the item counts that `export` reports.

## Splitting beyond that

The models come from several companies competing for one contract, so groups are natural.
- **One export per group:** chosen by an ingest `--meta` value (`--meta vendor=…`), or by the
  input folder, which mirrors SharePoint's.
- **A whole-corpus identifier index across the groups,** so that "which models mention
  REQ-…" still has one answer. It is small: 9,600 records for the samples.

`export --group-by meta:KEY|folder` would write one page or workbook per group, and a
corpus-wide identifier index. That is not built yet; it is proposed in plan KX.
