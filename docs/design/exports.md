# Design: exports for searching without tools

The workbook and the self-contained search page, for people who read the corpus through SharePoint
and office tools. Decision: ADR-0021. The README's "Searching without tools" is the user's view.

## The records (`catalog.py`)

`run` writes `index/catalog.jsonl` for each project, from the in-memory model. It is the only
per-project file the exports read (AR-012). The records come in this order:
1. **`project`,** once: its counts, and `left_out` by metaclass;
2. **items:** `requirement`, `diagram`, `package`, `element`;
3. **`relationship`;**
4. **`summary`,** with its model.

- **Scope:**
  - an element is in scope if it has its own chunk, or a name or documentation;
  - members without their own chunk are `listed_in` an owner and borrow its chunks;
  - comments are out, and unnamed items are counted, not listed.
- **Relations** are tuples `[rel key, kind, "out"/"in", phrase, other key, other label]`, the
  phrase being the pages' wording, forward or inverse.
- **Reproducible:** the same tree gives the same bytes (a fixed creation date, no author,
  `gzip.compress(…, mtime=0)`).

## The workbook (`workbook.py`)

- **Built** with XlsxWriter in constant-memory mode, one row at a time.
- **Text stays text:** `strings_to_formulas`, `strings_to_numbers` and `strings_to_urls` are off,
  so ids like `1.2.3` and text starting with `=` stay as written.
- **Sheets:**
  - About, Find, Search;
  - Requirements, Identifiers, Elements, Relationships, Diagrams, Subjects, Summaries;
  - Projects.
- **Cell limits** (`LIMITS`): Search 1,000 characters, Requirements 4,000, Elements 2,000,
  Summaries 8,000; at most 32,767 in a cell.
- **Rows:** `MAX_ROWS` = 1,048,575; the About sheet notes any sheet cut short.
- **Find:**
  - words go in B2:D2, a project in B3, a type in B4;
  - a dynamic-array `SORTBY(FILTER(…))` matches with `SEARCH` over Id, Name, Where and Text;
  - rows whose id or name holds the first word rank first;
  - untested in Excel itself: LibreOffice 24.2 lacks `FILTER`.

## The search page (`searchpage.py`, `assets/search.*`)

- **One self-contained HTML file.** A page opened from disk can't fetch files, use ES modules or
  workers, and its storage is unreliable, so it reindexes on each visit.
- **The data:** one `<script type="application/octet-stream">` block per project,
  base64(gzip(JSON)), with short keys.
  - Decoded through a `data:` URL `fetch`, with an `atob` fallback.
  - An inline `__read(i, n)` after each block advances the "Reading" message while the file
    parses.
- **The engine:**
  - tokens are `[a-z0-9]+(?:[-.][a-z0-9]+)*`, as `harness.words`, keeping ids like
    `REQ-1-OAD-1050` whole;
  - BM25 (k1 1.2, b 0.75) over two fields: the title, weighted 3, and the body;
  - prefixes expand to at most 200 tokens, and results are capped at 200.

  Node tests match `harness.BM25` to 1e-6.
- **"Long loads are acceptable, silent ones are not":** each phase shows progress and a time,
  slicing work every 30 ms and warning at a 10 s stall.
- **Safety:**
  - model text is shown with `textContent` only;
  - SVG sketches are parsed by `DOMParser` as `image/svg+xml`;
  - shape clicks are handled on the sketch's frame (`importNode` drops listeners);
  - Windows' zip preview is detected and the user told to extract.
- **Sketches,** `--sketches none|webp|svg`, default none: decoded only when a diagram is opened.
- **Subjects** (`docs/design/subjects.md`): a `data-subjects` block; results grouped by subject, a
  "Group by subject" switch, and a browse pane when nothing is typed.

## Size and scale

**On the samples** (27 projects, 74,407 items):

| Export | Size | Made in | Peak memory |
|---|---|---|---|
| Workbook | 9.5 MB | 11 s | 215 MB |
| Page, text only | 9.6 MB | 6 s | 591 MB |
| Page with SVG sketches | 14.7 MB | 9 s | 596 MB |
| Page with WebP sketches | 32.6 MB | 72 s | 645 MB |

In Chrome, the page is ready in about 2.7 s, with a 144 MB heap.

**Scale** (`docs/research/export-scale-2026-10-02.md`):
- **The page** loads at about 50 µs an item, and needs about 650 MB plus 3.8 KB an item. It is
  comfortable to about 300,000 items (15 s, 2 GB) and workable to about 600,000 (30 s, 3 GB).
- **The workbook** grows about 128 B an item. Excel for the web opens it up to 100 MB, about
  780,000 items.
- **A model's size** predicts little: items per MB of `.mdzip` range from 40 to 3,900. The median
  model has 269 items, the mean 2,756.
- **The maintainer's corpus** is estimated at about 345,000 items.

**SharePoint:**
- a folder download is limited to 10,000 files;
- search indexes `.xlsx` and `.html` but not `.md` or `.json`, parses at most 2 million
  characters, and splits ids at hyphens.
