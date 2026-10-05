# Design: output, chunks and `rag/`

How a project becomes pages, tables and chunks, and how chunks reach a RAG stack. The README
describes the output tree and gives the RAG advice; this describes how and why. Decisions:
ADR-0003, 0005 to 0008, 0019.

## Pages and chunks

- **Pages are Markdown,** for people:
  - one per package, with a section per element;
  - one per diagram;
  - the project's README, `LEDGER.md`, `THREADS.md` and `images.md`.

  An anchor (`<a id>`) goes before each heading (BASE-009). Markdown escapes only `\` `` ` `` `*`
  `[` `]` `<`, since model names are full of underscores.
- **Chunks are plain text,** for retrieval (ADR-0006). A section is built once as data
  (`sections.Section`) and rendered by role (ADR-0008):
  - `markdown()` for pages;
  - `plain()` for chunks;
  - `text()` for LLM inputs.
- **Meaning before structure:**
  - an element's chunk leads with what it is and does, then its structural detail, in one chunk
    when it fits;
  - otherwise the detail goes to a `<kind>:details` chunk.
- **Packing** (`plain.pack`, `parts`, `parts_with_context`):
  - chunks are packed to a token budget, estimated by `plain.tokens` (fitted to e5's tokenizer;
    id-heavy text runs about 2.7 characters per token, prose about 4);
  - a heading takes at most a quarter of a part (`HEADING = BUDGET // 4`), and when cut it keeps
    the project;
  - a later part of a section restates its ancestors, marked "(continued)";
  - a module's or part's covered names stay in its heading as keywords (unmeasured; AR-004R1);
    the metadata calls them `covers`.

## Cameo's tables (`cameo_tables.py`)

Cameo computes a table's cells whenever it shows the table; the file stores its configuration (a
stereotype's tags on the diagram) and, usually, the rows it lists (plan CT, ADR-0025,
`docs/research/cameo-tables-2026-10-04.md`).
- **Computed:** a table that lists its rows (`rowElements`, `additionalElements`):
  - its visible columns (`columnIds` without `hideColumns`), in order, sorted by `sort` with numbers
    in text compared as numbers;
  - each column read from the row: its properties, a requirement's Id and Text, a tag of any
    stereotype the model uses, a model attribute or reference, a relationship (Satisfied By,
    Derived From), one stereotype's tag, or an instance's slot (`IColumn`).
- **Columns not computed:** custom expression columns, and properties a profile derives. They keep
  their header, empty, and the page names them.
- **Where it goes:**
  - the page: a sentence ("Columns: …. Sorted by …. Rows: …"), then the rows as a table, cells cut
    at 500 characters;
  - `tables/diagram-tables/<page>.csv`: cells whole, with `id` and `trace`;
  - the diagram's details chunks: a line per row, every cell named, cut at 300 characters.

  Diagrams aren't package sections, so tables reach no LLM request.
- **Not computed, and said so:**
  - tables that find their rows in a scope;
  - matrices and maps, which store nothing they show;
  - tables without columns.

  Each one's page says what isn't shown and why (`cameo_tables.not_computed`).
  - **A matrix** then says what it relates, in words, from its configuration alone
    (`describe_matrix`, 0.17.2): its rows and columns (element types, scopes, "outside this project",
    "chosen by a query"), what a cell marks (the dependency criteria's names), which way, and
    whether unmarked rows and columns are shown. This replaces the raw configuration and its XML
    expressions.
  - **A table or a map** keeps its configuration. The catalog counts them per project (`tables`), the workbook's About, Projects
  and Diagrams sheets report them, and the search page's footer says so. Rows weren't inferred
  from scope: no rule reproduced the listed rows of tables that have both.

## Every chunk carries

Made by `chunks.make`, checked by `chunks.problems`, at creation and in every test's invariants:
- **`id`:** the first 24 hex digits of the sha256 of its identifying parts. A salt is added
  whenever several chunks share an element or file.
- **`metadata.kind`:** one of these (counts are from the samples' tree with the LLM, 0.14.1):
  - the model's own: `element` (28,604), `requirement` (9,737), `diagram` (9,633), `package`,
    `project`, and their `<kind>:details`;
  - ledgers: `ledger:elements`, `ledger:requirements`, `ledger:diagrams`, `ledger:packages`,
    `ledger:projects`;
  - across models: `index:id` (3,691), `trace:thread`, `index:hierarchy`;
  - generated: `generated:diagram_description` (2,871), `generated:module_summary`,
    `generated:summary`, `generated:module_description`, `generated:image_description`.
- **`metadata.file`:** the page it comes from.
- **`metadata.provenance`:**
  - a `locator` that starts from the project's content hash;
  - a `derivation.method`: `extracted` (from the model), `llm`, or `assembled` (the index and
    threads); sketches are `rendered`;
  - for generated text, its model and template.
- **Generated chunks** also carry `primary_chunk` and `annotation`, and their text says "(generated
  by <model>; not part of the source model)" (ADR-0005). A long answer is split into pieces, each
  under its heading.
- **No line over 8,000 characters:**
  - hex-encoded values are described by kind and size;
  - other tagged values are cut at 4,000 characters on pages (`text.VALUE_CHARS`);
  - the CSV and the element index keep full values (FU-020).

## Labels

Every element reads by one vocabulary (`semantics`), the pages' wording being the reference:
- **A requirement's id:** the DOORS id at the start of its text wins, also after a bullet
  (`text.DOORS_ID`). The `Id` tag then becomes "Database number".
- **Unnamed elements** read by what describes them, else "(unnamed Kind)" (FU-024):
  - swimlanes and lifelines, by the part they represent;
  - opaque actions, by their body;
  - state invariants, by their constraint;
  - notes, by their quoted text;
  - accept-event actions, by their trigger;
  - requirements, by their id or text.

  «DiagramInfo» is never a kind word. Labels are cut at 80 characters.
- **References outside a project** read by name (plan UL, ADR-0001's best effort):
  - into a used project, by the name in the model's cached copy (`proxy.*…snapshot`);
  - into the OMG libraries, by the URI's readable part (`String`, `Real`, `Block`);
  - otherwise, by the raw fragment.

  Names are keyed by fragment, and the first seen wins. Ids inside text (DocGen view lists, table
  column settings, UUID-valued tags) stay as written.
- **References to the project itself** are to its elements. Cameo writes the Model's packages kept
  in its shared part as `local:/PROJECT-<its id>?resource=…#id`; an href whose fragment is one of
  the project's elements resolves to it (`xmi.finalize`), as a diagram's shapes do (FU-019).
- **A project's README** lists its used projects by file name, which is how Cameo names them, and
  the OMG libraries by name and version: "PrimitiveTypes (OMG UML, 20131001)".
- **Relationships** read with their verbs, forward or inverse, from `semantics.RELATIONS`.
  Requirement containment is ownership, not a relationship.

## `rag/`: files for a stack that reads files

ADR-0007.
- **Text:** `rag/text/<project>/<sha256 of the text>.txt`, one chunk per file, sized to one
  512-token window (`plain.WINDOW`, with 100 tokens kept for the source line). The file ends with
  its source line:
  - with `--rag-source trace`, the project label and trace locator;
  - with `id`, short ids.
- **Metadata:** `rag/meta/<project>/<sha256>.json` beside it, carrying the chunk's metadata, its
  `source_id`, `source_file` and `source_files`. `rag/meta/_sources.json` resolves short ids to
  input files.
- **No paths:** chunk text names a project by its label ("TMT [9ffd7a2c]", `ContentInfo.label`, at
  most 32 characters), never by a path (ADR-0003).
- **Fit:** 3 of 43,552 files in the samples' `rag/` exceed 512 tokens.

## Across models: the identifier index and threads

ADR-0019 (`crossref.py`).
- **Identifiers:**
  - an identifier is `[A-Z][A-Z0-9]*(-[A-Z0-9]+)+` containing a digit; encodings (`UTF-8`,
    `ISO-8859-1`, `X-…`) are excluded;
  - an entry lists every place it is held, by two or more elements across all models, with a
    snippet of ±90 characters;
  - places that hold it as their own id come first;
  - entries are `index:id` chunks (method `assembled`), and `CROSSREF.md` for people;
  - each project's ids come from its `index/ids.jsonl`, sorted.
- **Threads:**
  - built only from `DeriveReqt` relationships;
  - a thread's root is a requirement that others derive from and that derives from nothing;
  - at most 4 levels deep, and at least 2 requirements;
  - each line adds what satisfies, verifies, refines, traces and allocates it;
  - requirement text is cut at 120 characters;
  - parts repeat their ancestors;
  - each project writes `index/threads.jsonl` and `THREADS.md`, and the tree switch decides only
    whether `chunks.jsonl` and `rag/` include them.
- **Type hierarchies** (`hierarchies.py`, plan TH, ADR-0026):
  - a root is a general with no general in the project, or a general outside it (a library's
    type) that two or more of its kinds specialize, "(outside this project)";
  - each kind appears once, under the first of its generals, with its kind word and the first
    sentence of its documentation (100 characters); its other generals are named ("also a kind
    of Sensor");
  - alike leaves share a line ("10 kinds of this name": a model's runs of one analysis);
  - at least 3 kinds; no depth limit, since parts repeat their ancestors (NIST's 1,005 kinds come
    in 75 parts);
  - each project writes `index/hierarchies.jsonl` and `HIERARCHIES.md`, and `--hierarchies` (on)
    decides whether `chunks.jsonl` and `rag/` include them, as `index:hierarchy`;
  - on Port Calder's fictional hierarchy, they hold answers that span levels, which no element
    chunk holds, and cost the 210 standing questions nothing
    (`docs/research/type-hierarchies-2026-10-04.md`).
- **Line references** (`--line-refs`, off) end each line with `[project:chunk]`.

## Reproducibility

The same input gives the same bytes (ADR-0003). Per-project files carry only the token; run data
goes to `run.json`; whatever could depend on the hash seed is sorted. `manifest.json` is
deterministic, and the root files are rebuilt from the database after every run.
