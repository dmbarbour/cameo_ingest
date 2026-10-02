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
is how a checkpoint shows it left the prompts alone; where it changes them on purpose (CP2's
labels, CP4's inputs), the misses are asked live, once, into the same store.

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
| CP4: the enrichment | RA-12, RA-13 (enrichment), AR-009 | Summaries (new template versions, one live run); 0.7.0 | |
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
| RA-18a | **`tests/conftest.py` and `tests/helpers.py`** (AR-022R1). Fixtures in `conftest.py`: `isolated_env` (autouse, every module: today it covers `test_pipeline.py` only), `fake_openai` with `FakeOpenAI`. Helpers in `helpers.py`, imported by tests: `ingest(tmp_path, *sources, args=(), name=...)` (one input or several; flags passed, not hard-coded), `tree()`, `project_dir()`, `provenance()`, `check_invariants()`. `test_llm_live.py` imports from them instead of from `test_pipeline`. | |
| RA-18b | **Split `test_pipeline.py` by concern** (AR-022R2), moving tests unchanged: `test_output.py` (pages, chunks, provenance, `rag/`, switches, the ledger, reproducibility, `treediff`), `test_diagrams.py` (the diagram tests, with `test_modules.py`'s), `test_xmi.py` (parsing, archives, bundles, budgets), `test_cli.py` (tree rules, destination, status and prune, interrupts, progress, options, preflight), `test_llm.py` (enrichment, templates, the store, replay, budget, breaker, concurrency, quality), `test_samples.py` (the samples, and the slow bundle test), `test_plain.py` (`test_plain_chunk_text`, misfiled in the evaluation tests). The count of tests stays the same. | |
| RA-18c | **The fiction once per session** (AR-022R3): a session fixture ingests the six fictional projects, in their folders, into one tree; the answer-key, rendering and across-models tests read it. | |
| RA-19 | **Retrieval on a tree as `rag/` presents it**: `harness.rag_units(tree)` reads `rag/text` with `rag/meta` (element, kind, chunk id), and `retrieval_eval.py --rag` uses it, in place of the one-off scripts that built the `corpus-*` directories. A test on a small tree. | |
| RA-20 | **The LLM reference**: copy the samples' store (`out/tmt-dv/.cache/llm.sqlite`) to `out/ra/llm.sqlite`, fill what the current prompts miss with one live run on the samples and the fiction (at most about $2), then build `out/ra/cp1-llm` replaying from it. Its comparison with a `--no-llm` build shows only the generated chunks and their pages' sections. | |

**Checks:** the tests pass in the same number, faster; `treediff` of `out/ra/ra05` against a
fresh build shows no difference; the replay build has no misses.

### CP2: one vocabulary

**Why here:** labels, requirement ids and relationship wording reach pages, chunks, headings,
the index and prompts. Settling them first means each later checkpoint compares against output
that no longer changes for this reason.

| Step | What | Status |
|---|---|---|
| RA-06 | **Labels, requirement ids and relationship wording in `semantics`** (AR-010R1, AR-010R2, AR-011R1). `semantics.requirement(view, el) -> Requirement(id, db_id, text, title)`, with the DOORS id pattern defined once (it is in three places now); `label(view, id)` and `kind_word(view, el)` (one rule for unnamed elements and for «DiagramInfo»); one table `kind -> (forward, inverse)` and `phrase(relationship, from_id)`, replacing `diagrams.VERBS`, `ledger.REQ_LINKS` and `crossref.VERBS`. `ModelIndex.label` goes back to generic. Diagram nodes carry a structured label computed once; the six label functions in `diagrams` collapse into it, and the trigger branch uses `semantics.trigger_text`. Used by emit, ledger, diagrams, pipeline and crossref. | |
| RA-07 | **A requirement's id once** (AR-010R3): ledger rows and pages show the id once, with the database number as a field; diagram legends show the same label as links. | |
| RA-08 | **Conversions in `text`** (AR-023): one `strip_links` (handling the escaped brackets `md_inline` writes); `plain.plain` for what a reader sees; `flat()` moves from `evaluation.grading` to `text`, for matching. `text.md_plain` with `ledger._MD_LINK`, `questions._plain` and `retrieval_eval._norm` go; the judges then read passages without link targets. | |
| AR-012R3 | **One `generated_label(derivation)`** for the "(generated by X; not part of the source model)" sentence, written in six places today. | |

**Checks:** the comparison's differences are listed by kind and each is accounted for (expected:
unnamed elements, «DiagramInfo» in ledgers, requirement ids in ledger rows and legends, wording
where the three tables disagree); retrieval on the fictional questions; the LLM replay misses
are only diagram descriptions whose legends changed, asked live (cents).

### CP3: one chunk path

| Step | What | Status |
|---|---|---|
| RA-09 | **One chunk type and one packer** (AR-015, AR-004R1 to R3). A `Chunk` type and factory (`chunks.py`): the id scheme, required metadata (`kind`, `content` or `contents`, `file`, `provenance`), validation, used by emit, crossref and exports, and by `check_invariants`. One `pack(rows, heading, budget, max_rows)` in `plain`, replacing the packers in `ledger.emit_group` and `exports._projects_ledger` (which compares characters with tokens). One plain heading builder for every chunk, generated and ledger chunks included; the "covering …" name lists of generated chunks go to metadata (`elements` already holds them), and `parts` caps a heading's share of the budget (module-summary headings run to 674 characters today). Module and part metadata are renamed `covers`, so that `part`/`parts` only ever means splitting. | |
| RA-11 | **A section view and its renderers** (AR-003R2): each element's section built once as data (title, fields as pairs, blocks marked meaning or detail, lines whose references are `(label, target)`), with `to_markdown` for pages and `to_plain` for chunks (and, in CP4, LLM inputs). `plain.blocks`, `_BLOCK`, `_TRACE` and the section-level `plain()` go. | |

**Checks:** pages unchanged; section chunks unchanged except where today's parsing still
differs from the page (each difference listed); generated and ledger headings changed as
intended; retrieval on the fictional questions.

### CP4: the enrichment

**Why together:** each of these changes what the LLM is sent, so one round of new template
versions and one live run cover them all.

| Step | What | Status |
|---|---|---|
| AR-009 | **A values builder per template**, beside it, returning values, notes and whether it was cut. Limits become named constants, interpolated into slot descriptions and cut notes alike. Sentences that reach the model today without a template version ("The text was cut at …", "(Only the first 150 shapes …)") move into the templates. `package-summary`'s always-empty `CUT_NOTE` and the diagram type "(None)" are fixed. A test renders every current template from its builder on the fixture. | |
| RA-13 (enrichment) | **An `enrich` module** (AR-008): typed requests, with an `AnnotationKind` holding both display label and chunk kind; one round loop (`while batch := enricher.next_round(): enricher.fold(batch, answers)`); `_fit_image` beside the sketch canvas, the FU-019 id rewrite in `layout`, one magic-bytes table, and `images.md` written by the page writer. Pipeline passes package parts and image notes to the writer as data (AR-007R2). | |
| RA-12 | **Plain LLM inputs** (AR-018R1): summaries are sent the section view's plain rendering, with `generated=False`. | |

**Checks:** the new template versions' requests on the fixture; one live run on the samples
and the fiction (about $1.50, accepted); a side-by-side reading of a sample of old and new
summaries before adopting them (a halt if the new read worse); the replay fixture re-recorded.

### CP5: the writer and the tree's outputs

| Step | What | Status |
|---|---|---|
| RA-13 (writer) | **Split `ProjectWriter`** (AR-007R1) into `ProjectView` (semantic indexes and caches, sections by package), `FilePlan` (paths, anchors, links), `PageWriter`, `ChunkSink` (CP3's factory) and `TableWriter`; the ledger takes the view, plan and sink, ending its circular import. | |
| RA-14 | **Per-project index files, and `rebuild` in steps** (AR-012R1, the rest of R2; AR-014). `index/ids.jsonl` written at build time from the model (identifier, title, what the element is, its main chunk), merged by the tree-level index instead of re-reading CSV tables; chunk metadata names an element's main chunk and an annotation's id, so `quality` reads structure, not text; `rebuild` calls one function per output, each tested; threads made at build time with their project's chunks, so they land in its `rag/` folder; the `exports` docstring fixed. | |
| RA-21 | **A split thread part names its ancestors** (AR-027R2): each part after the first starts with its first line's ancestors, by name and id only. Measured on the within-model questions. | |

**Checks:** the index and `CROSSREF.md` unchanged; threads moved and their text changed only as
RA-21 says; retrieval on the fictional questions, within-model ones especially.

### CP6: configuration and state

| Step | What | Status |
|---|---|---|
| RA-10 | **One config** (AR-013): a `config` module with `TreeSettings` (stored) and `ProjectOptions` (hashed), typed, with defaults in one place, passed as objects from the CLI to runner, pipeline and exports; `ProjectOptions.hash()` keeps today's hashes, so that no project renders again; a helper for on/off flag pairs, with the default in the help. The CLI stops importing `diagrams.IMAGE_PIXELS`, `modules.thresholds` and `prompts.CURRENT`. | |
| AR-024 | **SQL in `state.py`**: `State` methods for the nine queries in `runner`, `cli` and `exports` (`todo`, `counts`, `status`, `orphans`). | |

### CP7: diagrams and the LLM plumbing

| Step | What | Status |
|---|---|---|
| RA-15 | **Diagrams and partitioning** (AR-019): `diagram_graph` (build, nodes, links, labels), `diagram_text`, `sketch` (rendering, frames, presets), `vision` (the pixel budget, one `fit_size` for sketches and images) and `partition` (one base with diagram and package adapters; `_Sequence` calls its base's constructor). | |
| RA-16 | **The LLM session, HTTP and caches** (AR-016R1, AR-017): `ChatClient` (OpenAI or replay, injectable, so tests stop patching `openai.OpenAI`), `ResponseStore`, `EnrichmentSession` (budget, breaker, outcomes, request log); embeddings through the OpenAI SDK; one `post_json` with retries for the reranker; one `SqliteCache` base, with the store's recovery from a corrupt file; the provider's settings in one place; the `Embedder` counters under a lock. | |

### CP8: the evaluation

| Step | What | Status |
|---|---|---|
| RA-17 | **The evaluation as library code** (AR-020, AR-021, AR-005R3): `evaluation/systems.py` and `evaluation/report.py`, the script keeping its arguments; the windows recorded beside the rankings, for `judge_pools`; one module for reading and writing questions, rankings and judgments; the synthetic project ported to the fiction builder (`fiction/orchard.py`), taking the fact rule, its scores rebased, and `synthetic.py` and its script deleted; one `is_fictional(id)` from `fiction.PROJECTS`. | |
| RA-18d | **Tests for untested library code** (AR-022R4): the question generators, the judge's reply parsing, the embedding and rerank caches, with fakes. | |

## Not in this plan

- **Facet lists** (plan RF, deferred).
