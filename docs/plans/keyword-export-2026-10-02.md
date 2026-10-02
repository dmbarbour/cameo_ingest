# Plan: searching the corpus without tools, 2026-10-02

- **Status:** Proposed on 2026-10-02, and revised twice the same day with the maintainer's
  answers (Decisions). Both formats are built from one set of records, and a trial decides
  between them. The page ships as one file, with an optional bundle beside it.
- **Step prefix:** `KX`, so steps are `KX-01`, `KX-02` and so on
- **Addresses:** the tentative plan "Keyword search over the corpus, and an export to search
  without tools" (plan index). The maintainer's constraints, 2026-10-02:
  - the corpus is shared through SharePoint and read with common office tools;
  - neither Python nor a database can run where it is read;
  - their RAG service takes uploads, but can't do keyword search;
  - there are no links to SharePoint sources for now. The folder layout and the metadata given
    when the Cameo files are ingested preserve SharePoint's structure instead.
- **Research:** `docs/research/keyword-export-2026-10-02.md` (KX-01).
- **Related:** plan RE, whose baseline found that keyword search finds requirements by id where
  embeddings don't. Plan RF's index across models (`index/ids.jsonl`) is one of the record kinds.

## Decisions

| # | Question | Decision |
|---|---|---|
| 1 | The format | **Both, prototyped, then a trial** (maintainer, 2026-10-02: "let's not entirely strike the other approach yet"). A workbook, and a static search page that people download and open, which is acceptable "so long as it's clear to end users". The two share the records of KX-02, so that each is a thin writer. The maintainer's trial (KX-07) decides which to keep and polish, or keeps both. |
| 2 | Links | **No SharePoint addresses** (maintainer, 2026-10-02). Links are relative: they work in desktop Excel, and in the page, when the tree is downloaded or synced. Each item shows its **source**: the input file's path, which mirrors SharePoint's folders, and the input's `--meta` values. That serves the maintainer's tracing priority, "requirements to source files". |
| 3 | What an item links to | **Its page**, and **its chunk's `rag/text` file** when `rag/` is part of the tree: the exact text, which SharePoint previews and indexes (proposed). |
| 4 | Which elements | **Every element with a name or documentation**, plus every requirement, diagram and package. Unnamed structural items (literals, instance values, unnamed pins and the like) are left out and counted (proposed). |
| 5 | Generated text | **Included and marked**: package summaries and diagram descriptions, each saying which model wrote it (proposed). |
| 6 | Switches | **Tree-wide, applied on every run**: `--workbook/--no-workbook` and `--search-page/--no-search-page`, both on for the trial (proposed). The workbook adds one dependency, XlsxWriter (pure Python, BSD licence); the page adds none. |
| 7 | How the page ships | **One self-contained file, with a bundle optional** (maintainer, 2026-10-02: a zip "to ensure everything is grouped together", or "one big file with all JavaScript and data embedded"; distributing the tree is acceptable "if it helps and works").<br>**The file:** `SEARCH.html` holds all the corpus's text, gzipped inline, about 8 MB on the samples, so one download and a double-click suffice.<br>**The bundle:** a zip of the page with the sketches, and the pages if wanted, made by a command (`cameo-ingest bundle`). Inside an extracted bundle, the page finds them and shows sketches and opens pages. SharePoint's folder download stops at 10,000 files, so the bundle is one zip file of our own. |
| 8 | Waiting | **Long loads are acceptable, silent ones are not** (maintainer, 2026-10-02). The page says what it is doing from its first moment: each phase (reading, decompressing, parsing, indexing) with a progress bar and its time, then a summary of where the time went. Every search shows its count and time. |

## How the two compare

| | Workbook (`CATALOG.xlsx`) | Search page (`SEARCH.html`) |
|---|---|---|
| **Opening** | In Excel for the web, straight from SharePoint (up to 100 MB), or in desktop Excel | Downloaded (one file of about 8 MB, or the bundle, extracted), then opened in a browser; it says so on itself |
| **Plain search** | Ctrl+F; a column's filter ("contains", wildcards, two conditions) | A search box, with results as you type |
| **Better search** | A `Find` sheet: words in a cell, and `FILTER`/`SEARCH` formulas list the rows with all of them, ids and names first. This needs Excel 2021, Microsoft 365 or Excel for the web; older Excel shows `#NAME?`. No ranking beyond that, no prefixes or typos. | Ranked search (BM25, as plan RE measured), prefixes (`REQ-1-OAD-10*`), quoted phrases, ids kept whole, ids and names weighted above text, filters by project and kind, snippets with the words highlighted |
| **Browsing** | Sorting and filtering; rows to copy into reports | An item's full text, with its relationships as links to the related items (requirement → satisfier → diagram) and back |
| **Source** | A column | Shown with each item |
| **Scale** | ≈1M rows a sheet; slows beyond tens of MB | All text in about 8 MB gzipped; load time and memory grow with the corpus, shown as it loads (KX-06 measures) |
| **Familiar** | Everyone knows Excel | A web page, but new |
| **Our cost** | A writer in Python | A writer in Python, plus about 300 lines of JavaScript (search, layout), tested with Node |

## The records (shared)

`index/catalog.jsonl` in each project holds one record per item, made at build time from the
in-memory model with the vocabulary of `semantics` (labels, kind words, requirement ids,
relationship wording, as on the pages). It is the only input either format takes from a project
(AR-012: no reading of CSV tables or rendered text). Each record has:
- **Identity:** `key` (element id), `type` (requirement, element, diagram, package, summary),
  `kind` (kind word), `id` (a requirement's id), `db` (its database number), `name`, `where`
  (qualified name).
- **Text:** `text` (requirement text, documentation, or a generated summary with its model),
  `stereotypes`.
- **Relations:** `relations`, as `[wording, other key, other label]` (satisfied by, verifies,
  derives from…), and `diagrams` (the diagrams showing it).
- **Links:** `page` (project-relative file and anchor) and `chunk` (main chunk id).

The tree step adds the project's label and source (input paths and `--meta` values), and maps
`chunk` to its `rag/text` file.

## The workbook

Every sheet has a frozen header row and an AutoFilter. Text is written as text, never as a
formula or number, so that an id like `1.2.3`, or a text starting with `=`, stays as written.
Long text is cut, with "…", and the links lead to the rest. Links are `HYPERLINK()` formulas
with relative paths, which aren't limited in number per sheet.

| Sheet | One row per | Columns |
|---|---|---|
| `About` | | What the workbook is; how to search (desktop: Ctrl+F, Options, Within: Workbook; on the web: `Search` or `Find`); what "generated" means; the tool's version; the items left out, with counts |
| `Find` | (formulas) | Words in B1, and optionally a project and a type. A `FILTER` lists the matching rows of `Search`, those whose id or name holds a word first. |
| `Search` | item in scope | Type, Id, Name, Project, Where, Text, Source, Link. Everything findable from one sheet. |
| `Requirements` | requirement | Id, Database number, Name, Text, Project, Package, Satisfied by, Verified by, Derives from, Derived by, Refined by, Other relationships, Diagrams, Source, Link |
| `Identifiers` | identifier and element | Id, Project, Element, Kind, How (its id, in its text, satisfies it…), Snippet, Link |
| `Elements` | element in scope | Kind, Name, Where, Project, Stereotypes, Documentation, Link |
| `Relationships` | relationship | Source element, Relationship (as worded on the pages), Target element, Stereotype, Project |
| `Diagrams` | diagram | Name, Type, Owner, Project, Shapes, Description (generated), Link |
| `Summaries` | generated summary | Of, Project, Summary, Model, Link |
| `Projects` | project | Project (file name), Label (`TMT [9ffd7a2c]`), Content sha256, Source paths, Metadata, Saved by, counts, README link |

## The search page

`SEARCH.html` at the tree's root is one file. It works offline, opened from disk, loads nothing
from the network, and sends nothing anywhere; a banner says so, and how to open it. Its design
follows what browsers allow a page opened from disk (research, 2026-10-02):
- classic scripts and relative links work;
- `fetch`, ES modules and workers don't;
- storage is unreliable, so nothing is cached between visits.

**Data.** The records of every project, with each item's full chunk text, as JSON, gzipped and
base64-encoded inside the page. That is about 8 MB for the samples' 52 MB of text.
`DecompressionStream` unpacks it, which every current browser has. The page holds one block
per project, so that parsing and indexing advance a project at a time.

**Loading, with feedback from the first moment:**
- **Before any script runs:** the top of the file is a plain message, with a pure-CSS animation:
  "Loading the search index: 26 models, 120,000 items…". The data comes after it in the file,
  so the message shows while the browser reads the rest.
- **The phases:** decompressing, parsing and indexing each have a progress bar, with the project
  in hand, the items done and the time so far. The work goes in slices of about 30 ms, so that
  the bars repaint, and the page answers clicks (a Cancel button, at least).
- **When ready:** "120,000 items from 26 models, ready in 6.2 s (decompressing 0.4, parsing 1.9,
  indexing 3.9)".
- **If loading fails or stalls:** a phase that makes no progress for some seconds says which
  one, and what to try. If the browser lacks `DecompressionStream`, the page says which
  browsers work.

**Search.** A small engine of our own, a JavaScript port of `harness.BM25`:
- **Tokens:** those of plan RE's measurements, so `REQ-1-OAD-1050` stays one token.
- **Queries:** prefixes (`REQ-1-OAD-10*`) and quoted phrases work, and ids and names weigh more
  than text.
- **Results:** filters by project and type, and each search shows its count and time.
- **No third-party library,** and no licence to carry.

**Reading.** Results are ranked, with snippets that highlight the words. Each one opens a detail
pane:
- the item's full text;
- its relationships, as links to the related items, with back and forward;
- its source (input path and `--meta` values);
- its page and sketch, when the bundle is there.

**The bundle.**
- **What it holds:** `cameo-ingest bundle TREE ZIP` writes a zip with `SEARCH.html` at its top,
  the sketches, the pages if `--with-pages` is given, and a small `bundle.js` that marks them as
  present.
- **How the page finds it:** it loads `bundle.js` with a classic script tag. If the script is
  there, sketches and page links switch on; if not, the page says they come with the bundle.
- **Zip preview:** a page opened from Windows' zip preview, which extracts it alone into a
  temporary folder, notices its path and asks for "Extract All".

## Steps

| Step | What | Status |
|---|---|---|
| KX-01 | **Research** (`docs/research/keyword-export-2026-10-02.md`). | Done |
| KX-02 | **Catalog records** (`catalog.py`, `project_catalog(view, sink)`), written by `TableWriter.write_indices` as `index/catalog.jsonl`. Tests on the fixture and the fiction: a requirement's relations, a summary's model, the scope rule. | |
| KX-03 | **The workbook** (`workbook.py`, XlsxWriter in constant-memory mode). The sheets above, with the cut limits named in one place, and fixed document properties so that the same tree gives the same bytes (BASE-015). | |
| KX-04 | **The search page.** `searchpage.py` writes it; its code is in `assets/` (`search.js`, `search.css`, the page's template).<br>**Data:** per-project blocks, gzipped and base64-encoded.<br>**Loading:** the early message, the phases with progress bars and timings, slices of about 30 ms, Cancel, stall and capability messages, and the summary.<br>**Engine:** tokenizing, BM25 ranking, prefixes, phrases, field weights, filters.<br>**Interface:** results with snippets, the detail pane, history, the bundle check, the zip-preview check.<br>**Tests:** Node unit tests of the engine on a small corpus that a Python test also ranks with `harness.BM25`, so the two rank alike; a Node test that decodes a page's data blocks back into the records; skipped where Node is missing. | |
| KX-04b | **The bundle**: `cameo-ingest bundle TREE ZIP [--with-pages]`, a command rather than a switch, since it is a distribution step. It writes the page, the sketches, `bundle.js` and, if asked, the pages, keeping their paths. Tests: a bundle of the fiction holds what it should, and the page's links resolve inside it. | |
| KX-05 | **The tree step and settings**: `exports.write_catalog(tree)` in `rebuild`, after `write_rag`, writes both formats from the projects' records, the `rag/meta` chunk map and the state's sightings (paths and `--meta`). `TreeSettings.workbook` and `search_page`, with their flags (`flag_pair`). A README section, "Searching without tools", covers both formats, SharePoint's own search over `rag/text`, and Obsidian or VS Code. | |
| KX-06 | **Measure on the samples** (memory-capped):<br>- the workbook's size, rows and build time;<br>- the page's size, and its time per phase (decompressing, parsing, indexing) under Node, on the page's own data and engine;<br>- the bundle's size.<br>The maintainer then takes one look at the page in their own browser, to compare its timings with Node's. Adjust the cut lengths, the scope, or the slices from what that shows. | |
| KX-07 | **The maintainer's trial**, on the fiction first, then the samples, with tasks that matter:<br>- find a requirement by its id, and by a few words;<br>- find what satisfies it, and the source file of each;<br>- find which models mention an id;<br>- read a package's summary.<br>Also tried: opening each format from SharePoint (the workbook in the browser, the page downloaded), and SharePoint's own search for `"RWT-REG-001"` over `rag/text`. The maintainer decides what to keep. | |
| KX-08 | **Polish what is kept**, from the trial's notes; drop or switch off what isn't. | |
| KX-09 | **Pages as `.txt`**: only if the trial shows that SharePoint's search should find pages, which it skips as `.md`. | Conditional |

## Checkpoints

| Checkpoint | Steps | Output | Status |
|---|---|---|---|
| CP1: the records and the workbook | KX-02, KX-03, KX-05 (workbook) | `index/catalog.jsonl`, `CATALOG.xlsx`; 0.8.0 | |
| CP2: the search page | KX-04, KX-04b, KX-05 (page) | `SEARCH.html`, `cameo-ingest bundle`; 0.8.1 | |
| CP3: the samples | KX-06 | Measurements, and adjustments | |
| CP4: the trial | KX-07, KX-08, KX-09 if needed | What the maintainer keeps | |

**Checks:**
- **The workbook** (CP1), read in tests with `zipfile`:
  - its sheets and their row counts;
  - a known requirement row;
  - a text starting with `=` stored as a string;
  - relative links;
  - the same bytes twice.
- **The page** (CP2):
  - Node tests of the engine: tokens, ranking against `harness.BM25`, prefixes, phrases,
    filters;
  - a Python test that the page's JSON holds the records;
  - the same bytes twice.
- **Each checkpoint:**
  - the rest of the tree unchanged (`treediff`, `--no-llm`);
  - every project made again once, from the LLM store, at no cost.

## When to stop and ask

- **Size:** the workbook exceeds 100 MB on the samples even after cutting text. The maintainer
  chooses between less text, a workbook per project, or desktop-only use.
- **The page's memory or load** grows past what an ordinary office PC copes with, say over a
  minute or over 2 GB on the samples. Long loads are acceptable while their progress shows.
- **The trial** shows a need that neither format meets.
