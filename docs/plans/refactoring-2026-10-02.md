# Plan: refactoring after the architecture review, 2026-10-02

- **Status:** Proposed on 2026-10-02.
- **Step prefix:** `RA`, so steps are `RA-01`, `RA-02` and so on
- **Addresses:** the architecture review (`docs/reviews/architecture-2026-10-01.md`), stages 2
  to 4 of its remediation order, with the maintainer's four decisions. Stage 1 (bugs and the
  validity of the evaluation) is done in the review itself: AR-001, AR-002, AR-003R1, AR-005R1
  and R2, AR-006, AR-012R2's label fix and AR-016R2.
- **Related:** plan RE (retrieval evaluation), whose fictional projects and grading serve as the
  check that retrieval doesn't get worse; plan RF (related facts), whose threads AR-027 touches.

## Decisions

Answered by the maintainer on 2026-10-01.

| # | Question | Decision |
|---|---|---|
| 1 | The Markdown chunk style (AR-004R4) | Retire it. Pages stay Markdown. |
| 2 | Finished studies (AR-026R2) | Retire them, and cite where they can still be found: a tag on the last commit that has them. |
| 3 | The evaluation package (AR-026R3) | An optional extra, `cameo-ingest[eval]`: the code stays in the package, and its heavy dependencies (numpy, tokenizers) install only with the extra. |
| 4 | Retired and rejected prompt templates (AR-025R2) | Retire them from the code as well. |

**What follows:**
- **One chunk style:** most of the branching AR-004 found goes with the Markdown style, so it
  is retired first, and the later steps have only one style to keep.
- **One tag for the studies and the old templates:** `studies-2026-10-02`, on the commit just
  before they are deleted. The research notes cite it ("`scripts/sandwich_study.py` at tag
  `studies-2026-10-02`"). The maintainer pushes the tag.
- **A record of old templates is kept anyway:** the LLM store logs each request's template key
  and values, and `quality` copes with versions not in code.

## How each step is checked

Most steps change the code's structure and not its output. That is shown, not assumed:
- **The comparison (RA-01):** each step's output trees are compared with the trees made just
  before it, on every sample and on the fictional projects: pages, chunks (by id and text),
  `rag/`, tables, the ledger and the provenance. A step that should change nothing must show
  no difference; a step that changes output (marked below) must show only the expected ones.
- **LLM output stays fixed:** the comparison runs with the replay fixture and the LLM store, so
  prompts that don't change are answered from the store. A changed prompt hash shows up as a
  replay miss, which is how a step proves it left the prompts alone.
- **Retrieval doesn't get worse:** a step that changes chunk text is measured on the fictional
  questions (cached embeddings; only changed windows cost anything).
- **Load:** one tree at a time, under a memory cap, as the maintainer's machine requires.

## Steps

Each step lands as one or more commits with tests, and updates the review's statuses.

### First: the decisions

| Step | What | Output |
|---|---|---|
| RA-01 | **Before and after.** A script that compares two output trees and reports differences by kind of output (pages, chunks by id, chunk text, `rag/`, tables, provenance), ignoring run times and the tool version. A test on two runs of the fixture. | None |
| RA-02 | **Retire the Markdown chunk style** (AR-004R4). Remove `--chunk-style`, the `chunk_style` option and its branches (emit, ledger, exports, the generated chunks). A tree that stored `chunk_style` keeps working: the setting is ignored, with a note. The tests that ran both styles run one. The project options change, so every project renders again on its next run. | Only in trees that used the Markdown style; version 0.6.0 |
| RA-03 | **Tag, then retire the studies and old templates** (AR-026R2, AR-025). Tag `studies-2026-10-02`. Delete `partition_study`, `sandwich_study`, `long_context_study`, `chunk_inventory` and `embedding_check`, and the templates that are neither current nor used by the evaluation. Each template gets a status, `register()` refuses duplicates, and `CURRENT` is derived from the status (AR-025R1); derived texts are checked to differ from their base (AR-025R3). The research notes and plans cite the tag where they named a script. | None (the replay fixture proves the current prompts unchanged) |
| RA-04 | **`cameo-ingest[eval]`** (AR-026R3). Move numpy and tokenizers from the `eval` dependency group to an optional extra; `uv run --extra eval` replaces `--group eval` in scripts and docs. An evaluation module imported without the extra stops with "install cameo-ingest[eval]". Grading needs neither (`evaluation/grading.py`), so its tests always run. | None |
| RA-05 | **Dead code** (AR-026R1): the unused fields and functions the review lists, `md_escape`, and the short ids sliced by hand (`ContentInfo.short_id`, `chunk_ref()`). | None |

### Then: one source of truth (review stage 2)

| Step | What | Output |
|---|---|---|
| RA-06 | **Labels, requirement ids and relationship wording in `semantics`** (AR-010R1, AR-011R1): one `requirement()`, one `label()` and `kind_word()`, one table of relationship phrases, used by emit, ledger, diagrams, pipeline and crossref. Diagram nodes carry a structured label, computed once (AR-010R2). | Where the eight versions disagree today, as listed in the comparison |
| RA-07 | **The ledger shows a requirement's id once** (AR-010R3), with its database number as a field. | The ledger and its chunks |
| RA-08 | **Conversions in `text`** (AR-023): one `strip_links`, `plain` for what a reader sees, one `flat()` for matching (the grading module's). The other converters and link patterns go. | None |
| RA-09 | **One chunk type and one packer** (AR-015, AR-004R1 to R3): a `Chunk` type and factory (id scheme, required metadata, validation) that `check_invariants` uses; one `pack(rows, heading, budget, max_rows)`; one plain heading builder for every chunk, generated and ledger chunks included, with the heading's share of the budget capped; module and part metadata renamed `covers`, so that `part` only ever means splitting. | Generated and ledger chunk headings; measured on the fictional questions |
| RA-10 | **One config** (AR-013): `TreeSettings` (stored) and `ProjectOptions` (hashed), typed, with their defaults in one place, and a helper for on/off flag pairs. | None |

### Then: structure (review stage 3)

| Step | What | Output |
|---|---|---|
| RA-11 | **A section view and its renderers** (AR-003R2): each element's section built once, as parts (title, fields, blocks marked meaning or detail, lines whose references are `(label, target)`), rendered to Markdown for pages and to plain text for chunks. `blocks`, `_BLOCK`, `_TRACE` and the section-level `plain()` go. | None for pages; chunk text only where the parsing still differed |
| RA-12 | **Plain LLM inputs** (AR-018R1): summaries are sent the plain rendering, without link targets. The prompt hashes change, so the templates' versions go up and every summary is asked again once (for TMT, many requests). Run after the maintainer agrees to the cost. | Generated summaries |
| RA-13 | **Split `ProjectWriter` and the enrichment** (AR-007, AR-008, AR-009): `ProjectView`, `FilePlan`, `PageWriter`, `ChunkSink` and `TableWriter`; an `enrich` module with typed requests and one round loop; a values builder beside each template, with its limits as named constants, and a test that renders every current template from its builder. | None |
| RA-14 | **Per-project index files, and `rebuild` in steps** (AR-012R1, the rest of R2, R3; AR-014): `index/ids.jsonl` written at build time and merged by the tree-level index; chunk metadata names the main chunk and the annotation, so `quality` reads structure; one `generated_label()`; `rebuild` calls one function per output, each tested; threads made with their project's chunks. | Threads' metadata; measured if their text changes |
| RA-15 | **Diagrams and partitioning** (AR-019): `diagram_graph`, `diagram_text`, `sketch`, `vision` (one `fit_size`) and `partition` (one base, with diagram and package adapters). | None |
| RA-16 | **The LLM session, HTTP and caches** (AR-016R1, AR-017): `ChatClient` (OpenAI or replay, injectable), `ResponseStore` and `EnrichmentSession`; embeddings through the OpenAI SDK, one `post_json` with retries for the reranker, one `SqliteCache` base, the provider's settings in one place. | None |

### Last: the evaluation and the tests (review stage 4)

| Step | What | Output |
|---|---|---|
| RA-17 | **The evaluation as library code** (AR-020, AR-021, AR-005R3): `evaluation/systems.py` and `evaluation/report.py`, with the script keeping its arguments; the windows recorded beside the rankings, for `judge_pools`; one module for reading and writing questions, rankings and judgments; the synthetic project ported to the fiction builder, so that it takes the fact rule (its scores rebased, as plan RE notes), and `synthetic.py` and its script deleted; fictional prefixes derived from `fiction.PROJECTS`. | Evaluation only |
| RA-18 | **The tests** (AR-022, AR-024): a `conftest.py`, `test_pipeline.py` split by concern, a session fixture that ingests the fiction once, small tests for the untested library code, and the SQL against `state.sqlite` moved into `State` methods. | None |

## Not in this plan

- **AR-027R2, a thread part's ancestors:** it changes what threads say, so it belongs with
  their measurement; plan RF's follow-ups, or a plan of its own.
- **Facet lists** (plan RF, deferred).
