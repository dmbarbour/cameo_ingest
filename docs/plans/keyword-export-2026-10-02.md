# Plan: searching the corpus without tools, 2026-10-02

- **Status:** Proposed on 2026-10-02, and revised the same day with the maintainer's answers
  (Decisions). Both formats are built from one set of records, and a trial decides between them.
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

## How the two compare

| | Workbook (`CATALOG.xlsx`) | Search page (`SEARCH.html`) |
|---|---|---|
| **Opening** | In Excel for the web, straight from SharePoint (up to 100 MB), or in desktop Excel | Downloaded, then opened in a browser from disk; it says so on itself |
| **Plain search** | Ctrl+F; a column's filter ("contains", wildcards, two conditions) | A search box, with results as you type |
| **Better search** | A `Find` sheet: words in a cell, and `FILTER`/`SEARCH` formulas list the rows with all of them, ids and names first. This needs Excel 2021, Microsoft 365 or Excel for the web; older Excel shows `#NAME?`. No ranking beyond that, no prefixes or typos. | Ranked search (BM25, as plan RE measured), prefixes (`REQ-1-OAD-10*`), quoted phrases, ids kept whole, ids and names weighted above text, filters by project and kind, snippets with the words highlighted |
| **Browsing** | Sorting and filtering; rows to copy into reports | An item's full text, with its relationships as links to the related items (requirement → satisfier → diagram) and back |
| **Source** | A column | Shown with each item |
| **Scale** | ≈1M rows a sheet; slows beyond tens of MB | Holds everything in memory; load time and memory grow with the corpus (KX-06 measures) |
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

`SEARCH.html` at the tree's root is one file that works offline from disk. It holds its
data as JSON in `<script type="application/json">` blocks, its search code and its styles. It
loads nothing from the network, so nothing leaves the reader's machine; a banner says so, and
says how to open it.
- **Search:** a small engine of our own, a JavaScript port of `harness.BM25`.
  - Its tokens are those of plan RE's measurements, so `REQ-1-OAD-1050` stays one token.
  - Prefix and quoted-phrase queries work, and ids and names weigh more than text.
  - It needs no third-party library, and no licence to carry.
- **Results:** ranked, with filters by project and type, and snippets with the words
  highlighted. Each one opens a detail pane:
  - the item's full text;
  - its relationships, as links to the related items, with back and forward;
  - its source;
  - links to its page and chunk file.
- **Size:** the data is the records' text, the same scope as the workbook. If one file grows
  too slow to load (KX-06), the fallback is one file per project, with a project picker.

## Steps

| Step | What | Status |
|---|---|---|
| KX-01 | **Research** (`docs/research/keyword-export-2026-10-02.md`). | Done |
| KX-02 | **Catalog records** (`catalog.py`, `project_catalog(view, sink)`), written by `TableWriter.write_indices` as `index/catalog.jsonl`. Tests on the fixture and the fiction: a requirement's relations, a summary's model, the scope rule. | |
| KX-03 | **The workbook** (`workbook.py`, XlsxWriter in constant-memory mode). The sheets above, with the cut limits named in one place, and fixed document properties so that the same tree gives the same bytes (BASE-015). | |
| KX-04 | **The search page** (`searchpage.py` writes it; `assets/search.js` and `assets/search.css` are its code).<br>**Engine:** tokenizing, BM25 ranking, prefixes, phrases, field weights and filters.<br>**Interface:** results, detail pane, history.<br>**Tests:** Node unit tests of the engine, on the same small corpus as a Python test of `harness.BM25`, so that the two rank alike (skipped where Node is missing). | |
| KX-05 | **The tree step and settings**: `exports.write_catalog(tree)` in `rebuild`, after `write_rag`, writes both formats from the projects' records, the `rag/meta` chunk map and the state's sightings (paths and `--meta`). `TreeSettings.workbook` and `search_page`, with their flags (`flag_pair`). A README section, "Searching without tools", covers both formats, SharePoint's own search over `rag/text`, and Obsidian or VS Code. | |
| KX-06 | **Measure on the samples** (memory-capped):<br>- the workbook's size, rows and build time;<br>- the page's size, load time and memory in a browser. That needs a measurement script run under Node on the page's data and engine, plus one look in a real browser by the maintainer.<br>Adjust the cut lengths, the scope, or the page's split. | |
| KX-07 | **The maintainer's trial**, on the fiction first, then the samples, with tasks that matter:<br>- find a requirement by its id, and by a few words;<br>- find what satisfies it, and the source file of each;<br>- find which models mention an id;<br>- read a package's summary.<br>Also tried: opening each format from SharePoint (the workbook in the browser, the page downloaded), and SharePoint's own search for `"RWT-REG-001"` over `rag/text`. The maintainer decides what to keep. | |
| KX-08 | **Polish what is kept**, from the trial's notes; drop or switch off what isn't. | |
| KX-09 | **Pages as `.txt`**: only if the trial shows that SharePoint's search should find pages, which it skips as `.md`. | Conditional |

## Checkpoints

| Checkpoint | Steps | Output | Status |
|---|---|---|---|
| CP1: the records and the workbook | KX-02, KX-03, KX-05 (workbook) | `index/catalog.jsonl`, `CATALOG.xlsx`; 0.8.0 | |
| CP2: the search page | KX-04, KX-05 (page) | `SEARCH.html`; 0.8.1 | |
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

- **Size:** the workbook exceeds 100 MB on the samples, or the page takes longer than about ten
  seconds to load, even after cutting text. The maintainer chooses between less text, a file
  per project, or desktop-only use.
- **The trial** shows a need that neither format meets.
