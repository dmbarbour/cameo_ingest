# Plan: searching the corpus without tools, 2026-10-02

- **Status:** Proposed on 2026-10-02, and revised the same day with the maintainer's answers
  (Decisions).
  - Both formats, a workbook and a self-contained search page, come from one set of records.
  - A separate command makes them, and a trial decides between them.
  - Sketches in the page are an experiment.
- **Step prefix:** `KX`, so steps are `KX-01`, `KX-02` and so on
- **Addresses:** the tentative plan "Keyword search over the corpus, and an export to search
  without tools" (plan index). The maintainer's constraints, 2026-10-02:
  - the corpus is shared through SharePoint and read with common office tools;
  - neither Python nor a database can run where it is read;
  - their RAG service takes uploads, but can't do keyword search;
  - there are no links to SharePoint sources for now. The folder layout and the metadata given
    when the Cameo files are ingested preserve SharePoint's structure instead.
- **Research:** `docs/research/keyword-export-2026-10-02.md` (KX-01): Excel, SharePoint, and what
  browsers allow a page opened from disk.
- **Related:** plan RE, whose baseline found that keyword search finds requirements by id where
  embeddings don't. Plan RF's index across models (`index/ids.jsonl`) is one of the inputs.

## Decisions

All from the maintainer, 2026-10-02, unless marked proposed.

| # | Question | Decision |
|---|---|---|
| 1 | The format | **Both, then a trial.** A workbook, and a static search page that people download and open, which is acceptable "so long as it's clear to end users". Neither approach is struck until the trial (KX-08). |
| 2 | Links to files | **None.** The exports travel alone, without the tree: chunk files and pages "would only be on my machine". Each item carries what a reader needs: its text (in full in the page, cut in the workbook), its qualified name, and its **source**, the input file's path, which mirrors SharePoint's folders, and its `--meta` values. That serves the tracing priority, "requirements to source files". |
| 3 | Which elements | **Every element with a name or documentation**, plus every requirement, diagram and package. Unnamed structural items are left out and counted. |
| 4 | Generated text | **Included and searched**: package summaries and diagram descriptions, marked with the model that wrote them. They help find what a model is *about*, "even if it's weaker than embeddings and rerankers". |
| 5 | How the exports are made | **A separate, documented command**, not part of `run`: `cameo-ingest export TREE`, with `--workbook FILE`, `--search-page FILE` and `--sketches …`. The records it reads are made during `run` (KX-02), since they need the in-memory model; they are small. |
| 6 | Sketches in the page | **An experiment** (KX-05): "include sketches even in the single-file format if not cost-prohibitive". Two candidates, measured on the samples, and the maintainer chooses:<br>- **WebP:** the existing PNG sketches, re-encoded losslessly. That is 17 MB for all 3,666, half the PNGs' 34 MB, and 23 MB inside the page. The page would be about 30 MB in all.<br>- **SVG:** sketches drawn as vectors from the diagram's graph. They are sharp at any zoom, likely smaller once gzipped, and each shape can open its element in the page. They need a second renderer, in Python, beside `sketch`.<br>Either way, a sketch is decoded only when someone opens it. |
| 7 | Waiting | **Long loads are acceptable, silent ones are not.** The page says what it is doing from its first moment: each phase with a progress bar and its time, then a summary of where the time went. Every search shows its count and time. |
| 8 | A zip bundle (the page beside pages and sketches) | **Deferred.** With the text and sketches inside the page, a bundle adds little but pages, whose text the page already holds. Taken up again if the trial asks for it. |
| 9 | Dependency | **XlsxWriter**, for the workbook (pure Python, BSD licence), proposed. The page needs no library: its search engine is ours. |

## How the two compare

| | Workbook (`CATALOG.xlsx`) | Search page (`SEARCH.html`) |
|---|---|---|
| **Opening** | In Excel for the web, straight from SharePoint (up to 100 MB), or in desktop Excel | Downloaded (one file: about 8 MB of text, about 30 MB with WebP sketches), then opened in a browser; it says so on itself |
| **Plain search** | Ctrl+F; a column's filter ("contains", wildcards, two conditions) | A search box, with results as you type |
| **Better search** | A `Find` sheet: words in a cell, and `FILTER`/`SEARCH` formulas list the rows with all of them, ids and names first. This needs Excel 2021, Microsoft 365 or Excel for the web; older Excel shows `#NAME?`. No ranking beyond that, and no prefixes or typos. | Ranked search (BM25, as plan RE measured), prefixes (`REQ-1-OAD-10*`), quoted phrases, ids kept whole, ids and names weighted above text, filters by project and kind, snippets with the words highlighted |
| **Browsing** | Sorting and filtering; rows to copy into reports | An item's full text, with its relationships as links to the related items (requirement → satisfier → diagram) and back; sketches |
| **Source** | A column | Shown with each item |
| **Familiar** | Everyone knows Excel | A web page, but new |
| **Our cost** | A writer in Python | A writer in Python, plus about 400 lines of JavaScript (loading, search, layout), tested with Node |

## The records (shared)

`index/catalog.jsonl` in each project holds one record per item. `run` makes it at build time,
from the in-memory model, with the vocabulary of `semantics`: labels, kind words, requirement
ids and relationship wording, as on the pages. It is the only input either export takes from a
project (AR-012: no reading of CSV tables or rendered text). Each record has:
- **Identity:** `key` (element id), `type` (requirement, element, diagram, package, summary),
  `kind` (kind word), `id` (a requirement's id), `db` (its database number), `name`, `where`
  (qualified name).
- **Text:** `text` (requirement text, documentation, or a generated summary), `model` (for
  generated text), `stereotypes`.
- **Relations:** `relations`, as `[wording, other key, other label]` (satisfied by, verifies,
  derives from…), and `diagrams` (the diagrams showing it).
- **Chunks:** `chunks`, the ids of the item's chunks (its main chunk and its details). The page
  shows their text as the item's full text, as the RAG sees it.

`export` adds each project's label and source (input paths and `--meta` values, from the
state) and, for the page, the chunks' text (from `index/chunks.jsonl`) and the sketches.

## The workbook

Every sheet has a frozen header row and an AutoFilter. Text is written as text, never as a
formula or number, so that an id like `1.2.3`, or a text starting with `=`, stays as written.
Long text is cut, with "…" and a note that the page holds it whole.

| Sheet | One row per | Columns |
|---|---|---|
| `About` | | What the workbook is; how to search (desktop: Ctrl+F, Options, Within: Workbook; on the web: `Search` or `Find`); what "generated" means; the tool's version; the items left out, with counts |
| `Find` | (formulas) | Words in B1, and optionally a project and a type. A `FILTER` lists the matching rows of `Search`, those whose id or name holds a word first. |
| `Search` | item in scope | Type, Id, Name, Project, Where, Text, Source. Everything findable from one sheet. |
| `Requirements` | requirement | Id, Database number, Name, Text, Project, Package, Satisfied by, Verified by, Derives from, Derived by, Refined by, Other relationships, Diagrams, Source |
| `Identifiers` | identifier and element | Id, Project, Element, Kind, How (its id, in its text, satisfies it…), Snippet |
| `Elements` | element in scope | Kind, Name, Where, Project, Stereotypes, Documentation |
| `Relationships` | relationship | Source element, Relationship (as worded on the pages), Target element, Stereotype, Project |
| `Diagrams` | diagram | Name, Type, Owner, Project, Shapes, Description (generated) |
| `Summaries` | generated summary | Of, Project, Summary, Model |
| `Projects` | project | Project (file name), Label (`TMT [9ffd7a2c]`), Content sha256, Source paths, Metadata, Saved by, counts |

## The search page

`SEARCH.html` is one file that works offline, opened from disk. It loads nothing from the
network and sends nothing anywhere; a banner says so, and how to open it. Its design follows
what browsers allow a page opened from disk (research, 2026-10-02):
- inline scripts work;
- `fetch`, ES modules and workers don't;
- storage is unreliable, so nothing is cached between visits.

**Data.** One block per project inside the page, gzipped and base64-encoded:
- its records, with their chunks' text: about 8 MB for the samples' 52 MB of text;
- its sketches, if `--sketches` asks for them, as separate blocks decoded only on demand.

`DecompressionStream`, which every current browser has, unpacks the blocks.

**Loading, with feedback from the first moment:**
- **Before any script runs:** the top of the file is a plain message, with a pure-CSS animation:
  "Loading the search index: 26 models, 120,000 items…". The data comes after it in the file,
  so the message shows while the browser reads the rest.
- **The phases:** decompressing, parsing and indexing each have a progress bar, with the project
  in hand, the items done and the time so far. The work goes in slices of about 30 ms, so that
  the bars repaint and the page answers clicks (a Cancel button, at least).
- **When ready:** "120,000 items from 26 models, ready in 6.2 s (decompressing 0.4, parsing 1.9,
  indexing 3.9)".
- **If loading fails or stalls:**
  - a phase that makes no progress for some seconds says which one, and what to try;
  - a browser without `DecompressionStream` is told which browsers work;
  - a page opened from Windows' zip preview, which copies the file alone into a temporary
    folder, notices its path and says to save or extract it first.

**Search.** A small engine of our own, a JavaScript port of `harness.BM25`:
- **Tokens:** those of plan RE's measurements, so `REQ-1-OAD-1050` stays one token.
- **Queries:** prefixes (`REQ-1-OAD-10*`) and quoted phrases work, and ids and names weigh more
  than text. Generated text is searched too, and marked in results.
- **Results:** filters by project and type, and each search shows its count and time.

**Reading.** Results are ranked, with snippets that highlight the words. Each one opens a detail
pane:
- the item's full text;
- its relationships, as links to the related items, with back and forward;
- its source;
- for a diagram, its sketch, when the page has them.

## Steps

| Step | What | Status |
|---|---|---|
| KX-01 | **Research** (`docs/research/keyword-export-2026-10-02.md`). | Done |
| KX-02 | **Catalog records** (`catalog.py`, `project_catalog(view, sink)`), written by `TableWriter.write_indices` as `index/catalog.jsonl` during `run`. Tests on the fixture and the fiction: a requirement's relations, a summary's model, the scope rule. | |
| KX-03 | **The workbook** (`workbook.py`, XlsxWriter in constant-memory mode). The sheets above, with the cut limits named in one place, and fixed document properties so that the same tree gives the same bytes (BASE-015). | |
| KX-04 | **The search page, text only.** `searchpage.py` writes it; its code is in `assets/` (`search.js`, `search.css`, the template).<br>**Data:** per-project blocks.<br>**Loading:** the early message, phases with progress bars and timings, slices of about 30 ms, Cancel, stall, capability and zip-preview messages, and the summary.<br>**Engine:** tokenizing, BM25 ranking, prefixes, phrases, field weights, filters.<br>**Interface:** results with snippets, the detail pane, history.<br>**Tests:** Node unit tests of the engine, on a small corpus that a Python test also ranks with `harness.BM25`, so that the two rank alike. A Node test decodes a page's blocks back into the records. Both are skipped where Node is missing. | |
| KX-05 | **Sketches in the page, an experiment.** Both candidates on the samples:<br>(a) **WebP:** the tree's PNGs re-encoded at export (Pillow has WebP).<br>(b) **SVG:** a renderer beside `sketch`, `sketch_svg.render_svg(ix, graph, title)`, drawing the same shapes, numbers, connections and names as vectors. It writes `diagrams/*.svg` during `run`, behind the existing `--render` option. Each shape carries its element's key, so the page can open it.<br>Measured for each: the page's size, the time to show a sketch, and how it reads, judged by the maintainer side by side on a few diagrams (small, large, an activity, an IBD).<br>The maintainer then picks one, both or neither, and the chosen one goes into the page. | |
| KX-06 | **The `export` command**: `cameo-ingest export TREE [--workbook FILE] [--search-page FILE] [--sketches none\|webp\|svg]`. It writes the exports from the projects' records, chunks and sketches, and the state's sightings. It reports, with progress, what it wrote, the sizes, and what it left out. The README gets a section, "Searching without tools": how to make the exports, how to share them on SharePoint, what readers do (download and open the page; open the workbook), and Obsidian or VS Code for those who have the tree. | |
| KX-07 | **Measure on the samples** (memory-capped):<br>- the workbook's size, rows and build time;<br>- the page's size per sketch option, and its time per phase under Node, on its own data and engine.<br>The maintainer then takes one look at the page in their own browser, to compare its timings with Node's. Adjust the cut lengths, the scope or the slices from what that shows. | |
| KX-08 | **The maintainer's trial**, on the fiction first, then the samples, with tasks that matter:<br>- find a requirement by its id, and by a few words;<br>- find what satisfies it, and the source file of each;<br>- find which models mention an id;<br>- find what a model is about (summaries);<br>- look at a diagram.<br>Also tried: sharing each export through SharePoint. The maintainer decides what to keep. | |
| KX-09 | **Polish what is kept**, from the trial's notes; drop what isn't. | |

## Checkpoints

| Checkpoint | Steps | Output | Status |
|---|---|---|---|
| CP1: the records and the workbook | KX-02, KX-03, KX-06 (workbook) | `index/catalog.jsonl` per project; `export --workbook`; 0.8.0 | Done (1db2652) |
| CP2: the search page | KX-04, KX-06 (page) | `export --search-page` | Done; no version bump, since the tree's output is unchanged and a bump would make every project again |
| CP3: sketches | KX-05 | The maintainer's choice, in the page | |
| CP4: the samples | KX-07 | Measurements, and adjustments | |
| CP5: the trial | KX-08, KX-09 | What the maintainer keeps | |

### CP1 in detail

**The records** (`catalog.py`, KX-02). `project_catalog(view, sink)` gives the records of
`index/catalog.jsonl`, in this order:
- **`project`, first and once:**
  - the file name, label and token;
  - the exporter's "saved by";
  - counts per record type;
  - `left_out`: the elements out of scope, by metaclass.
- **`requirement`:** each element with `semantics.requirement`.
  - **Fields:** `key`, `id`, `db`, `name` (`label`), `where` (qualified name), `package`, `text`
    (the requirement text), `stereotypes`.
  - **`relations`:** `[relationship key, kind, "out"/"in", phrase, other key, other label]`. The
    phrase is the pages' wording, forward or inverse ("satisfied by", "derived into"), or the
    kind with an arrow.
  - **`diagrams`:** `[key, label]` of the diagrams that show it.
  - **`chunks`:** its main and details chunks.
- **`diagram`, `package`, `element`:** the same fields where they apply. `kind` is the diagram
  type, or the kind word, and `text` the documentation.
  - **Scope:** an element is in when it has its own chunk (a section) or a name or documentation.
    Comments, relationships and stereotype applications are records of other types or none.
  - **Members:** an element in scope without a chunk of its own (a part property, a port, a pin)
    names `listed_in`, the nearest owner with chunks, and borrows its chunks.
- **`relationship`:** `key`, `kind`, `source`, `target` (each `[key, label]`), `phrase`.
- **`summary`:** each LLM annotation with text:
  - `of` (`[key, label]`), `label` (Summary, Part summary, Diagram description…), `module` or
    `parts` where given;
  - `text`, `model`.

On the samples that is about 69,000 items in scope (42,000 sections and 27,000 members),
23,600 relationships and 6,500 summaries.

**The workbook** (`workbook.py`, KX-03): `write_workbook(path, projects)`, where `projects`
yields each project's header, records, identifier records and sources.
- **Sheets:** in the plan's order, written row by row (constant memory), a project at a time.
- **Cut limits** (`LIMITS`, in one place): 1,000 characters for text in `Search`, 4,000 in
  `Requirements`, 2,000 in `Elements`, 8,000 in `Summaries`.
- **`Find`:** three cells for words and one each for a project and a type, with a single
  `FILTER`/`SORTBY` formula over `Search`, ids and names first. LibreOffice 24.2 here predates
  `FILTER`, so the formula is first checked in the maintainer's trial.
- **Properties:** fixed (a fixed creation time; no author).

**The command** (KX-06, workbook part): `cameo-ingest export -o OUT --workbook FILE`.
- **Inputs:** the written projects from the state, with their sightings (paths and `--meta`), and
  each project's `index/catalog.jsonl` and `index/ids.jsonl`.
- **Feedback:** progress per project, then the file's size and the rows per sheet.
- **Old trees:** a project made before 0.8.0 has no catalog. The command names it and says that
  `run` makes it again.

**Version:** 0.8.0, since there is a new per-project file.

**Results (2026-10-02):**
- **The tree:** a `--no-llm` tree of the samples and the fiction (27 projects, KOIS now among
  them) differs from 0.7.2's (`out/kx/base`) only in the 27 new `index/catalog.jsonl` files and
  the manifest that lists them.
- **The workbook from it** (`out/kx/catalog-cp1.xlsx`): 7.1 MB, written in 16 s at 204 MB of
  memory. Rows:

  | Sheet | Rows |
  |---|---|
  | Search | 68,314 |
  | Requirements | 8,808 |
  | Identifiers | 9,620 |
  | Elements | 54,100 |
  | Relationships | 22,988 |
  | Diagrams | 3,645 |
  | Summaries | none, without the LLM |
  | Projects | 27 |

**Checks:** a `--no-llm` tree of the samples and the fiction, against one made at 0.7.2
(`out/kx/base`): everything the same but `index/catalog.jsonl`, the manifest's lists and the
version. Then the workbook made from it: its size and rows.

### CP2 in detail

**Files.**
- **`searchpage.py`:** `write_search_page(path, projects, version)` fills the template and
  appends the data blocks.
- **`assets/`:** `search.html` (the template, with its loading message), `search.css` and
  `search.js`, inlined into the page when it is written.
- **`search.js`:** two parts. The engine (tokens, the index, search, snippets) has no DOM, so
  Node can test it; the interface runs only in a browser.

**Data.** One `<script type="application/octet-stream">` block per project, holding
base64(gzip(JSON)), with gzip's time fixed for the same bytes each time. Each block has:
- **The project:** label, file name, token, sources (paths and `--meta`), counts.
- **The items, as objects with short keys:**
  - `k` key, `t` type, `kd` kind, `id`, `db`, `n` name, `w` where, `x` text;
  - `c`: the full text, the item's own chunks joined. Members borrow none, but link to the
    item they are listed in (`l`), so the text isn't repeated.
  - `r` relations (`[kind, direction, phrase, other key, other label]`), `d` diagrams;
  - `m` model, `of` (summaries).

Relationship records stay in the workbook: the page shows relations on their items.

**Loading** (the plan's feedback rules).
- **While the file is still being read:** a small inline script after each data block advances
  "Reading: project 3 of 26", since the browser paints while it parses.
- **When the document is ready, per project:**
  - base64 to bytes;
  - `DecompressionStream`;
  - `JSON.parse`;
  - indexing, in slices of about 30 ms that yield to the page.
- **During all of it:** each phase has a bar and a running time, and a Cancel button. A note
  appears if a phase stalls for 10 s.
- **At the end:** the summary.
- **Problems:**
  - a browser without `DecompressionStream`: a message;
  - a path in a temporary folder of Windows' zip preview: a message.

**The engine.**
- **Tokens:** those of `harness.words` (`[a-z0-9]+(?:[-.][a-z0-9]+)*`, lower case).
- **Two BM25 indexes** (k1 = 1.2, b = 0.75, the idf of `harness.BM25`):
  - the title (id and name);
  - the body (where, text and full text).
- **Score:** 3 × the title's BM25 + the body's.
- **Postings:** per token, typed arrays of document numbers and term counts.
- **Queries:**
  - words, scored together, so that an item with more of them ranks higher;
  - `prefix*`, expanded through the sorted vocabulary, at most 200 tokens;
  - `"a phrase"`: its words, then a check for the phrase in the item's text;
  - filters by project and type.
- **Results:** the first 200, with the total, the time, and snippets that mark the words.

**The interface.**
- **Layout:** a search box, filters and results on the left, the item on the right.
- **Navigation:** in the URL's `#` (an item's project and key), so that Back and Forward work.
- **Safety:** model text is shown with `textContent` only, never as HTML.

**Tests.**
- **Python:** the page's blocks decode back into the records; the same bytes twice; the
  template's placeholders are all filled.
- **Node** (`tests/js/`, run from pytest, skipped without Node):
  - the engine's BM25 on a small corpus matches `harness.BM25`'s scores to 1e-6;
  - prefixes, phrases and filters;
  - the blocks of a real page, from the fiction tree, decode and index.

**Packaging:** the assets ship in the wheel, which a `uv build` and a listing check.

### CP3 in detail

**The records name the sketches.** A diagram record gets:
- `sketch`: its PNG, from the diagram's image annotation;
- `modules`: a large diagram's module PNGs;
- `svg`: its SVG file, once written (below).

**SVG** (`sketch_svg.py`, `render_svg(ix, graph, title)`). It draws the graph that `sketch`
draws, in diagram units (a `viewBox`, no pixel budget):
- **Shapes:** rectangles, ellipses and bars, tagged with their legend numbers, and their names
  shortened to fit by an estimate of text width.
- **Connections:** lines dashed or solid, arrowheads hollow or open, and the item-flow mid-arrows.
- **Other marks:** pins as dots, and connector circles with their labels.
- **In the browser:** each shape is a group with its element's key (`data-k`) and a tooltip with
  the full label (`<title>`). The page can therefore open a shape's element, and a reader can
  see a name that was cut.
- **When it is written:** `run` writes `diagrams/<name>.svg` beside the PNG whenever it draws
  (`--render`). Text is XML-escaped.

**The page** (`--sketches none|webp|svg`, default `none` until the trial decides):
- **The data:** one block per diagram, after the projects' blocks.
  - `webp`: the PNGs (the overview, and a large diagram's modules) re-encoded losslessly at
    export.
  - `svg`: each SVG, gzipped.
- **Decoding:** only when the diagram is opened.
- **SVG in the page:** it is parsed with `DOMParser` as SVG, never as HTML, and its shapes
  open their elements when clicked.

**The measure,** on the samples, for each option:
- the page's size, and the export's time;
- the time to show a sketch;
- side-by-side screenshots of a small diagram, a large one, an activity and an IBD, for the
  maintainer to choose.

**Version:** 0.8.1 (new per-project files: the SVGs, and the records' sketch fields).

**Checks:**
- **The workbook** (CP1), read in tests with `zipfile`:
  - its sheets and their row counts;
  - a known requirement row;
  - a text starting with `=` stored as a string;
  - the same bytes twice.
- **The page** (CP2, CP3):
  - Node tests of the engine: tokens, ranking against `harness.BM25`, prefixes, phrases,
    filters;
  - a Node test that decodes the blocks back into the records, and the sketches if present;
  - the same bytes twice.
- **SVG** (CP3, if chosen): a test that each shape's key is an element of the diagram; the
  `--no-llm` tree otherwise unchanged.
- **Each checkpoint:** the rest of the tree unchanged (`treediff`, `--no-llm`). CP1, and CP3 if
  SVG is chosen, make every project again once, from the LLM store, at no cost.

## When to stop and ask

- **The workbook's size:** it exceeds 100 MB on the samples even after cutting text. The
  maintainer chooses between less text, a workbook per project, or desktop-only use.
- **The page's memory or load** grows past what an ordinary office PC copes with, say over a
  minute or over 2 GB on the samples. Long loads are acceptable while their progress shows.
- **The trial** shows a need that neither format meets.
