# Plan: refactoring after the architecture review, 2026-10-02

- **Status:** Approved on 2026-10-02 ("plan is go"), with the cost of RA-12. RA-01 to RA-05 are
  done; the rest is grouped into checkpoints CP1 to CP8 below, each expanded in detail when it
  starts.
- **Step prefix:** `RA`, so steps are `RA-01`, `RA-02` and so on
- **Addresses:** the architecture review (`docs/reviews/architecture-2026-10-01.md`), stages 2
  to 4 of its remediation order, with the maintainer's four decisions. Stage 1 (bugs and the
  validity of the evaluation) is done in the review itself: AR-001, AR-002, AR-003R1, AR-005R1
  and R2, AR-006, AR-012R2's label fix and AR-016R2.
- **Related:** plan RE (retrieval evaluation), whose fictional projects and grading serve as the
  check that retrieval doesn't get worse; plan RF (related facts), whose threads AR-027 touches.

## Decisions

Answered by the maintainer on 2026-10-01 (1 to 4) and 2026-10-02 (5).

| # | Question | Decision |
|---|---|---|
| 1 | The Markdown chunk style (AR-004R4) | Retire it. Pages stay Markdown. |
| 2 | Finished studies (AR-026R2) | Retire them, and cite where they can still be found: a tag on the last commit that has them. |
| 3 | The evaluation package (AR-026R3) | An optional extra, `cameo-ingest[eval]`: the code stays in the package, and its heavy dependencies (numpy, tokenizers) install only with the extra. |
| 4 | Retired and rejected prompt templates (AR-025R2) | Retire them from the code as well. |
| 5 | The plan itself (2026-10-02) | Go. Expand, reorder and merge steps into checkpoints where that makes sense, and halt early for discussion if significant issues turn up. RA-12's cost (about $1.50 on the samples, once) is accepted. |

**What follows:**
- **One chunk style:** most of the branching AR-004 found goes with the Markdown style, so it
  is retired first, and the later steps have only one style to keep.
- **One tag for the studies and the old templates:** `studies-2026-10-02`, on the commit just
  before they are deleted. The research notes cite it ("`scripts/sandwich_study.py` at tag
  `studies-2026-10-02`"). The maintainer pushes the tag.
- **A record of old templates is kept anyway:** the LLM store logs each request's template key
  and values, and `quality` copes with versions not in code.


## How each checkpoint is checked

A checkpoint is one or more commits that leave the tests passing and the output accounted for.
Most of the work changes the code's structure, not its output, and that is shown, not assumed.

**The reference trees.** Before a checkpoint starts, its baseline is the tree built at the end
of the one before (`out/ra/<checkpoint>`; the first is `out/ra/ra05`). Each is built from the
same inputs, at the same paths, one at a time and under a memory cap:

```sh
systemd-run --user --scope -q -p MemoryMax=3G -p MemorySwapMax=0 \
  .venv/bin/cameo-ingest samples out/eval/fiction -o out/ra/<checkpoint> --no-llm
python -m cameo_ingest.treediff out/ra/<previous> out/ra/<checkpoint>
```

Twenty-six projects (the samples and the six fictional ones) take about four minutes. The
comparison must show no difference, or only the ones the checkpoint expects; each expected
difference is explained in its status.

**LLM output** (from CP1, RA-20): a copy of the samples' LLM store answers every current
prompt, and a reference tree is built replaying from it. A replay miss fails the build, which
is how a checkpoint shows it left the prompts alone. CP2 (labels) and CP4 (inputs) change
prompts on purpose; CP2 is checked without the LLM, and CP4's one live run asks every changed
prompt, once, into the same store.

**Retrieval** (from CP1, RA-19): a checkpoint that changes chunk text is measured on the 210
fictional questions, on the tree as `rag/` presents it: BM25, e5-large and their hybrid,
alone and reranked (Qwen3-Reranker 0.6B over the top 30). Embeddings and reranks are cached,
so only changed text costs anything (cents).

**Load:** one heavy job at a time, under a memory cap.

## When to stop and ask

The maintainer asked for an early halt when significant issues turn up. Concretely:
- a comparison shows differences a checkpoint didn't expect, that aren't a plain bug fix;
- retrieval gets worse with any system, beyond the intervals' noise;
- prompts change where no change was intended, or a live run would cost more than twice its
  estimate;
- a change would alter an interface the maintainer relies on beyond what this plan says: the
  CLI's flags, the layout of `rag/`, or the metadata of `chunks.jsonl` and `rag/meta`;
- a step turns out to need a design decision the review didn't anticipate.

## Versions

A checkpoint that changes output bumps the version, so that trees render again (the version
is part of each project's stamp): CP2 to 0.6.1, CP3 to 0.6.2, CP4 to 0.7.0 (new template
versions), CP5 to 0.7.1. The others change no output.

## Steps done

| Step | What | Output | Status |
|---|---|---|---|
| RA-01 | **Before and after.** A module that compares two output trees and reports differences by kind of output (pages, chunks by id, chunk text, `rag/`, tables, provenance), ignoring run times and the tool version. A test on two runs of the fixture. | None | Done: `cameo_ingest.treediff` (`python -m cameo_ingest.treediff BEFORE AFTER`), with a test |
| RA-02 | **Retire the Markdown chunk style** (AR-004R4). Remove `--chunk-style`, the `chunk_style` option and its branches (emit, ledger, exports, the generated chunks). A tree that stored `chunk_style` keeps working: the setting is ignored, with a note. The tests that ran both styles run one. The project options change, so every project renders again on its next run. | Only in trees that used the Markdown style; version 0.6.0 | Done (0.6.0): on the samples and the fiction (26 projects), the tree before and after is the same (`treediff`). A tree that stored the Markdown style warns once and runs on with plain chunks (a test) |
| RA-03 | **Tag, then retire the studies and old templates** (AR-026R2, AR-025). Tag `studies-2026-10-02`. Delete `partition_study`, `sandwich_study`, `long_context_study`, `chunk_inventory` and `embedding_check`, and the templates that are neither current nor used by the evaluation. Each template gets a status, `register()` refuses duplicates, and `CURRENT` is derived from the status (AR-025R1); derived texts are checked to differ from their base (AR-025R3). The research notes and plans cite the tag where they named a script. | None (the replay fixture proves the current prompts unchanged) | Done: tag `studies-2026-10-02` (local, for the maintainer to push); five studies and ten templates retired. The eight current templates take their purposes, slots and texts as literals, without versions in their names; one tuple makes `CURRENT` and `TEMPLATES`, one version per id. Their requests are pinned by hash (unchanged), and the replay test passes. No derived texts remain, so AR-025R3 needs no check. The research notes and plan RE cite the tag |
| RA-04 | **`cameo-ingest[eval]`** (AR-026R3). Move numpy and tokenizers from the `eval` dependency group to an optional extra; `uv run --extra eval` replaces `--group eval` in scripts and docs. An evaluation module imported without the extra stops with "install cameo-ingest[eval]". Grading needs neither (`evaluation/grading.py`), so its tests always run. | None | Done: `[project.optional-dependencies] eval`; `evaluation.require()` names the extra when numpy or tokenizers is missing (a test); the scripts and README say `uv run --extra eval`. A plain `uv sync` now leaves numpy out: use `uv sync --extra eval` for the evaluation |
| RA-05 | **Dead code** (AR-026R1): the unused fields and functions the review lists, `md_escape`, and the short ids sliced by hand (`ContentInfo.short_id`, `chunk_ref()`). | Ledger package counts of 1,000 or more | Done: `ContentInfo.short_id`, `short_id()` and `chunk_ref()`; `md_escape` renamed `tidy` for what it does; the unused output lists, `Project.notes`, `Layout.bounds`, `View.depth` and `type_label` gone; comment bodies converted once, by the parser; the ledger uses `text.plural`. Compared with RA-02's tree, only TMT's package ledgers differ ("1,258 elements", one row moving between parts) |

## Checkpoints

The order differs from the review's. The tests come first: a shared `conftest.py` and one
ingest of the fiction per session make every later checkpoint's tests cheaper to write and to
run. Then the vocabulary (labels, ids, wording), which headings and prompts depend on; then the
chunk path, whose plain rendering of a section is what CP4 sends the LLM; then the enrichment,
with one live run for every prompt that CP2 to CP4 change; then the writer, whose reach from
pipeline the enrichment replaces with data. Configuration, diagrams, the LLM plumbing and the
evaluation follow, each independent of the others.

| Checkpoint | Steps | Output | Status |
|---|---|---|---|
| CP1: tests and references | RA-18 (part), RA-19, RA-20 | None | |
| CP2: one vocabulary | RA-06, RA-07, RA-08, AR-012R3 | Labels, kind words, relationship wording and ledger rows where today's versions disagree; 0.6.1 | |
| CP3: one chunk path | RA-09, RA-11 | Generated and ledger chunk headings; 0.6.2 | |
| CP4: the enrichment | AR-009, RA-12, RA-13 (enrichment) | Summaries (new template versions, one live run); 0.7.0 | |
| CP5: the writer and the tree's outputs | RA-13 (writer), RA-14, RA-21 | Threads in their projects' folders, with their ancestors; chunk metadata; 0.7.1 | |
| CP6: configuration and state | RA-10, AR-024 | None | |
| CP7: diagrams and the LLM plumbing | RA-15, RA-16 | None | |
| CP8: the evaluation | RA-17, RA-18 (rest) | Evaluation only | |

### CP1: tests and references

**Why first:** the later checkpoints move code between modules, and their tests should land in
files organized by concern, with shared helpers, not in a 1,281-line module. The fiction tests
ingest the same projects many times (13 s of a 49 s suite). And every later checkpoint needs the
LLM and retrieval references this one builds.

| Step | What | Status |
|---|---|---|
| RA-18a | **`tests/conftest.py` and `tests/helpers.py`** (AR-022R1). Fixtures in `conftest.py`: `isolated_env` (autouse, every module: today it covers `test_pipeline.py` only), `fake_openai` with `FakeOpenAI`. Helpers in `helpers.py`, imported by tests: `ingest(tmp_path, *sources, args=(), name=...)` (one input or several; flags passed, not hard-coded), `tree()`, `project_dir()`, `provenance()`, `check_invariants()`. `test_llm_live.py` imports from them instead of from `test_pipeline`. || Done: `conftest.py` (with live LLM tests exempt from the isolated environment) and `helpers.py` (`ingest()`, with `run()` built on it). The existing tests keep their own setup; new ones use `ingest()` |
| RA-18b | **Split `test_pipeline.py` by concern** (AR-022R2), moving tests unchanged: `test_output.py` (pages, chunks, provenance, `rag/`, switches, the ledger, reproducibility, `treediff`), `test_diagrams.py` (the diagram tests, with `test_modules.py`'s), `test_xmi.py` (parsing, archives, bundles, budgets), `test_cli.py` (tree rules, destination, status and prune, interrupts, progress, options, preflight), `test_llm.py` (enrichment, templates, the store, replay, budget, breaker, concurrency, quality), `test_samples.py` (the samples, and the slow bundle test), `test_plain.py` (`test_plain_chunk_text`, misfiled in the evaluation tests). The count of tests stays the same. || Done: the tests of `test_pipeline.py` (59 with their parameters) moved unchanged into six modules; 87 tests in all, as before. Also `testpaths = tests`: a bare `pytest` walked `out/` (8.5 GB) for 20 s |
| RA-18c | **The fiction once per session** (AR-022R3): a session fixture ingests the six fictional projects, in their folders, into one tree; the answer-key, rendering and across-models tests read it. || Done: `fiction_tree`, a session fixture; the fiction tests take 6.5 s instead of 13 |
| RA-19 | **Retrieval on a tree as `rag/` presents it**: `harness.rag_units(tree)` reads `rag/text` with `rag/meta` (element, kind, chunk id), and `retrieval_eval.py --rag` uses it, in place of the one-off scripts that built the `corpus-*` directories. A test on a small tree. || Done: `harness.rag_units`, `retrieval_eval.py --rag`, a test on the fiction tree |
| RA-20 | **The LLM reference**: copy the samples' store (`out/tmt-dv/.cache/llm.sqlite`) to `out/ra/llm.sqlite`, fill what the current prompts miss with one live run on the samples and the fiction (at most about $2), then build `out/ra/cp1-llm` replaying from it. Its comparison with a `--no-llm` build shows only the generated chunks and their pages' sections. || Done: the samples' store copied to `out/ra/llm-cache/llm.sqlite` and completed by one live run (`out/ra/cp1-llm`, 26 projects): 1,420 new answers, most of them TMT-2024x's, which the store lacked; 5,574 from the store; the 265 incomplete items are trivial diagrams, skipped by design. About $1.50. The tree was built against the store rather than replayed from it; a replay build would ask nothing |

**Checks:** the tests pass in the same number, faster; `treediff` of `out/ra/ra05` against a
fresh build shows no difference; the replay build has no misses.

### CP2: one vocabulary

**Why here:** labels, requirement ids and relationship wording reach pages, chunks, headings,
the index and prompts. Settling them first means each later checkpoint compares against output
that no longer changes for this reason.

**What stays and what changes.** The pages' wording is the reference where the versions
disagree; the index and the ledger follow it. Expected differences, each listed in the status:
- **Unnamed elements** read as what they otherwise say they are (the part a swimlane represents,
  an action's body or behavior, an event, a comment's text, a value), as diagrams already do;
  otherwise "(unnamed Class)", as headings already do. Links on pages said "(Class)".
- **Requirements** are titled one way everywhere: by name, with their id; unnamed, by id and
  the start of their text. The id is the one people use: a DOORS id at the start of the text
  (`[RWT-REG-001] …`) over the `Id` tag, which is then a database number. Diagram legends
  showed the raw tag (`16001`).
- **«DiagramInfo»** is never a kind word (ledger rows showed it).
- **The index's** `copy` phrase becomes the pages' ("is a copy of"); its inverse phrases come
  from the table, not from `.replace()` chains.
- **Ledger rows** show a requirement's id once (RA-07).

| Step | What | Status |
|---|---|---|
| CP2a | **The vocabulary in `semantics`** (AR-010R1, AR-011R1). `text.DOORS_ID` is the one pattern for a DOORS id at the start of a text (`crossref` and `evaluation.questions` each have a copy). In `semantics`: `Requirement(id, db_id, text, title)` and `requirement(ix, el)`; `described(ix, el)` (diagrams' `_described`, its trigger branch using `trigger_text`, which also covers change and time events) and `invoked(ix, el)` (an action's behavior, operation, signal, event or feature); `label(ix, id)`: the name, or for an unnamed element its requirement title, what it invokes or what describes it, else "(unnamed Kind)"; `kind_word(ix, el)`: "Requirement", or the first stereotype but «DiagramInfo», or the metaclass; `RELATIONS`, kind to (forward, inverse) phrases ("satisfies", "satisfied by"), and `phrase(kind)`. `ModelIndex.label` becomes generic (the name, or the tail of a reference), for the data layer only. Callers switch: `emit` (links, headings, relationship lines), `ledger` (rows; `REQ_LINKS` goes), `crossref` (its `VERBS` and `_BRACKET_ID` go), `pipeline` (prompt values), `modules`. Tests: each function on the fixture and on hand-made elements (unnamed of each kind, a DOORS requirement, a named one with an `Id`). || Done (0.6.1) |
| CP2b | **Diagram labels computed once** (AR-010R2). `diagrams.build` gives each node a `Label(stereotype, name, type, description)` from `semantics`; the legend's text, the sketch's name and `describe`'s link label read it. `_name`, `_described`, `element_label`, `_shown_name` and `diagrams.VERBS` go (the verbs to `semantics`). The diagram tests keep their expectations, except requirement nodes (titled, not the raw tag). || Done |
| CP2c | **A requirement's id once** (AR-010R3). Ledger rows: `- [title](link) — "text"`, the text without a leading `[id]`, and the database number in the row's parenthesis when there is one; sorted by the id. Pages: "Requirement ID" is the id; a "Database number" field follows when the tag differs. || Done |
| CP2d | **Conversions in `text`** (AR-023): `strip_links` (one link pattern, which handles the escaped brackets `md_inline` writes), and `flat()` moved from `evaluation.grading`. `md_plain` with `ledger._MD_LINK` and `questions._plain` go: the projects ledger uses `plain.plain`, and the judges and the question writer read `plain.plain` passages, without link targets. || Done |
| CP2e | **One `generated_by(derivation)`** (AR-012R3) for "(generated by X; not part of the source model)", in `provenance`, used in the six places. || Done. Every difference from CP1's tree is accounted for (per element, across parts): unnamed elements named by what they invoke or say, else '(unnamed Kind)' (27,066 lines); ledger rows with the id once (7,461); the requirement id field and database number (6,668); requirement titles 'Name (ID)' (2,970); diagram legends titling requirements, not by their raw tag (378); wording from one table (6); 296 sketches, whose shapes now show the same names. Follow-up, for CP5: TMT has texts starting '- [REQ-…]', which `DOORS_ID` misses |

**Checks:** unit tests for each new function; `out/ra/cp2` (`--no-llm`) against `out/ra/cp1`,
every difference in the lists above; retrieval on the fictional questions, `out/ra/cp1` against
`out/ra/cp2`; the replay fixture re-recorded if its prompts changed (cents). The samples' LLM
prompts change too (labels in legends and in summaries' page text), but they are not asked
live here: CP4 changes the same prompts again, and one live run there covers both.
Version 0.6.1.

### CP3: one chunk path

| Step | What | Status |
|---|---|---|
| RA-09 | **One chunk type and one packer** (AR-015, AR-004R1 to R3). A `Chunk` type and factory (`chunks.py`): the id scheme, required metadata (`kind`, `content` or `contents`, `file`, `provenance`), validation, used by emit, crossref and exports, and by `check_invariants`. One `pack(rows, heading, budget, max_rows)` in `plain`, replacing the packers in `ledger.emit_group` and `exports._projects_ledger` (which compares characters with tokens). One plain heading builder for every chunk, generated and ledger chunks included; the "covering …" name lists of generated chunks go to metadata (`elements` already holds them), and `parts` caps a heading's share of the budget (module-summary headings run to 674 characters today). Module and part metadata are renamed `covers`, so that `part`/`parts` only ever means splitting. || Done (0.6.2): `chunks.make` and `problems` (and `check_invariants` uses them); `plain.pack`; plain headings for generated and ledger chunks ('Requirements ledger of Package OAD in … (project TMT [9ffd7a2c]) (part 494 of 593), 2,718 entries': shorter, so TMT's OAD ledger has 593 parts, not 729); `covers`. A deviation from the review: a part's or module's covered names stay in its heading, as keywords the fiction can't measure (it has no generated chunks), cut to fit. The heading cap first cut the project from 120 headings; fixed (9536a08): `cap` keeps the project, and a long name is cut first |
| RA-11 | **A section view and its renderers** (AR-003R2): each element's section built once as data (title, fields as pairs, blocks marked meaning or detail, lines whose references are `(label, target)`), with `to_markdown` for pages and `to_plain` for chunks (and, in CP4, LLM inputs). `plain.blocks`, `_BLOCK`, `_TRACE` and the section-level `plain()` go. || Done: `sections.py`; `plain.section`, `blocks` and the block pattern gone. Against CP2's tree, 325 changed lines, every one a fault of the old parsing: markup or white space it left (324: a name ending in a space kept its asterisks; a name spanning lines leaked into the chunk twice) and a backslash it unescaped in a tagged value (1) |

**Checks:** pages unchanged; section chunks unchanged except where today's parsing still
differs from the page (each difference listed); generated and ledger headings changed as
intended; retrieval on the fictional questions.

### CP4: the enrichment

**Why together:** each of these changes what the LLM is sent, so one round of new template
versions and one live run cover them all, CP2's label changes included.

**Template versions.** A template whose text changes gets a new version, never a number used
before: retired versions (at tag `studies-2026-10-02`) keep theirs, since the LLM store's request
log names them. So `package-summary` goes to v4 (v3 was the retired sandwich), `module-summary`
to v3, `package-synthesis` to v3, `instances-summary` to v2 and `diagram-description` to v5.
`module-description`, `diagram-synthesis` and `image-description` keep their text, and their
version; their requests change only where CP2's labels do.

| Step | What | Status |
|---|---|---|
| CP4a | **The values of every request built beside its template** (AR-009). A module `requests` (after the review's "a builder per template") with one function per template: `diagram_description`, `module_description`, `diagram_synthesis`, `image_description`, `package_summary`, `module_summary`, `package_synthesis`, `instances_summary`. Each returns the values, the notes for the request log, and whether the input was cut (`Values`). The limits (`DIAGRAM_ITEMS` 150, `PART_CHARS`, `OWN_CHARS`, `DIGEST_CHARS`, `SUMMARY_INPUT_CHARS`, `MAX_SUMMARIES`) are named constants in `prompts`, interpolated into the slot descriptions. The sentences that reach the model without a version today ("The text was cut at …", "(Only the first 150 shapes …)", "(The digest was cut here.)", "The package's own section was cut at …") become `Template.fragments`, format strings that belong to the version and are pinned with its text. `package-summary` loses its always-empty `CUT_NOTE`; a diagram without a type is "(unknown type)", not "(None)". `modules.module_values` and `modules.synthesis_values` move to `requests`. A test renders every current template from its builder on the fixture. || Done: `prompt_values`, `Template.fragments`, the limits named; a test fills every template from its builder |
| CP4b | **Plain inputs** (RA-12, AR-018R1). Summaries are sent each section's plain text (`Section.text`: a title, then its fields and blocks, meaning first, in one piece), not the page's Markdown with its link targets; the package's own section likewise. `generated=False` is explicit. The character limits then hold more model text per request, so fewer packages are split into parts. || Done: `Section.text`; the drone sample now needs 16 requests, not 20, its packages fitting whole |
| CP4c | **An `enrich` module** (RA-13, AR-008, AR-007R2). `AnnotationKind`s (diagram description, module description, part summary, summary, run summary, image description), each with its display label and chunk kind, replace the string kinds and the label munging. An `Enricher` holds the project's requests and folds their answers into annotations, a round at a time (`while batch := enricher.next_round(): enricher.fold(batch, answers)`): the first round, then large diagrams from their modules and large packages from their parts, as today. `ingest_project` keeps parsing, rendering and writing. `_fit_image` moves beside the sketch canvas (`diagrams.fit_image`), the FU-019 id rewrite into `layout`, `IMAGE_MAGIC` into `text` beside the other magic-bytes table, and `images.md` into the writer (`write_images`). The writer gets package parts and image notes as data (`writer.set_parts`, `write_images`), and `sections_in` is public. || Done: `annotations`, `enrich`; `--no-llm`, CP4's tree is the same as CP3's (`treediff`) |

**Checks:**
- **Without the LLM:** CP4a and CP4c change no output, so their `--no-llm` trees match CP3's.
- **The requests:** the new versions' requests on the fixture, pinned; the replay fixture
  re-recorded once, at the end.
- **The live run:** samples and fiction into the same store (about $1.50 for the summaries,
  plus the diagram descriptions whose legends CP2 changed, accepted).
- **Before adopting the new summaries:** a side-by-side reading of a sample of old and new
  summaries (same packages); the plan halts for discussion if the new read worse.

### CP5: the writer and the tree's outputs

**Threads stay a tree-wide switch** (the maintainer's rule: switches are applied to the tree on
`run`). Each project now builds its threads, with its own chunks and from its in-memory model,
into `index/threads.jsonl` and a `THREADS.md` page; the switch decides only whether the tree's
`chunks.jsonl` and `rag/` include them. Under `rag/`, they move from `_tree` to the project's own
folder. Their `file` pointed at `CROSSREF.md#thread-…`, an anchor that page never had; it is
`THREADS.md#…` now.

| Step | What | Status |
|---|---|---|
| CP5a | **Split `ProjectWriter`** (RA-13, AR-007R1) into `ProjectView` (`view.py`: semantic indexes and caches, traces, headings, sections as data), `FilePlan` (`files.py`), `ChunkSink` (`sink.py`), `PageWriter` (`pages.py`) and `TableWriter` (`tables.py`); `ProjectWriter` assembles them. The ledger takes the view, plan, sink and pages, ending its circular import; the enricher takes the view and the plan. || Done: `view.py` (290 lines), `files.py`, `sink.py`, `pages.py`, `tables.py`; `emit.py` keeps the assembly (69 lines) |
| CP5b | **A DOORS id after a bullet** (from CP2's comparison): TMT has requirement texts starting `- [REQ-1-OAD-1050] …`; `DOORS_ID` takes them. || Done (0.7.1) |
| CP5c | **Per-project identifier files** (RA-14, AR-012R1). `index/ids.jsonl`, one record per identifier and element (what holds it, how, a snippet, the element's main chunk, its trace), made from the in-memory model with the vocabulary of CP2, not from the CSV tables. `crossref.places` reads these files. || Done: `crossref.project_places`, written by the table writer; `crossref.places` reads `ids.jsonl` |
| CP5d | **Threads with their project** (AR-014R2, RA-21). Made at build time from the model; their parts each start with their first line's ancestors, by title, so that every part states its derivations (AR-027R2). || Done: `crossref.project_threads` and `thread_chunks`; `plain.parts_with_context`. The text is rendered at tree time, so `--line-refs`, a tree setting, still applies; the crossing's SN-02 thread now reads 'Stop Road Users (SN-02) (continued)' and 'Obstacle Detection (FVX-SYS-011) (continued)' above its second part's first line, which was shown under the wrong parent before AR-027R1 |
| CP5e | **Structure for `quality`** (the rest of AR-012R2). Generated chunks carry `primary_chunk` (their element's main chunk) and `annotation` (an id shared by its pieces); `quality` joins an answer's pieces by it and takes its reference from the element's own chunks, not from the page with the answer cut out. || Done, with the reference kept as the page: a package summary's rater needs its elements' sections, which the package's own chunks lack. What changed is the answer: its pieces are joined by their `annotation` before it is cut from the page |
| CP5f | **`rebuild` in steps** (AR-014R1): one function per output (manifest, provenance, `INDEX.md`, the projects ledger, the index across models and `CROSSREF.md`, the tree's chunks, `rag/`), each with a test. || Done: `rebuild` calls `write_manifest`, `write_provenance`, `write_index_page`, `projects_ledger`, `cross_index`, `thread_chunks`, `write_chunks`, `write_rag`; each output is covered by the tests that read it |

**Checks:** a `--no-llm` tree for CP5a (the same as CP4's, but for the heading fix of 9536a08);
then one for the rest, every difference listed (index entries' wording, threads' place and their
ancestors, the new files and metadata); retrieval on the fictional questions, the within-model
ones especially (RA-21). Version 0.7.1.

### CP6: configuration and state

| Step | What | Status |
|---|---|---|
| RA-10 | **One config** (AR-013): a `config` module with `TreeSettings` (stored) and `ProjectOptions` (hashed), typed, with defaults in one place, passed as objects from the CLI to runner, pipeline and exports; `ProjectOptions.hash()` keeps today's hashes, so that no project renders again; a helper for on/off flag pairs, with the default in the help. The CLI stops importing `diagrams.IMAGE_PIXELS`, `modules.thresholds` and `prompts.CURRENT`. | Done (5cc3619) |
| AR-024 | **SQL in `state.py`**: `State` methods for the nine queries in `runner`, `cli` and `exports` (`todo`, `counts`, `status`, `orphans`). | Done (5cc3619) |

### CP7: diagrams and the LLM plumbing

**RA-15 in detail.** `diagrams.py` and `modules.py` become five modules. Only `sketch` loads
Pillow when imported, and only `pipeline` imports `sketch`.

| Module | What it holds |
|---|---|
| `diagram_graph` | What a layout's views are (`DECORATION`, `ATTACHED`, `DIRECTED`), `ShapeLabel`, `Node`, `Link`, `DiagramGraph` and `build`. |
| `diagram_text` | `Refs`, `PLAIN`, `describe`, and a module's lists (`module_lists`, `crossing_lines`). |
| `vision` | The patch (48 px) and `patch_sides`, which both the sketch's canvas and `fit_image` use to cut their sides to whole patches; `fit_image`. The budget itself stays in `config`. |
| `sketch` | What is drawn how (`DASHED`, `HOLLOW`, `ROUND`, fonts, margins), `Frame`, `canvas`, `render_png` and its helpers; the presets for large diagrams, `overview_png` and `module_png`, with `colour`. |
| `partition` | A base `_Graph` that takes nodes, sizes, places, parents and links; its two adapters, `_Shapes` (a diagram's shapes, placed by their rectangles) and `_Sequence` (a package's sections, placed by order), each with its own `weights`; `partition` and `sequence_partition`. A `Partition` holds its graph, so its users pass one thing, not two that must match. |

The output stays the same: a `--no-llm` tree compared with CP6's. Tests follow their code
(`test_modules.py` becomes `test_partition.py`).

**RA-16 in detail.**

- **`llm.py`, three pieces.**
  - A `ChatClient` answers one request (`complete(model, messages, temperature)`). There are two
    kinds: `OpenAIChat` (any compatible endpoint, through the SDK) and `ReplayChat` (a recorded
    store; a request it has no answer for is a `ReplayMiss`). `connect(cfg, replay)` makes the
    run's client. Tests replace `OpenAIChat` with a fake that has the same small interface, and
    no longer patch `openai.OpenAI`.
  - A `ResponseStore` (formerly `LLMStore`) holds answers and the request log.
  - An `EnrichmentSession` (formerly `LLM`) holds a run's policy:
    - the store, the budget and the breaker;
    - outcomes and items left without text;
    - the request log;
    - `ask`.

    A replayed answer bypasses the store, the budget and the breaker, as before.
    `max_failures=None` never switches off, so `judge_pools` stops passing `10**9`.
- **`sqlite_cache.py`.** `SqliteCache` is the base: one connection shared by threads under a
  lock, read-only opening, and a damaged file moved aside and started afresh (BASE-005, which
  only the LLM store had). The response store, the embedding cache and a `ScoreCache` (split
  out of `Reranker`) build on it.
- **`evaluation/provider.py`.** DeepInfra's two APIs and the key's variable, in one place:
  - the OpenAI-compatible API for embeddings;
  - its inference API for rerankers.

  The module also holds `post_json`, which retries for the reranker. Embeddings go through the
  OpenAI SDK (floats, as before), and its retries replace `Embedder._post`. The cache keeps
  the endpoint's URL in its key, so that the vectors cached so far still match.
  `EmbeddingModel.endpoint` and `key_env` go (AR-017R4). The ingest's LLM keeps its own
  configuration (`OPENAI_BASE_URL`), since it serves any compatible endpoint.
- **Counters.** `Embedder` updates its counters under a lock.
- **Tests.** The embedder and the reranker against fakes: cache hits, batches and counters.
  This is part of RA-18d, done here since the code changes here.
- **Checks.** The suite and the replay fixture. A live check: one text embedded through the SDK
  matches the vector the old path cached. The LLM run is reproduced from `out/ra/llm-cache` with
  no new calls: images and prompts unchanged, from RA-15 as well.

| Step | What | Status |
|---|---|---|
| RA-15 | **Diagrams and partitioning** (AR-019): `diagram_graph` (build, nodes, links, labels), `diagram_text`, `sketch` (rendering, frames, presets), `vision` (the pixel budget, one `fit_size` for sketches and images) and `partition` (one base with diagram and package adapters; `_Sequence` calls its base's constructor). | Done; its `--no-llm` tree check pending |
| RA-16 | **The LLM session, HTTP and caches** (AR-016R1, AR-017): `ChatClient` (OpenAI or replay, injectable, so tests stop patching `openai.OpenAI`), `ResponseStore`, `EnrichmentSession` (budget, breaker, outcomes, request log); embeddings through the OpenAI SDK; one `post_json` with retries for the reranker; one `SqliteCache` base, with the store's recovery from a corrupt file; the provider's settings in one place; the `Embedder` counters under a lock. | Done; replay from `out/ra/llm-cache` pending |

### CP8: the evaluation

| Step | What | Status |
|---|---|---|
| RA-17 | **The evaluation as library code** (AR-020, AR-021, AR-005R3): `evaluation/systems.py` and `evaluation/report.py`, the script keeping its arguments; the windows recorded beside the rankings, for `judge_pools`; one module for reading and writing questions, rankings and judgments; the synthetic project ported to the fiction builder (`fiction/orchard.py`), taking the fact rule, its scores rebased, and `synthetic.py` and its script deleted; one `is_fictional(id)` from `fiction.PROJECTS`. | |
| RA-18d | **Tests for untested library code** (AR-022R4): the question generators, the judge's reply parsing, the embedding and rerank caches, with fakes. | |

## Not in this plan

- **Facet lists** (plan RF, deferred).
