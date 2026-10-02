# Review: architecture, 2026-10-01

- **Status:** Open.
- **Finding prefix:** `AR`
- **Subject:** cameo-ingest at commit `949030f` (version 0.5.2), after the follow-up review
  (`followup-2026-09-30.md`, closed) and plans DV, RE and RF. That is about 13,200 lines: the
  ingest package, the evaluation package, the scripts and the tests.
- **Focus:** architecture, separation of concerns, and redundancy and refactoring opportunities,
  as the maintainer asked. Bugs found on the way are included.
- **Reviewers:** Claude Opus 5.5, with three Claude subagents, each reading one part in full:
  - the core ingest (`pipeline`, `emit`, `ledger`, `plain`, `text`, `semantics`, `richtext`,
    `model`, `xmi`, `archive`, `provenance`);
  - diagrams and LLM work (`diagrams`, `layout`, `modules`, `llm`, `prompts`, `quality`,
    `progress`, and the LLM side of `pipeline`);
  - the evaluation package, the scripts and the tests.

  Claude read the orchestration and tree-level outputs (`cli`, `runner`, `state`, `exports`,
  `crossref`) and merged the reports.

Findings are numbered `AR-NNN`, and their remediation steps `AR-NNNRn`.

## Methodology

- **Reading:** every finding was checked against the code, with file and line references.
- **Reproducing:** the claimed bugs were reproduced on purpose-built inputs:
  - AR-001 with the fixture model;
  - AR-002 with a fictional requirement whose text starts `[TBD]`;
  - AR-003 by calling `plain.plain` and `plain.section`;
  - AR-012's quality bug by reading its label list against the annotations.
- **Measuring:** two reviewers measured on scratch trees (the evidence counts in AR-006, the
  heading lengths in AR-004, the profile in AR-021). The import graph was mapped for layering.
- **Not covered:** performance beyond the cases noted; the LLM prompts' wording, which plan LQ
  covers.

## The shape of the code

The layering holds:
- **The lowest layers** (`archive`, `layout`, `progress`, `text`) import nothing of their own.
- **The ingest never imports the evaluation.**
- **Strengths worth keeping:**
  - `xmi.py`: a streaming, schema-agnostic parser;
  - `archive.py`: detection by content, and a bounded zip budget;
  - `provenance.py`: small frozen value objects;
  - `Template`/`Slot` prompts, versioned into every derivation;
  - the `LLMStore`: a request hash that is safe to commit as a fixture;
  - one numbered `DiagramGraph`, feeding legend, sketch and modules alike;
  - deterministic partitioning;
  - content-hash caches throughout;
  - the fiction builder, and its answer-key tests.

Four themes run through the findings:
1. **Rendered text used as an interface.** Stages hand each other rendered text, and the next
   stage parses it back:
   - plain chunks regex-parse the page Markdown (AR-003);
   - `describe` inspects its link callback's output (AR-002);
   - `quality` matches page Markdown (AR-012);
   - the index reads the per-project CSV tables and `chunks.jsonl` (AR-012).

   Each wording change downstream then breaks something upstream silently. Structured
   intermediate forms would end this.
2. **One concept, many implementations:**
   - element labels and requirement ids (AR-010);
   - relationship verbs (AR-011);
   - Markdown to plain text (AR-023);
   - packing rows into parts, and chunk records (AR-015);
   - setting defaults (AR-013);
   - HTTP clients and caches (AR-017);
   - fictional-project prefixes (AR-022).

   They have already drifted apart.
3. **Hubs that do everything:**
   - `ProjectWriter` (AR-007);
   - `ingest_project` (AR-008);
   - `exports.rebuild` (AR-014);
   - the `LLM` class (AR-016);
   - `retrieval_eval.main` (AR-021).
4. **The evaluation's validity rests on untested code in a script** (AR-005), and one question
   set measures less than it seems to (AR-006).

## Summary

| ID | Severity | Title | Verified | Status |
|---|---|---|---|---|
| AR-001 | High | `--no-cross-index` crashes every run, and `--no-threads` deletes `CROSSREF.md` | Reproduced | Fixed |
| AR-002 | High | An unnamed requirement whose text starts with `[` fails its whole project when a vision model is set | Reproduced | Fixed |
| AR-003 | High | Plain chunks are made by regex-parsing the page Markdown, which corrupts model text | Reproduced | Partly fixed |
| AR-004 | Medium | The two chunk styles branch in five places and have drifted: generated and ledger chunks break the plain style's rules | Reproduced | Open |
| AR-005 | High | Grading by construction lives in a script, untested, with two different rules | By inspection | Open |
| AR-006 | Medium | The within-model questions' evidence groups are bare names, so their measures are inflated | Measured | Open |
| AR-007 | Medium | `ProjectWriter` is a god object, and pipeline and ledger reach into its internals | By inspection | Open |
| AR-008 | Medium | `ingest_project` mixes six jobs; request kinds are bare strings | By inspection | Open |
| AR-009 | Medium | Prompt values are built in three modules and two scripts, with wording and limits outside the versioned templates | By inspection | Open |
| AR-010 | Medium | An element's label and a requirement's id are worked out in about eight places, with different results | Reproduced | Open |
| AR-011 | Medium | Relationship wording is defined in three to five places | By inspection | Open |
| AR-012 | Medium | Per-project files and rendered text serve as undeclared APIs, and readers have already broken | Reproduced | Partly fixed |
| AR-013 | Medium | Settings, project options and their defaults are spread over five modules | By inspection | Open |
| AR-014 | Medium | `exports.rebuild` does seven jobs, and tree-level chunks are made in two modules | By inspection | Open |
| AR-015 | Medium | Chunk records are loose dicts made in four places, and packing rows into parts is written three times | By inspection | Open |
| AR-016 | Medium | The `LLM` class mixes transport, store, replay, run policy and report | By inspection | Partly fixed |
| AR-017 | Medium | HTTP clients, retries and SQLite caches are written two or three times | By inspection | Open |
| AR-018 | Medium | LLM summary inputs are page Markdown, link targets and all | By inspection | Open |
| AR-019 | Medium | `diagrams.py` and `modules.py` each carry several unrelated responsibilities | By inspection | Open |
| AR-020 | Medium | `retrieval_eval.main` is library code; `judge_pools` cuts windows again on its own defaults | By inspection | Open |
| AR-021 | Medium | The KOIS project duplicates the fiction builder, and fictional prefixes are listed in four places | By inspection | Open |
| AR-022 | Medium | The test suite: a 1,168-line module, no `conftest.py`, repeated setup, untested library code | By inspection | Open |
| AR-023 | Low | Five Markdown-to-plain converters and four link patterns | By inspection | Open |
| AR-024 | Low | SQL against `state.sqlite` is written outside `state.py` | By inspection | Open |
| AR-025 | Low | The prompt registry is two hand-kept lists, current and retired templates mixed | By inspection | Open |
| AR-026 | Low | Dead code, finished studies left in `scripts/`, and the evaluation in the product wheel | By inspection | Open |

## Findings

### AR-001: `--no-cross-index` crashes every run, and `--no-threads` deletes `CROSSREF.md`

**Severity:** High · **Verified:** Reproduced · **Where:** `src/cameo_ingest/exports.py:112-130`

**Status:** Fixed on 2026-10-02. The index and threads have independent blocks in `exports.rebuild`; `test_tree_switches` runs every combination of index, threads and `rag/` on and off.

The threads block (RF-05) was inserted between the index's computation and the code that writes
`CROSSREF.md`, so that code now hangs on the threads switch:
- **With `--no-cross-index` and threads on:** `crossref.page(merged)` runs with `merged`
  undefined. Every run ends in `UnboundLocalError` (reproduced: exit 1).
- **With `--no-threads`:** the `elif` deletes `CROSSREF.md` though the index is on (reproduced).

No test sets either switch. The commits are unpushed.

**Remediation:**
- **AR-001R1:** Give each switch its own block: the index computes `merged` and writes
  `CROSSREF.md`, or removes it; threads only append chunks.
- **AR-001R2:** A test that runs every combination of `--cross-index`, `--threads` and
  `--rag-files` on the fixture model.

### AR-002: An unnamed requirement whose text starts with `[` fails its whole project when a vision model is set

**Severity:** High · **Verified:** Reproduced · **Where:** `src/cameo_ingest/diagrams.py:295-306` (`describe.ref`), `pipeline.py:373`

**Status:** Fixed on 2026-10-02. `describe` takes a `Refs` (an element's link target, or none) and writes a label as text when there is no target. The diagram test covers a label starting `[Deleted]`.

`describe(…, link)` decides whether its callback gave Markdown by inspecting the string:
`if linked.startswith("["): … linked[linked.rindex(']('):]`.
- **How it fails:** for the LLM request, pipeline passes `ix.label`, which returns plain text.
  Since 0.5.1, an unnamed requirement is labelled by its text. A text that starts with a
  bracket that isn't an id, such as `[TBD] The system shall stop.`, makes `rindex` raise
  `ValueError`. The call is outside any `try`, so the runner marks the whole project failed.
  Reproduced: exit 4.
- **The same design leaks Markdown into prompts:** `describe` always applies `md_inline`, so
  "plain" requests carry escapes. 57 of 2,493 logged diagram and module prompts contain them
  (`T/T \< Threshold`).

This was introduced by a pushed commit (`cb0c6ba`).

**Remediation:**
- **AR-002R1:** Pass a renderer, not a string-returning callback:
  - its methods: `esc(text)` and `ref(element_id, text)`;
  - `MarkdownRenderer`: links to pages, escaping;
  - `PlainRenderer`: identity.

  `describe` composes, and never inspects.
- **AR-002R2:** A regression test with a bracket-led unnamed requirement on a diagram, LLM on
  (replayed).

### AR-003: Plain chunks are made by regex-parsing the page Markdown, which corrupts model text

**Severity:** High · **Verified:** Reproduced · **Where:** `src/cameo_ingest/plain.py:31-140`, `emit.py:247-262`, `text.py:49` (`md_escape`)

**Status:** Partly fixed on 2026-10-02 (0.5.3). AR-003R1 is done: `plain` removes only the emphasis emit writes (bold labels and names, a member's role, an annotation's origin); quotes are removed only from the requirement text; `#` lines are kept inside blocks; a block's name keeps its parenthesis unless it is a count; and the table configuration and annotation labels start blocks of their own. A test covers each case. AR-003R2 remains.

**How the chunks are made:**
- `emit.section` renders a page section as Markdown.
- `plain.section` takes it apart again with regexes:
  - `_BLOCK` and `blocks()`;
  - hard-coded prefixes (`"- **Kind:**"`);
  - `DETAIL_BLOCKS`, which must match emit's bold labels.
- Model text enters the Markdown unescaped (`md_escape` escapes nothing), so Markdown-like
  characters in it are interpreted.

**Reproduced:**
- `plain("self.mass <= 2 * self.tare * 1.5")` gives `self.mass <= 2  self.tare  1.5`: the
  emphasis pattern eats the multiplication signs. Constraints and OCL lose their operators.
- A documentation line `> 5 bar: trip` becomes `5 bar: trip`.
- A documentation line `#1 priority is safety.` disappears: `blocks()` drops every line that
  starts with `#`.
- `**Specification (OCL2.0):**` loses its language: group 2 of `_BLOCK` is discarded.
- The table configuration line (`emit.py:582`) doesn't match `_BLOCK`, so it is glued onto the
  previous block.

**Why it matters:** plain is the default style, so this reaches the embeddings. And every
wording change in `emit.section` silently changes how chunks are split into meaning and detail.

**Remediation:**
- **AR-003R1 (now):** Stop the corruption:
  - limit the emphasis and quote rules to the markup emit itself writes;
  - keep `#` lines inside blocks;
  - keep the specification's language.
- **AR-003R2:** A structured section view built once per element:
  - its parts: title; fields as pairs; blocks with a meaning or detail flag; lines whose
    references are `(label, target)`;
  - two renderers: `to_markdown` for pages and `to_plain` for chunks and LLM inputs.

  `blocks`, `_BLOCK`, `_TRACE` and section-level `plain()` then go. This also serves AR-004 and
  AR-018.

### AR-004: The two chunk styles branch in five places and have drifted: generated and ledger chunks break the plain style's rules

**Severity:** Medium · **Verified:** Reproduced · **Where:** `emit.py:202, 250, 267, 381, 525, 646`, `ledger.py:133-155`, `exports.py:148`, `plain.py:108`

**Branching:** `chunk_style` is tested in five places. A typo in `!= "plain"` silently selects
Markdown.

**Breaks with the plain style's rules (RE-08: every window says whose text it is):**
- **Generated chunks don't name their project.** Their heading is "Summary of Package X
  (generated by …)". Every other plain heading ends with the project's label.
- **Module-summary headings list up to 25 element names:**
  - up to 674 characters in `out/fic3`, repeated in every piece;
  - with DOORS-style labels, about 750 tokens. `parts` then falls back to 40 tokens of room
    and makes pieces twice the window (reproduced by a reviewer).
- **The project chunk keeps its `#` headings.**
- **The plain ledger header keeps backticks and the full qualified name.**

**Metadata and API:**
- Split metadata is `piece/pieces` in one place, `part/parts` in two others, and `part` is
  also a dict for module summaries.
- `section_chunks` passes a title through `extra` and pops it, changing the caller's dict.
- The README chunk swaps in the label by string replacement.

**Remediation:**
- **AR-004R1:** One plain heading builder for every chunk, generated and ledger chunks
  included. The "covering …" name list goes to metadata, which already holds `elements`.
- **AR-004R2:** `parts` caps the heading's share of the budget.
- **AR-004R3:** Rename the module and part metadata (`covers`), so that `part/parts` only ever
  means splitting.
- **AR-004R4 (decision):** Retire the Markdown chunk style, or make it a strategy object chosen
  once. It was judged worse and kept only for continuity; retiring it would remove most of the
  branching. Pages stay Markdown either way.

### AR-005: Grading by construction lives in a script, untested, with two different rules

**Severity:** High · **Verified:** By inspection · **Where:** `scripts/retrieval_eval.py:58-92, 185-189`, `tests/test_fiction.py:31-34`, `tests/test_evaluation.py:41-42`, `evaluation/synthetic.py`

**Where the grading is:**
- `grades()`, the coverage logic and `group_measures` are what every measure in plans RE and RF
  rests on.
- They live in a script that tests can't import, and no test covers them.
- The rule is chosen by which keys a question dict happens to have (`evidence_groups`, `prefix`,
  `evidence`).

**The rules differ:**
- **For a KOIS question:** any window of an answering element gets a 2, whether it holds the
  fact or not.
- **For a fictional question:** only a window that holds the fact does.

So "synthetic" and "fictional" scores measure different things.

**Questions have no schema:** each source has its own keys:
- KOIS: `fact`, `evidence`;
- the builder: `difficulty`, `evidence_by_element`, `prefix`, `project`;
- across and within: `evidence_groups`;
- natural: `quote`, `answer_chunks`.

The answer-key test restates the rule without the `index:id` case.

**Remediation:**
- **AR-005R1:** `evaluation/grading.py`:
  - a `Question` type with an explicit rule (`element | fact | parts | quote`);
  - `grade(q, unit)` and `covers(q, unit)`;
  - `holds` and the flattening it needs, done once per unit.

  The script and the tests call it.
- **AR-005R2:** Offline tests of each rule on hand-made units.
- **AR-005R3:** KOIS takes the fact rule when it is ported (AR-021). Its scores are then
  rebased, as noted in plan RE.

### AR-006: The within-model questions' evidence groups are bare names, so their measures are inflated

**Severity:** Medium · **Verified:** Measured · **Where:** `evaluation/fiction/rivals.py:166-186` (`within`), `tests/test_fiction.py:38-41`

The within-model questions' groups are element names, not facts:
- `[["UV Dose"], ["UV Reactor"]]`;
- `[["FVX-SUB-031"], ["FVX-SUB-032"], ["Barrier Machine"]]`.

In a scratch tree, "Barrier Machine" is in 20 chunks, "UV Reactor" in 17 and "UV Dose" in 13.
Any of them earns credit, so the within-model coverage reported in
`docs/research/related-facts-2026-10-01.md` is inflated. The thread results there can't be
relied on. The across-model questions mostly use facts ("required by RWT-REG-002", "5,200
cubic metres") and are sound. The stray check in the tests covers `evidence`, not
`evidence_groups`.

**Remediation:**
- **AR-006R1:** Phrase each group as a relation or a fact ("Barrier Machine satisfies", "derived
  from FVX-SYS-003"), and extend the stray check to groups.
- **AR-006R2:** Measure the threads again and correct the research note and plan RF's RF-05 and
  RF-06 statuses. The default for threads waits on the result.

### AR-007: `ProjectWriter` is a god object, and pipeline and ledger reach into its internals

**Severity:** Medium · **Verified:** By inspection · **Where:** `emit.py:65-846`, `pipeline.py:339-546`, `ledger.py:23-24, 77`

**What `ProjectWriter` holds** (846 lines):
- the model's derived indexes (relationships by end, flows, notes, diagrams showing each
  element);
- file planning (paths, anchors, links);
- the diagram graph and partition caches;
- every page's Markdown;
- every chunk, in both styles;
- the CSV and JSON tables.

**How others reach in:**
- `LedgerWriter` needs the writer back: a circular dependency hidden behind `TYPE_CHECKING`.
- Pipeline:
  - calls the private `_section_elements_in`;
  - assigns `writer.package_parts`;
  - appends to `writer.out.files`;
  - writes images under `writer.root` and builds `images.md` itself.
- The order of these calls matters, and nothing states it.

**Remediation:**
- **AR-007R1:** Split it into five pieces:
  - `ProjectView`: the semantic indexes and caches, and sections by package;
  - `FilePlan`: paths, anchors and links;
  - `PageWriter`;
  - `ChunkSink`: one chunk factory (AR-015);
  - `TableWriter`.

  The ledger takes the view, plan and sink.
- **AR-007R2:** Pipeline passes package parts and image notes as data.

### AR-008: `ingest_project` mixes six jobs; request kinds are bare strings

**Severity:** Medium · **Verified:** By inspection · **Where:** `pipeline.py:317-562`, `emit.py:56, 383`

**The six jobs:** `ingest_project` (245 lines):
- renders sketches;
- writes files;
- builds five kinds of LLM requests;
- folds the answers back, in two dispatch blocks;
- runs the summaries-of-summaries loop;
- writes `images.md`.

**Request kinds:** they are strings:
- "diagram", "module", "image", "summary", "part", "run" (the docstring lists four);
- an `else` takes any other kind as an image.

**Naming:**
- `module` means both a module of a large diagram and a part of a large package.
- Annotation display labels become chunk kinds by string munging.

**Things that belong elsewhere:**
- `_fit_image`, which repeats the sketch canvas's sizing;
- the FU-019 layout id rewrite;
- a second magic-bytes table.

**Remediation:**
- **AR-008R1:** An `enrich` module:
  - typed requests, with an `AnnotationKind` that holds both display label and chunk kind;
  - one round loop: `while batch := enricher.next_round(): enricher.fold(batch, answers)`.
- **AR-008R2:** Move `_fit_image` beside `canvas`, the id rewrite into `layout`, and
  `images.md` to the page writer.

### AR-009: Prompt values are built in three modules and two scripts, with wording and limits outside the versioned templates

**Severity:** Medium · **Verified:** By inspection · **Where:** `pipeline.py:179-264, 373-386, 432`, `modules.py:356-369`, `prompts.py`, `scripts/sandwich_study.py:72-92`, `scripts/long_context_study.py:63-87`

**Where values are built:**
- the diagram description: inline in pipeline;
- module description and diagram synthesis: in `modules`;
- package summary: inline;
- instances, module summary and package synthesis: pipeline functions.

There are two unrelated `synthesis_values`.

**Wording no template version covers:** sentences that reach the model:
- "The text was cut at …";
- "(Only the first 150 shapes …)";
- "(The digest was cut here.)".

Changing them changes requests without changing the template's version, which defeats the
versioning that quality ratings rely on.

**Limits written twice:** slot descriptions restate pipeline constants as literals (150, 12,000,
6,000, 8,000, 4,000, 30).

**Other problems:**
- `package-summary@v2`'s `CUT_NOTE` is always empty.
- A diagram with no type is sent as "(None)".
- The two study scripts copy pipeline's package walk, private call included.

**Remediation:**
- **AR-009R1:** A builder per template, beside it, returning values, notes and whether it was
  cut. Limits become named constants, interpolated into slot descriptions and cut notes alike.
- **AR-009R2:** A shared `package_plan(view, package)` (whole, instances or parts) for pipeline
  and the studies.
- **AR-009R3:** A test that renders every current template from its builder on the fixture.

### AR-010: An element's label and a requirement's id are worked out in about eight places, with different results

**Severity:** Medium · **Verified:** Reproduced · **Where:** `model.py:102-115`, `text.py:70-83`, `emit.py:236-244, 304, 311`, `ledger.py:98-118, 200`, `diagrams.py:67-138`, `crossref.py:36, 98-130`, `pipeline.py:189-193`, `evaluation/questions.py:29`

**The requirement id:**
- `ModelIndex.label` (the schema-free data layer) applies SysML and DOORS requirement logic,
  taking an `Id` tag from any stereotype.
- The page shows the database number (`Requirement ID: 16001`).
- The ledger row shows the database number, then the label (with the DOORS id and the start of
  the text), then the text, which starts with the id again. Reproduced:
  `**16001** [RWT-REG-001: The turbidity …] — "[RWT-REG-001] The turbidity …"`.
- A diagram legend shows the raw Id tag (`16001`) where a link to the same requirement reads
  `RWT-REG-001: …`.
- The DOORS id pattern is defined three times.

**Labels and kinds:**
- An unnamed element is "(Class)", "(unnamed Class)" or "(unnamed)", depending on the module.
- The kind word drops «DiagramInfo» in headings, not in ledgers.
- In diagrams, six functions decide labels: `_name`, `_described`, `element_label`,
  `_shown_name`, `describe.ref`, and `ix.label`.
  - Their comments record fixes made one path at a time.
  - The trigger branch re-implements `sem.trigger_text` and misses change and time events.

**Remediation:**
- **AR-010R1:** In `semantics`:
  - `requirement(view, el) -> Requirement(id, db_id, text, title)`, with the pattern defined
    once;
  - `label(view, id)` and `kind_word(view, el)`;
  - used by emit, ledger, diagrams, pipeline and crossref.

  `ModelIndex.label` goes back to generic.
- **AR-010R2:** Diagram nodes carry a structured label (stereotype, name, type, description),
  computed once.
- **AR-010R3:** The ledger and pages show the requirement's id once, with its database number
  as a field.

### AR-011: Relationship wording is defined in three to five places

**Severity:** Medium · **Verified:** By inspection · **Where:** `diagrams.py:55-60` (`VERBS`), `emit.py:357`, `ledger.py:32-40` (`REQ_LINKS`), `crossref.py:39-40, 253-255`, `emit.py:748-752`

**Where the wording is defined:**
- `diagrams.VERBS`: page text takes its vocabulary from here, a drawing module that loads
  Pillow.
- `ledger.REQ_LINKS`: other words ("copies" against "is a copy of", "derived into").
- `crossref.VERBS`: a third table. Its inverses are made by chains of `.replace()`.
- `requirements.csv`: encodes relationships as `kind_in`/`kind_out`.

**Remediation:**
- **AR-011R1:** One table in `semantics`, `kind -> (forward, inverse)`, and
  `phrase(relationship, from_id)`, used everywhere.

### AR-012: Per-project files and rendered text serve as undeclared APIs, and readers have already broken

**Severity:** Medium · **Verified:** Reproduced · **Where:** `crossref.py:53-130, 220-230`, `quality.py:53-87`, `emit.py:381-382, 393, 525-526, 646-647`, `pipeline.py:537-540`

**Status:** Partly fixed on 2026-10-02. The label list in `quality` is gone: a reference page drops the answer under any bold label before its "generated by" sentence, so part summaries are no longer judged against themselves (a test covers one). The rest of AR-012R2, and AR-012R1 and R3, remain.

**The index reads files back:**
- It reads the per-project CSV tables and `chunks.jsonl`.
- From them it re-derives titles, kinds (splitting `stereotypes` on `;`) and owners
  (`rsplit("::")`).
- It finds each element's main chunk by the order and kind of chunks.

Any change to a table's columns breaks it silently.

**`quality` reads rendered text back:**
- **Separating the answer:** it takes a generated chunk's answer by splitting on the first
  blank line, which is wrong for split pieces.
- **Its label list misses a kind:** to strip answers from reference pages, it matches the
  annotation Markdown against a hard-coded label list. The list lacks "Summary of parts …", so
  those answers stay in the reference they are judged against.

**The "generated by" sentence:** "(generated by X; not part of the source model)" is formatted in
six places.

**Remediation:**
- **AR-012R1:** At build time, write `index/ids.jsonl` from the in-memory model: identifier,
  title, what the element is, its main chunk. The tree-level index merges these files.
- **AR-012R2:** Chunk metadata carries `primary_chunk` and the annotation's id. `quality` reads
  structure, not text. Fix the label list now.
- **AR-012R3:** One `generated_label(derivation)`.

### AR-013: Settings, project options and their defaults are spread over five modules

**Severity:** Medium · **Verified:** By inspection · **Where:** `cli.py:45-47, 133-187, 281-350`, `runner.py:41-46, 191-195`, `pipeline.py:319`, `emit.py:70`, `exports.py:112-149`

**Two kinds of setting:**
- **Project options:** render, models, pixels, modules, chunk style, templates. They are hashed
  into each project's identity, and assembled as a `dict` in the CLI.
- **Tree settings:** the rag files, source line, index, threads and line references. They are
  read in `exports` with `settings.get(key, default)`.

**Defaults are restated:**
- The `plain` default appears in four modules (`cli.py:347`, `runner.py:195`,
  `pipeline.py:319`, `emit.py:70`).
- The tree settings' defaults appear only in `exports`, one `get` each.
- A misspelt key silently takes the default.

**The CLI knows project internals:** it imports `diagrams.IMAGE_PIXELS`, `modules.thresholds`
and `prompts.CURRENT` to build the options.

**Repetition:** five on/off flag pairs are written out by hand.

**Remediation:**
- **AR-013R1:** A `config` module:
  - `TreeSettings` (stored) and `ProjectOptions` (hashed): typed, with defaults in one place;
  - `ProjectOptions.hash()`.

  Pass the objects, not dicts, from CLI to runner, pipeline and exports.
- **AR-013R2:** A helper that adds an on/off flag pair, with its default in the help.

### AR-014: `exports.rebuild` does seven jobs, and tree-level chunks are made in two modules

**Severity:** Medium · **Verified:** By inspection · **Where:** `exports.py:68-151`, `crossref.py:207-313`

**The seven jobs:** `rebuild` writes, in one function:
- the manifest;
- `provenance.jsonl`;
- `INDEX.md`;
- the projects ledger;
- the index and `CROSSREF.md`;
- threads;
- `chunks.jsonl`;
- `rag/`.

AR-001's bug came from this.

**Tree-level chunks:** they are made in `exports` (the projects ledger) and `crossref` (index
entries and threads).

**Threads are misplaced:**
- they belong to one model, yet are computed at tree level from that model's tables;
- they land in `rag/text/_tree`, not in the model's folder.

**Stale docstring:** `exports` says only `provenance.jsonl` names local paths; `rag/meta` does
too.

**Remediation:**
- **AR-014R1:** `rebuild` calls one function per output, each with its own test.
- **AR-014R2:** Threads are made with the project's own chunks at build time (with AR-012R1),
  so that they live and are labelled with their project.
- **AR-014R3:** Fix the docstring.

### AR-015: Chunk records are loose dicts made in four places, and packing rows into parts is written three times

**Severity:** Medium · **Verified:** By inspection · **Where:** `emit.py:193-214`, `crossref.py:174-192, 296-312`, `exports.py:283-311`, `plain.py:105-129`, `ledger.py:135-150`

**Chunk records:**
- They are built as dicts in `emit`, `crossref` (twice) and `exports`.
- Each has its own id scheme and its own metadata conventions: `content` or not, `file` with or
  without the project's directory, the shape of `provenance`.
- The invariants are checked only in a test helper.

**Packing into parts:**
- `plain.parts`, `ledger.emit_group` and `exports._projects_ledger` each pack rows into parts.
- The last imports the ledger's private names, and compares characters with tokens.

**Remediation:**
- **AR-015R1:** A `Chunk` type and factory in one module: id scheme, required metadata,
  validation. `check_invariants` uses it.
- **AR-015R2:** One `pack(rows, heading, budget, max_rows)` in `plain`.

### AR-016: The `LLM` class mixes transport, store, replay, run policy and report

**Severity:** Medium · **Verified:** By inspection · **Where:** `llm.py:179-350`, `pipeline.py:327, 370, 376, 452`, `scripts/judge_pools.py:82`

**Status:** Partly fixed on 2026-10-02. AR-016R2 is done: a failed `put` is logged and the answer kept (a test covers it). AR-016R1 remains.

**What the class does:**
- builds the client;
- keeps the response store and replay;
- applies a call budget;
- runs the circuit breaker;
- records outcomes;
- logs requests.

**Problems:**
- Pipeline uses it to record events that are not calls (`skip(…, "skipped_trivial")`).
- Truncation is recorded three ways.
- The evaluation has to defeat the breaker (`max_failures=10**9`).
- `store.put` is not guarded against `sqlite3.DatabaseError` as `get` and `log_request` are, so
  a database error after a paid answer fails the project.
- There is no seam to inject a client; tests patch `openai.OpenAI`.

**Remediation:**
- **AR-016R1:** Split into three pieces that `ask` composes:
  - `ChatClient` (OpenAI or replay; injectable);
  - `ResponseStore`;
  - `EnrichmentSession` (budget, breaker, outcomes, request log).

  The evaluation uses client and store with its own policy.
- **AR-016R2 (now):** Guard `put`.

### AR-017: HTTP clients, retries and SQLite caches are written two or three times

**Severity:** Medium · **Verified:** By inspection · **Where:** `evaluation/embed.py:103-168`, `evaluation/rerank.py:50-80`, `llm.py:129-135, 203`

**Duplicated code:**
- `Embedder._post` and `Reranker._post` have the same retry loop.
- The caches have the same SQLite setup, without the store's recovery from a corrupt database.

**A race:** `Embedder` updates its counters from worker threads without a lock.

**DeepInfra configured three ways:**
- `DEEPINFRA`;
- `INFERENCE`;
- `OPENAI_BASE_URL`.

**Leftovers from the dropped local containers:**
- `EmbeddingModel.endpoint`;
- an optional `key_env` that is never absent.

**Remediation:**
- **AR-017R1:** Embed through the OpenAI SDK (the endpoint is compatible), which brings its
  retries. Keep one `post_json` with retries for the reranker.
- **AR-017R2:** A small `SqliteCache` base for both caches.
- **AR-017R3:** One place for the provider's settings.
- **AR-017R4:** Remove the leftovers.

### AR-018: LLM summary inputs are page Markdown, link targets and all

**Severity:** Medium · **Verified:** By inspection · **Where:** `pipeline.py:424-432`

**What goes to the LLM:** package summaries and part summaries send `writer.section(…)`, the
page Markdown.

**Why that costs:**
- Each link is about 110 characters of path for a 15-character label. The plain module's own
  docstring puts that apparatus at 45% of the characters.
- The character limits (`SUMMARY_INPUT_CHARS`, `PART_CHARS`, `OWN_CHARS`) count it. So more
  packages are split into parts, and every prompt costs more.

**A hidden dependency:** the call leaves `generated=True` and relies on no annotations existing
yet.

**Remediation:**
- **AR-018R1:** Send the plain rendering (AR-003R2, or `link=ix.label` meanwhile), with
  `generated=False`. This changes the prompt hashes: bump the template version, and accept one
  round of cache misses (for TMT, many).

### AR-019: `diagrams.py` and `modules.py` each carry several unrelated responsibilities

**Severity:** Medium · **Verified:** By inspection · **Where:** `diagrams.py` (582 lines), `modules.py` (369 lines), `pipeline.py:134-154`

**`diagrams.py` holds:**
- the vocabulary and labels;
- graph extraction (`build`);
- text (`describe`);
- Pillow rendering;
- the vision model's pixel budget.

`emit` and `cli` import it for its verbs and `IMAGE_PIXELS`, which loads Pillow.

**`modules.py` holds:**
- CLI parsing (`thresholds`);
- diagram partitioning;
- package partitioning (`_Sequence`, outside its docstring's scope);
- sketch presets;
- text;
- prompt values.

**Other problems:**
- `_Sequence` subclasses `_Graph` without calling its constructor.
- Bounding boxes are computed three ways, one of them (`Layout.bounds`) never called.

**Remediation:**
- **AR-019R1:** Split into modules:
  - `diagram_graph` (build, nodes, links, labels);
  - `diagram_text`;
  - `sketch` (rendering, frames, presets);
  - `vision` (pixel budget, one `fit_size` used by sketches and images);
  - `partition` (one base, with diagram and package adapters; the `Partition` holds its graph).

  CLI parsing moves to the CLI, the verbs to `semantics` (AR-011).

### AR-020: `retrieval_eval.main` is library code; `judge_pools` cuts windows again on its own defaults

**Severity:** Medium · **Verified:** By inspection · **Where:** `scripts/retrieval_eval.py:95-234`, `scripts/judge_pools.py:55, 63`, `evaluation/synthetic.py:135-139`

**`main()` does everything:**
- loads three question sources;
- applies judgments;
- cuts windows;
- runs BM25, dense search, fusion and reranking;
- grades;
- measures;
- writes outputs;
- renders the report.

**Wasted work:** grading runs once per system though grades don't depend on the system: about
18 times the work with four models and a reranker. `holds` flattens text again on every call:
1.9 s of a 5.3 s test.

**`judge_pools` re-cuts windows:**
- It cuts windows itself, always at 512/64. After a run at other sizes, the judges would grade
  other text under the same window ids.
- It hard-codes `out/eval/questions`.
- The rankings' schema is defined only by what the script writes.

**Remediation:**
- **AR-020R1:** Split into `evaluation/systems.py`, `grading.grade_all` (once) and
  `evaluation/report.py`; the script keeps the arguments.
- **AR-020R2:** `retrieval_eval` writes the windows it used (or their parameters) beside the
  rankings, and `judge_pools` reads them.
- **AR-020R3:** One module for reading and writing questions, rankings and judgments.

### AR-021: The KOIS project duplicates the fiction builder, and fictional prefixes are listed in four places

**Severity:** Medium · **Verified:** By inspection · **Where:** `evaluation/synthetic.py`, `scripts/make_synthetic_project.py`, `evaluation/questions.py:28`, `scripts/retrieval_eval.py:48`, `scripts/judge_pools.py:59`

**KOIS hand-writes what the builder makes:** `synthetic.py` hand-writes the XMI, layouts and
archive (280 lines).
- **Less faithful:** every diagram is a "Class Diagram", and diagrams have no owner.
- **Special cases it causes:**
  - `SYNTHETIC`;
  - `--questions synthetic`;
  - a script;
  - a weaker test.

**Prefix lists:** the fictional prefixes are listed in four places. A project added to
`fiction.PROJECTS` but not to `FICTIONAL` leaks into the structural and natural question sets.

**Remediation:**
- **AR-021R1:** Port KOIS to the builder (`fiction/orchard.py`). Its element ids survive; its
  token and chunk ids change. Delete `synthetic.py` (after moving `holds` to grading), the script
  and the special cases.
- **AR-021R2:** Derive the prefixes from `fiction.PROJECTS`, with one `is_fictional(id)`.

### AR-022: The test suite: a 1,168-line module, no `conftest.py`, repeated setup, untested library code

**Severity:** Medium · **Verified:** By inspection · **Where:** `tests/`

**Structure:**
- `test_pipeline.py` holds output, CLI, XMI, samples, LLM and ledger tests.
- `test_llm_live.py` imports from it.
- Its autouse environment fixture covers that module only.

**Repetition:** 21 copies of the same ingest setup. The `run()` helper hard-codes its flags.

**Misfiled:** `test_plain_chunk_text` tests the ingest, but sits in the evaluation tests.

**Slow:** the fiction tests ingest the same projects 15 times (13 s of a 49 s suite).

**Untested:**
- the structural and natural question generators;
- the judge's reply parsing;
- the embedding and reranking caches;
- the scripts.

**Remediation:**
- **AR-022R1:** A `conftest.py` (environment, fake OpenAI, a flexible `ingest()` helper,
  `check_invariants`).
- **AR-022R2:** Split `test_pipeline.py` by concern (output, CLI, XMI, samples, LLM, ledger).
- **AR-022R3:** A session-scoped fixture that ingests the fiction once per chunk style.
- **AR-022R4:** Small tests for the untested library code, with fakes.

### AR-023: Five Markdown-to-plain converters and four link patterns

**Severity:** Low · **Verified:** By inspection · **Where:** `plain.py:31, 67-77`, `text.py:65`, `ledger.py:43`, `evaluation/questions.py:136-140`, `evaluation/synthetic.py:128-132`, `scripts/retrieval_eval.py:52-55`

**The converters:**
- `plain.plain`;
- `text.md_plain` with `ledger._MD_LINK`;
- `questions._plain` (private, but imported by `judge` and the script);
- `synthetic._flat`;
- `retrieval_eval._norm`.

**A mistake one of them makes:** `_plain`'s link pattern doesn't handle the escaped brackets
`md_inline` writes, so what the judges read can keep link targets.

**Remediation:**
- **AR-023R1:** One `strip_links` in `text`.
- **AR-023R2:** `plain.plain` for what a reader sees, and one `flat()` for matching. The others
  go.

### AR-024: SQL against `state.sqlite` is written outside `state.py`

**Severity:** Low · **Verified:** By inspection · **Where:** `runner.py:108, 135-138, 149-151, 177, 231-271`, `cli.py:359`, `exports.py:69`

Nine statements in `runner`, `cli` and `exports` query the database directly: what to build,
counts, status, orphans. The `State` class exists to hold them.

**Remediation:**
- **AR-024R1:** `State` methods for each query (`todo`, `counts`, `status`, `orphans`).

### AR-025: The prompt registry is two hand-kept lists, current and retired templates mixed

**Severity:** Low · **Verified:** By inspection · **Where:** `prompts.py:525-533`, `evaluation/judge.py:19`, `evaluation/questions.py:111`

**The lists:** `CURRENT` and `TEMPLATES` are kept by hand. A duplicate key is silently dropped,
and nothing checks that the current templates are registered.

**What the registry holds:** 18 templates, of which eight are current:
- **retired versions:** the old diagram-description versions describe a context slot and an
  image size the code can no longer produce;
- **rejected experiments:** for example `module-summary@v2`, so the current module summary is
  v1 although a v2 exists.

**Other problems:**
- The evaluation's templates are not registered.
- Templates derived with `str.replace` would silently equal their base if the anchor text
  changed.

**Remediation:**
- **AR-025R1:** A `status` per template (current, retired, rejected), and a `register()` that
  refuses duplicates. `CURRENT` is derived from the status.
- **AR-025R2:** Move the non-current templates to an archive module; `quality` already copes
  with versions not in code.
- **AR-025R3:** Assert that each derived text differs from its base.

### AR-026: Dead code, finished studies left in `scripts/`, and the evaluation in the product wheel

**Severity:** Low · **Verified:** By inspection · **Where:** various

**Dead code:**
- `ProjectResult.outputs` and `Outputs.files` (the runner lists files itself), and every append
  to them;
- `Project.notes`;
- `Layout.bounds`, `View.depth`;
- a `type_label` computed and ignored (`emit.py:316`);
- `ledger._plural`, a copy of `text.plural`;
- a second HTML conversion of comment bodies;
- `md_escape`, which escapes nothing (AR-003).

**Short ids sliced by hand:** `[:8]` and `[:12]` in five places.

**Finished studies:** `partition_study`, `sandwich_study`, `long_context_study`,
`chunk_inventory` and `embedding_check` are done.
- **They depend on internals:** two call private pipeline and writer methods, so a refactor
  breaks them unnoticed.
- **They pin code in place:** they keep rejected templates in the registry (AR-025).

**The wheel:** the evaluation package (about 2,800 lines, 1,500 of them fictional data) ships
in the product wheel.

**Remediation:**
- **AR-026R1:** Delete the dead code; add `ContentInfo.short_id` and a `chunk_ref()` helper.
- **AR-026R2 (decision):** Move the studies to `scripts/studies/`, marked "as run at commit X",
  or delete them and cite their commits in the research notes.
- **AR-026R3 (decision):** Leave the evaluation out of the wheel, or split it into subpackages
  (corpus, retrieval, grading).

## Remediation order

The findings depend on one another. A sensible order:

1. **Bugs and validity, first:**
   - AR-001;
   - AR-002 (with a renderer, AR-002R1);
   - AR-003R1;
   - AR-012R2's label fix and AR-016R2;
   - AR-005 and AR-006: grading moved into a module and tested, the groups phrased as facts,
     the threads measured again, and the research note corrected.
2. **One source of truth:**
   - semantics owns labels, requirement ids and relationship wording (AR-010, AR-011);
   - text owns conversions (AR-023);
   - one chunk type and one packer (AR-015);
   - one config (AR-013).
3. **Structure:**
   - the section view and its renderers (AR-003R2, AR-004, AR-018);
   - splitting `ProjectWriter` and the enrichment (AR-007, AR-008, AR-009);
   - the per-project index file, and `rebuild` in steps (AR-012R1, AR-014);
   - diagrams and partitioning (AR-019);
   - the LLM session (AR-016, AR-017).
4. **The evaluation and the tests:** AR-020, AR-021, AR-022, AR-024 to AR-026.

Steps 2 to 4 change no output, except where noted (AR-004, AR-010R3, AR-018). They would go
into a refactoring plan, with output compared before and after on every sample.

**Decisions for the maintainer:**
1. **The Markdown chunk style (AR-004R4):** retire it, or keep it as a strategy?
2. **Finished studies (AR-026R2):** archive them, or delete them and cite their commits?
3. **The evaluation package (AR-026R3):** out of the wheel, or reorganized within it?
4. **Retired and rejected prompt templates (AR-025R2):** move them out of the runtime registry?
