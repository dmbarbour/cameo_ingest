# Review: code quality, 2026-10-07

- **Status:** Open. Stage 1 done (0.28.1): CQ-001 to CQ-004, CQ-021R1 but the renderers' `ix`.
  Stage 2 done (0.28.2): CQ-010, CQ-018, CQ-022, CQ-023 (but a browser test of Compare, left to
  CQ-020), CQ-024R1.
  Then (0.29.0): CQ-009, CQ-011 to CQ-014, CQ-017, and CQ-025 (the maintainer's: models looked
  for by name).
  The maintainer, starting the remediation: work from the easiest to the hardest, skip what needs
  their input, and deliberate architecture (options, pros and cons) before judging, with today's
  design counted only as the convenient option.
- **Finding prefix:** `CQ`. Findings are `CQ-001` and so on; remediation steps `CQ-001R1` and so on.
- **Subject:** cameo-ingest at `edbfc7c` (0.28.0): about 20,000 lines of Python in the package
  (17,000 outside the fiction builders), 1,265 lines of page script (`assets/search.js`), the
  tests and the scripts. The last such review (`docs/archive/reviews/architecture-2026-10-01.md`,
  at 0.5.2 and 13,200 lines) is closed; its decided matters aren't raised again.
- **Asked for** (the maintainer): "messy code, architecture and separation of concerns,
  refactoring opportunities", with tools to measure where they help.
- **Reviewers:** Claude Opus 5.5 took the measurements and merged; three Claude subagents each
  read one part in full: the tree-level orchestration and outputs (`cli`, `runner`, `exports`,
  `subjects`, `topics`, `lineage`, `shared`, `groups`, `catalog`, `searchpage`, `workbook`, ...);
  the per-project ingest and diagrams (`diagram_graph`, `sketch`, `sketch_svg`, `partition`,
  `view`, `pages`, `xmi`, `pipeline`, ...); and the page script, the tests and the scripts.

## Methodology

- **Tools** (run with `uvx`, none added to the project):
  - **radon:** cyclomatic complexity (`radon cc`, grades A to F) and a maintainability index
    (`radon mi`);
  - **ruff's `C901`** (McCabe complexity, counted more leniently than radon) and its `PLR09xx`
    size rules;
  - **vulture:** unused code, run over the package, scripts and tests together, every hit
    checked by `grep`;
  - **pylint's `symilar`:** copied blocks of 6 lines or more;
  - **lizard:** complexity of the page script;
  - **an import graph** (a short script over `ast`): cycles, imports inside functions, fan-in and
    fan-out;
  - **churn:** `git log` per file, to tell complex code that keeps changing from complex code
    that is done;
  - **pytest `--durations`** and cProfile, for the suite's time.
- **Reading:** every finding here was checked against the code; the bugs were reproduced or
  traced line by line.

## The measurements

- **Complexity:** 994 functions, mean B (6.1). Radon grades 22 in the package F (over 40) or E
  (31 to 40); ruff's count puts 4 over 25 (`catalog.project_catalog` 39, `diagram_graph.build` 29,
  `sketch.render_png` 41, `xmi._Parser.start` 31). Worst by radon: `diagram_graph.build` 120,
  `sketch.render_png` 80, `xmi._Parser.start` 58, `catalog.project_catalog` 49,
  `partition.partition` 49, `view.ProjectView.section_view` 46, `interactive.interview` 44,
  `workbook._project_rows` 42, `tables.TableWriter.write_tables` 42, `sketch_svg.render_svg` 42.
- **Maintainability index:** every module grades A except `cli.py` (C, 0.0: 1,022 lines),
  `subjects.py`, `pages.py`, `view.py` and the fiction builder (B).
- **Duplication:** 0.18% (31 of 17,010 lines), in three places: two in the sketches (CQ-013) and a
  prompt the study kept a copy of.
- **Imports:** no cycle at run time but `subjects` ↔ `topics` and `interactive` ↔ `cli`;
  `files` ↔ `view` is for type hints only. The ingest still never imports the evaluation.
  Most-imported: `text`, `provenance`, `model`, `semantics`.
- **The page script:** `detail` 35, `Subjects.group` 19, `alsoIn` 18 (lizard).
- **Tests:** 188 in 289 s (4 to 5 minutes); 85 s of it in three places (CQ-022).
- **Tool limits:** radon and vulture can't parse PEP 695 generics (`plain.pack[K]`, line 161)
  and skip that file.

## Findings

### Bugs

#### CQ-001: lineage orders two saves by comparing their times as text

- **Where:** `lineage.compare`, `lineage.py:137`: `(x.saved or "", x.sha) <= (y.saved or "", y.sha)`.
- **What:** `saved` is ISO 8601 with the saver's own UTC offset. `"2023-11-02T11:39:23-07:00"`
  sorts before `"2023-11-02T15:00:00+01:00"` as text, but is later in time. `groups._when` turns
  times to UTC before ordering (`groups.py:65-78`); lineage doesn't.
- **Cost:** two bids saved in different time zones on the same day can swap older and newer:
  version against derived, and the direction of "built on", disagree with the groups' order.
  Bidders in other time zones are the maintainer's ordinary case.
- **CQ-001R1:** order by the same UTC key as `groups` (one helper, used by both), with a test of
  two offsets.
- **Done (0.28.1):** `groups.utc`, used by both; `test_lineage.py::test_the_older_is_older_in_utc`.

#### CQ-002: the search page keeps the last search's state after the box is cleared

- **Where:** `search.js`: `state.copies` is set only by a search (`:685`) and read by every result
  row (`:1041`); `last` (`:663`) is read by the detail pane's highlighting (`:1068`).
- **What:** cleared, the box returns to browsing or comparing before `:685`, so browse and compare
  rows reuse the old search's copies ("X and 1 more", or not, by what was searched before), and
  the detail pane goes on marking the old words.
- **CQ-002R1:** reset both whenever a view other than search is drawn; keep them in `state`.
- **Done (0.28.1):** `state.terms` and `state.copies`, reset when the box is cleared; the topics
  browser walk searches a word of an item, clears, reopens it and finds no marks (it fails on
  0.28.0).

#### CQ-003: `quality` still honours the retired `cache_dir` setting

- **Where:** `cli.py:981` builds settings by `TreeSettings.from_stored`, which keeps retired keys;
  `cli.tree_settings` drops them (`cli.py:451-460`). `exports.py:104` does the same.
- **What:** on a tree from before 0.21.0 that stored `cache_dir`, `quality` reads that store while
  `run` ignores it (ADR-0030).
- **CQ-003R1:** retire keys inside `from_stored`, and delete the fields no setting can set any
  more (`env`, `llm_timeout`, `llm_retries`, `cache_dir`, `calibrate`; see CQ-009).
- **Done (0.28.1):** `config.RETIRED` and `config.retired`; `from_stored` drops them; the five
  fields deleted; `store_dir` and `shared_store` lost their `cache_dir`. The calibrated fields
  stay as the carriers of calibration: whether they deserve a type of their own is CQ-009's.

#### CQ-004: two defects in `diagram_graph.build`

- **A label replaced too widely** (`diagram_graph.py:224`): `label.replace(name, drawn)` replaces
  every occurrence, so a stereotype spelled like the element's name is rewritten too
  (`«flow» flow` → `«flow(x)» flow(x)`). Rare, but wrong.
- **A wasted quadratic loop** (`:242`): each view's tree members are gathered by scanning every
  link before the view is checked to be a tree at all.
- **CQ-004R1:** replace only the name part; group links by tree once.
- **Done (0.28.1):** `diagram_graph.link_label`, a pure function with its own test; trees' links
  gathered once.

#### CQ-005: "the family" names a different model in lineage than in subjects

- **Where:** `lineage.facts` (`lineage.py:239-248`) keys a family by its newest member, whatever
  its status (failed and pending included); `subjects.families` (`subjects.py:122-135`) by its
  newest *written* member.
- **What:** when a family's newest version failed or waits, the facts' family token names no
  exported project: `workbook._lineage` prints a hex prefix for it, and the workbook's "only this
  family" test at `workbook.py:271` compares against it.
- **CQ-005R1:** with CQ-008: one lineage result per state, computed once, giving both the family
  and its newest written member.

### Architecture and separation of concerns

#### CQ-006: the `export` command assembles the export's inputs itself, and labels are made four ways

- **Where:** `cli.export_catalog` (`cli.py:290-330`) reads `subjects.json` raw, computes
  `lineage.facts` and `shared.find`, and patches labels into the facts. Then labels are built
  again: `workbook.py:150` (from `p.label`), `workbook.py:246` (fallback `t[7:15]`),
  `workbook.py:319` (fallback `t`, in the same function), `searchpage.py:208-213`;
  `_project_rows` rebuilds its label map for every project.
- **Cost:** each output re-derives the same inputs, and they have drifted already.
- **CQ-006R1:** one `ExportContext` (families, topics, facts, links, labels), built in a library
  module and passed to both writers; `cli` only calls it.
- **Also:** `exports.py` writes the root's files and has nothing to do with the `export` command;
  a name like `rootfiles.py` would end the confusion.

#### CQ-007: subjects and topics copy one algorithm, joined by private imports and a cycle

- **Copied, and drifting:** the asker that tolerates replay misses (`subjects.py:384-391`,
  `topics.py:255-260`); reading numbered replies into groups or "not sorted" (`:439-447`,
  `:283-291`); merging down to k (`:253-268`, `:173-183`); distinctive-word labels (`:290-304`,
  `:188-199`; only the subjects' leaves out the about texts' idiom); batching; the
  found/incomplete/failed status (`:484`, `:315`).
- **Coupled:** `topics` imports `subjects`' private `_json` and `_tokens` (`topics.py:30`), and
  `subjects.update` imports `topics` inside the function to write both into one file.
- **CQ-007R1:** a small shared module (asking for JSON, placing replies, merging down,
  distinctive words, Louvain, status); the runner calls subjects, then topics, and one function
  writes the file.

#### CQ-008: `subjects.json` travels as untyped nested dicts, with a reference encoded in a string

- **Where:** the `"token/n"` subject reference is built at `topics.py:76`, `workbook.py:130` and
  `:190`, and parsed at `topics.py:91` and `searchpage.py:177`; "the default view" is looked up at
  `topics.py:61`, `workbook.py:126` and `:171`; the file is read three ways (`subjects.load`,
  `subjects.load_topics`, raw at `cli.py:305`), twice by `subjects.summary`.
- **CQ-008R1:** with CQ-007: typed records (the file, a family, a view, a subject reference) with
  `default_view()`, and one loader.

#### CQ-009: `cli.py` holds library logic

- **SQL:** `shared_store` (`cli.py:892-924`) attaches and copies tables of the LLM store; it
  belongs to the store (`llm`).
- **Settings:** `RETIRED`, `tree_settings`, `stored_settings` and `llm_config` (`:52-56`,
  `:451-476`) belong to `config` (and fix CQ-003 there).
- **Calibration:** the orchestration (`:544-626`) and the two calibrate commands (`:632-732`,
  about 30 lines of setup in common) belong to a calibration module. Moving these, with the
  settings, ends the `interactive` ↔ `cli` cycle.
- **`remove` repeats `prune`'s deletion** (`:418-422` and `runner.py:333-337`).
- **`versions_command`** (E 36) is five commands in one chain of `if`s; one function a command,
  dispatched by `set_defaults(func=...)`, would do. `main` keeps its own list of the commands
  that need a tree (`:952`) beside `COMMANDS` (`:43`).
- **Opening a tree** (open, lock, `except StateError`, close) is written out 17 times; one context
  manager would serve.
- **CQ-009R1 to R5,** one a bullet, each a separate small change.
- **Weighed,** for where the command line's work belongs: (a) all in `cli.py`, as the composition
  root (legitimate, and convenient, but 1,000 lines and the cycle with `interactive`, which calls
  the calibrate commands back); (b) a command layer under a thin parser (most commands already are
  such a function); (c) library pieces to their domains, and the commands in a package by group;
  (d) a CLI framework (click, typer: a dependency and a rewrite, for nothing a user sees). (c).
- **Done:** settings to `config` (`stored_settings`, `tree_settings`); the tree's LLM to a new
  `session.py` (`llm_config`, `shared_store`, `make_client`, `note_models`), its SQL to
  `llm.ResponseStore.adopt`; `runner.remove`, sharing `prune`'s deletion; and `cli/` a package:
  `__init__` (the whole parser in one place, each command's function by `set_defaults`, the tree
  commands by `needs_tree`, a `StateError` reported once, in `main`), `common` (`open_tree`,
  `check_endpoint`), `tree`, `versions` (`versions_command` five functions), `calibration`,
  `configure` and `interactive`, which imports `calibration`: no cycle. The largest module is 291
  lines. Left: `interactive.interview` (F 44: a dialogue, read top to bottom) and `export`, which
  CQ-006 rewrites.

#### CQ-010: the tree's layout and its JSON Lines are spelled out in many places

- **Where:** `"by-sha256"` at `subjects.py:115` and `catalog.py:205` beside `exports.PROJECTS`;
  `index/*.jsonl` paths at `exports.py:200,214,225,345`, `catalog.py:206-214`, `subjects.py:115`;
  JSON Lines read four ways, two of them (`exports.py:201,215`) opening files in a comprehension
  without closing them; the `path!chain` reference joined in four places.
- **CQ-010R1:** a `ProjectDir(out, sha)` with `catalog()`, `chunks()`, `threads()`; one
  `read_jsonl`; one helper for a sighting's reference.
- **Weighed:** (a) constants and functions in a new lowest-level module; (b) a `ProjectDir` class,
  a method a file; (c) keep them in `exports`, where `PROJECTS` was (convenient, but `catalog`
  and `subjects` would import a high-level module for a folder's name); (d) fix only the leaked
  handles. (a): callers mostly want a path, and a method a file grows for little.
- **Done (0.28.2):** `treefiles.py` (`PROJECTS`, `project_dir`, `index_file`, `read_jsonl`,
  `write_jsonl`), used by `catalog`, `crossref`, `exports`, `subjects`, `tables`, `runner`, `cli`;
  no file is left open. Left: the `path!chain` joins, over two shapes of sighting (the state's
  rows, whose chain is JSON text, and the exports' decoded ones), where one helper would need
  both.

#### CQ-011: a flow's direction is an arrow at the end of a display string

- **Where:** `Link.items` holds `"Energy →"` (`diagram_graph.py:81`, made at `:227-238`); readers
  take the last character back: `sketch.py:123`, `:224-227`, `sketch_svg.py:147-149`; `build`
  itself rewrites them (`:235-238`).
- **Cost:** this is AR's theme of rendered text used as an interface: a change of the arrow's
  wording silently breaks the sketches' mid-line arrows and the "flows" reading guide.
- **CQ-011R1:** the direction as its own field; the arrow added only when writing text.
- **Weighed:** (a) a `Flow` type, names and way, the arrow added in `text`; (b) a list of
  directions beside the strings (two lists to keep in step); (c) one direction a link (wrong: a
  connector's items can flow both ways). (a).
- **Done:** `diagram_graph.Flow`; `Link.items` are flows; the sketches read `way`, the texts
  `text`. Every sketch of four samples (257 diagrams: PNG, modules, overview, SVG, conventions)
  byte for byte the same.

#### CQ-012: a link's ends are views, converted back to shapes 18 times

- **Where:** `node_of.get(v.view_id or "") if v else None` at `partition.py:51,164,258,292`,
  `sketch.py:94,121,182,247`, `sketch_svg.py:109`, `pages.py:249`, `diagram_text.py:53`,
  `validate.py:93`, `diagram_graph.py:154,206,249`; five local helpers do the same.
- **CQ-012R1:** `source_node` and `target_node` worked out once in `build`, kept on `Link`.
- **Weighed:** (a) one `DiagramGraph.node(view)`, serving the 18 sites, pins' and parents' among
  them; (b) the ends' nodes stored on `Link` (only the link ends, and a link holding its ends
  twice). (a).
- **Done:** `DiagramGraph.node`; the three local helpers gone; the same sketches.

#### CQ-013: the PNG and SVG sketches change together but share almost nothing

- **Evidence:** 3 of the 6 commits to `sketch_svg.py` (plan SK) had to change `sketch.py` the
  same way. Copied: a graph's bounds (`sketch.py:147-160`, `sketch_svg.py:83-97`), the middle of a
  line (`:368-375`, `:66-73`), arrowheads (`:355-357`, `:56-59`). Drifted: dashes 5/5 against
  `"5 4"`; room for a name `4*FONT_PX*0.5` against `3*CHAR`; arrowhead size by style against 9.
- **Coupling:** `sketch_svg` and `prompt_values` import Pillow's renderer for constants and for
  `conventions`, a question about the graph.
- **CQ-013R1:** a small `drawing.py`: the constants, `conventions`, `bounds`, `midpoint`,
  arrowhead points, and one `link_marks(link)` (dashed, hollow, head end, mid-arrow). Keep two
  emitters: the PNG's regions, fading and edge tags have no SVG counterpart.
- **CQ-013R2:** split `render_png` (F 80) at its seams: canvas, shapes, trees, links and tags,
  connectors and pins, numbers and names, module outlines, region finish. It shadows the module's
  `FONT_PX` and `TITLE_PX` (`:140`).
- **Weighed:** (a) a shared `drawing.py` for what is geometry and convention, each renderer
  emitting its own primitives; (b) one scene builder with two backends (one source of every
  decision, but the PNG's regions, fading, edge tags and measured text have no SVG counterpart,
  on code the vision calibration was measured against); (c) only the constants moved, so that
  `sketch_svg` and `prompt_values` stop importing Pillow (the copied geometry stays). (a), each
  renderer keeping its own sizes (the "drift" is two media's choices, not a fault).
- **Done:** `drawing.py` (`DASHED`, `HOLLOW`, `ROUND`, `SEQUENCE`, `conventions`, `extent`,
  `head_end`, `head_legs`, `flow_along`, `mid_arrow`); `render_png` in phases sharing a `_Pen`
  (radon 80 to under 10; its parts 21 at most), `render_svg` likewise (35 to under 10); neither
  `sketch_svg` nor `prompt_values` imports Pillow; the renderers' unused `ix` gone from them and
  their 20 callers (CQ-021's leftover). Every sketch of 257 sample diagrams byte for byte the
  same, after each step.

#### CQ-014: `diagram_graph.build` (radon 120) has clear seams

- **Churn:** 6 commits, 5 of them one day of plan SK; every new Cameo notation lands here.
- **Seams:** nodes and pins (`:129-146`), label boxes (`:160-164`), flows split at connector
  circles (`:172-180`), which end is which (`:189-215`), the link's label (`:216-224`), flow items
  (`:227-238`), trees (`:240-250`).
- **CQ-014R1:** one function a seam, after CQ-011 and CQ-012 (which remove much of the code).
- **Weighed:** (a) a `_Builder` whose fields are the shared state (views by id, the graph, label
  boxes, split flows) and whose methods are the seams; (b) free functions passing those along
  each call; (c) leave it (every new notation lands here, so the cost recurs). (a).
- **Done:** `diagram_graph._Builder`: `nodes`, `label_boxes`, `split_flows`, `ends`,
  `split_ends`, `path_ends`, `link`, `items`, `trees` (radon 120 to 24 at most); its `noqa` gone.
  The same 257 sketches, whose SVG tooltips carry each connection's label, verb and flows.

#### CQ-015: threads and type hierarchies are one feature written twice, as loose dicts

- **Where:** `hierarchies.hierarchy_chunks` (`:136-160`) and `crossref.thread_chunks`
  (`:288-313`) match nearly line for line, as do `hierarchies_page` and `threads_page`; `_anchor`
  exists twice. The records are dicts (`root`, `title`, `element_ids`, `locator`, `lines`)
  through pages, tables and JSON Lines with no declared shape. `crossref` also mixes the index
  across models with per-project threads.
- **CQ-015R1:** one record type, one chunker, one page writer; threads in their own module.
- **Weighed:** (a) one module for outlines (trees of lines), chunking and paging from a small
  description of each sort, the records still built by each, declared by a `TypedDict`; (b)
  dataclasses for the records, converted at every JSON Lines boundary; (c) the two merged into one
  module (their records' building has nothing in common). (a).
- **Done:** `outlines.py` (`Line`, `Outline`, `Sort`, `outline_chunks`, `outline_page`,
  `anchor`); `threads.py`, out of `crossref`; `hierarchies` on the same. A tree of the fiction and
  the lineage cases (17 projects, 61 thread and 6 hierarchy chunks) built before and after:
  `treediff` finds them the same.

#### CQ-016: an element's section is built in the view, a diagram's in the page writer

- **Where:** `ProjectView.section_view` (`view.py:182-246`, F 46) builds format-neutral data;
  a diagram's section is built inside `PageWriter.write_diagram` (`pages.py:151-206`, E 33) and
  handed to the chunk sink from there. An annotation is rendered twice, by slightly different
  rules (`view.py:258-261`, `pages.py:48-54`); that copy is why `view` imports `files`, and so
  the `files` ↔ `view` cycle.
- **`ProjectView` is not a god object:** it writes nothing; it is indexes and caches, with 160
  lines of section building attached.
- **CQ-016R1:** a sections module building both kinds (and members, tagged values, table
  configuration, annotations); the view keeps its indexes.

#### CQ-017: `pipeline.ingest_project` mixes jobs, and works by an aliasing accident

- **Churn:** 35 commits, 12 since 2026-10-01: the most changed file in its area.
- **Mixed jobs:** the sketch loop (`:132-165`) draws, annotates and queues LLM requests; image
  extraction (`:172-185`) is another job in the same function.
- **The trap:** the pipeline writes sketch annotations to its local `annotations` (`:154`,
  `:162`), the enricher to `view.ann`; both land only because `view.py:40` keeps the very dict it
  was given. Writing that line as `annotations or {}` would drop every sketch annotation, with no
  test failing loudly. `view.package_parts` is likewise changed by enrichment and read later by
  the pages, an order nothing states.
- **CQ-017R1:** write through `view.ann`; extract `render_sketches` and `extract_images`.
- **Weighed:** (a) the view the one owner of annotations, the pipeline writing through it; (b) an
  `Annotations` collector passed to both (a type for a dict of lists); (c) the shared dict, with a
  comment (the trap stays). (a). For `package_parts`: the view as the project's store of what is
  found before writing, the order stated (pages, ledger and sink all read the view), or
  enrichment's results passed to the writers (no behavior gained for the churn); the first.
- **Done:** `ProjectView.ann` made by the view alone (no parameter); `pipeline.draw_sketches` and
  `extract_images`; `ProjectView`'s docstring states the fill-then-write order.

#### CQ-018: small text helpers written several times, with different rules

- **First sentence:** `ledger.py:47`, `hierarchies.py:40`, `prompt_values.py:175`.
- **Clipping:** `ledger._clip`, `prompt_values._cut`, `semantics.described.short`, `crossref.py:255`.
- **Natural sort:** `cameo_tables.py:276`, `ledger.py:42`.
- **CQ-018R1:** one of each in `text.py`.
- **Done (0.28.2):** `text.clip`, `text.first_sentence`, `text.natural_key`, by the most careful
  rules: a cut after a whole word, a sentence ending at `.`, `!` or `?`. Outputs change a little:
  the ledger's first sentences no longer end at a semicolon, and its clips and the unnamed
  elements' descriptions end at a word.

#### CQ-019: `xmi._Parser.start` (radon 58) is a state machine with untyped frames

- **Churn:** 8 commits, 6 since 2026-10-01 (TR-001 among them): it changes as Cameo's quirks
  turn up. Frame kinds are bare strings with an `object` payload (five `type: ignore`s); the
  comment at `:82-83` lists 8 of the 11 kinds.
- **CQ-019R1:** a handler a parent kind, a dispatch table, named kinds.

#### CQ-020: the page script keeps logic in its interface, out of the tested engine

- **Untested logic in the interface:** how two models relate (`alsoIn`'s table, `:1104-1107`;
  `compare`'s, `:815-816`), the short token (`slice(7, 23)` at `:809` and `:1093`, mirroring
  Python's `[:16]` silently), choosing the browse mode (the same condition three times,
  `:905-932`), a model's facts line (twice, `:767-781`, `:1162`), building the catalog's lookups
  (`load`, `:598-607`, re-written in `tests/js/page.js` and `subjects.js`), `detail`'s rows.
- **Repeated DOM patterns:** expand and collapse three times (`:855`, `:965`, `:1018`);
  `pid + "\u0000" + key` 12 times; `href="#"` with `preventDefault` 7 times; "Not sorted yet"
  with its note four times.
- **Too much in one function:** `detail` (35); `Subjects.group` returns three shapes of group
  with no field saying which, and calls `place` twice a topic hit; the chooser's "newest of each"
  runs the search twice.
- **Mixed sources of truth:** the type filter and grouping are read from the DOM, the mode and
  views from `state`, which will matter when a view is shared by URL.
- **CQ-020R1:** engine functions with node tests for the relations, the short token (or emitted by
  Python), the browse mode and the catalog's lookups; **R2:** DOM helpers (`collapsible`, `keyOf`,
  `hashLink`); **R3:** `detail` split by section, groups with a `kind`; **R4:** the script in two
  assets, engine and interface, joined by `searchpage._asset`, the tests requiring the engine
  alone. Not further: the interface shares `state` and its helpers.

### Dead code and loose constants

#### CQ-021: dead code, and constants defined but not used

- **Dead** (no use in the package, scripts or tests): `cli.flag_pair`, `subjects.llm_ways`,
  `lineage.Model.saved_day`, `LLMConfig.public` (`llm.py:70`), `ledger.MAX_CHARS`,
  `config` `llm_timeout` and `llm_retries`; `ix` passed to `render_png` and `render_svg` and
  never used.
- **Defined, then repeated as literals:** `subjects.UNSORTED` (`workbook.py:174,193`);
  `shared.BASES`, re-keyed in `searchpage.BASIS` and `workbook.MATCH`; `searchpage.SKETCHES`
  (`cli.py:181`).
- **Smaller:** `sink.section_chunks` pops `title` out of its caller's dict (`sink.py:67`); the
  lazy imports in `lineage.facts`, `subjects.families` and `exports.rebuild` guard no cycle;
  `searchpage.write_search_page` gzips and base64-encodes four times by hand; `tables.py` (CSV),
  `cameo_tables.py` (Cameo's table diagrams) and `TableWriter.write_tables` (both) are easily
  confused; `tables.write_indices` writes five JSON Lines files by hand.
- **CQ-021R1:** delete the dead; use the constants (an enum for match bases).
- **Done (0.28.1):** the dead deleted; `subjects.UNSORTED` and a new `UNSORTED_NOTE` used by the
  workbook; `shared.BASES` drives `find`, `searchpage.BASIS` and `workbook.MATCH` (a tuple did as
  well as an enum); `searchpage.SKETCHES` gives the CLI its choices; `lineage.facts`' needless
  inner import gone. Left for CQ-013: the renderers' unused `ix`, whose 20 callers that stage
  rewrites anyway.

#### CQ-025: a list of what is never a model, where a list of what can be one serves (the maintainer)

- **Raised by the maintainer** during the remediation (2026-10-07): "I don't believe we need a
  `NOT_MODELS`. We don't need to check every zip file, perhaps just '.zip' as a directory
  surrogate, and the known extensions for Cameo."
- **What was:** a folder's files were opened unless their extension was among 62 known
  non-models (`cli.NOT_MODELS`); inside an archive, any member that began as a ZIP was searched
  (a `.jar` in a plugin bundle too).
- **Done (0.29.0):** `archive.CANDIDATE_EXTS`: Cameo's names (`PROJECT_EXTS`) and bundles
  (`.zip`, `.rdzip`), for a folder's files and an archive's members alike, each still taken by
  its content; a file named on the command line is taken whatever its name. No sample, fiction or
  bundle holds a project under another name (every nested ZIP checked).

### Tests and scripts

#### CQ-022: 85 of the suite's 289 seconds can go

- `test_fiction.py:74-105` takes 50 s: `grading.holds` flattens a chunk's text again for every
  evidence group and question (4.9 million calls to `text.flat`). Flatten each chunk once
  (`grading.Corpus` exists for it).
- `test_cli.py:178` (15 s) and `test_llm.py:449` (24 s) run a full calibration through the fake
  endpoint (92 eye-chart cards at 0.1 s) to check 3 requests; with `--no-calibrate
  --no-preflight` the command takes 0.5 s, not 12.
- The lineage corpus is ingested twice alike (`test_shared.py:12`, `test_lineage.py:38`, 10 s
  each): one session fixture.
- **CQ-022R1** to **R3,** one a bullet.
- **Done (0.28.2):** `grading.Corpus.holds` (the test: 50 s to 7 s); the two runs without
  calibration (39 s to 2 s), still checking overlap and heartbeats; one session `lineage_tree`.
  The suite: 230 s to 139 s.

#### CQ-023: test and script structure

- `test_topics_in_a_browser` lacks `@needs_node`. `tests/js/chooser.js` also tests `tagPieces`,
  `collapseShared` and `compareModels`. The data-block regex is written three times. No browser
  test covers Compare or "Also in". The two browser walks repeat their timeout and close code.
- "Write projects, then ingest" is hand-written in six places (`conftest.py:39`,
  `test_shared.py:14`, `test_subjects.py:20,79`, `test_lineage.py:12,45`,
  `test_calibrate.py:297`), though `helpers.ingest` takes `(path, bytes)` sources;
  `conftest.py:32` says six projects where there are seven.
- Private names: `test_subjects.py:137` computes its expected request count with
  `subjects._family` and `batches`, re-deriving the answer from the code under test;
  `evaluation/topic_judges.py` imports `topics._family` and `subject_judges._number`.
- Study scripts: `judge_subjects.summarize` and `topic_splits.summarize` share the kappa block
  word for word and the E1 table; `topic_splits` imports `JUDGES` from another script.
- `test_diagrams.py:326` patches by hand with `try`/`finally` where `monkeypatch` serves.
- **CQ-023R1:** these, as one cleanup.
- **Done (0.28.2):** `@needs_node`; the engine's tests moved to `engine.js`; `tests/js/pagedata.js`
  reads a page's blocks for `page.js` and `subjects.js`; `chrome.walk` holds the walks' framing;
  `helpers.write_inputs` for the four setups (keeping the input folder, which outputs depend on);
  `Subject.family` and `subject_judges.reply_field`, public; the request count written as a
  number; `judge.PANEL`, `kappa_lines` and `both_orders`, and `subject_judges.pick`, so no script
  imports another (both study reports regenerate byte for byte); `monkeypatch`. Left to CQ-020: a
  browser test of Compare and "Also in".

### Tooling and docs

#### CQ-024: nothing guards complexity, and the architecture doc has fallen behind

- **No guard:** ruff runs without `C901`. By ruff's count only 4 functions exceed 25 (above), so a
  limit would cost little now and stop new F-grade functions.
- **The doc:** `docs/design/architecture.md`'s module table omits `subjects`, `topics`,
  `lineage`, `shared` and `xlsx_parts`, and says the state's schema is version 3 (it is 5).
- **CQ-024R1:** `C901` with `max-complexity = 25`, the four named in `noqa` comments until they are
  split; **R2:** the architecture doc brought up to date as the refactors land; **R3:**
  `catalog.project_catalog` (39), the one of the four no other finding splits.
- **R1 done (0.28.2):** in `pyproject.toml`; the fictional projects' builders exempt (test data).
  `render_png`'s exception went with CQ-013.

## Leave alone

High scores, little reason to change: `partition.partition` (F 49: deterministic, well
commented, 7 commits even counting a rename), `tables.TableWriter.write_tables` (F 42: six
independent CSV files; the score is conditionals in comprehensions), `cameo_tables.build`,
`xmi.finalize` (a clean sequence of passes), the fiction builders (test data, written once).

## Worth keeping

- **Ingest:** one numbered `DiagramGraph` feeding text, both sketches, the partition and prompts;
  `cameo_tables`' value and column model; `partition`'s one algorithm with two adapters; `xmi`'s
  streaming parser; the small `ProjectWriter` parts and the shared `Section` form; atomic writes.
- **The tree:** `runner.build_project` (build aside, publish with a rename and a transaction);
  all SQL in `state.py`; `exports.rebuild` a function a root file; `catalog.jsonl` as the one
  interface of the exports; `shared.find`'s two passes; determinism throughout (seeded Louvain,
  reproducible bytes); `config.Setting`'s one table for `show`, `set` and `-i`; `checks`,
  `xlsx_parts`, `fingerprint`, small and documented; `lineage.classify`'s rules, each with its
  reason.
- **The page:** model text only through `textContent`; ranking checked against the evaluation's
  BM25; byte-identical pages; Chrome driven with no library; a documented data contract.
- **Docstrings that cite plan and finding IDs.**

## Remediation order

| Stage | Steps | Why first | Effort |
|---|---|---|---|
| 1. Bugs and dead code | CQ-001, CQ-002, CQ-003, CQ-004, CQ-021 | Wrong output now; each small | Small |
| 2. Cheap wins | CQ-022 (85 s off every run), CQ-024R1, CQ-018, CQ-010 | Faster tests and a guard before the larger changes | Small |
| 3. The diagram model | CQ-011, CQ-012, then CQ-013, CQ-014 | The most churned complex code; each step shrinks the next | Medium |
| 4. The tree's outputs | CQ-007 with CQ-008, then CQ-006 with CQ-005; CQ-009 step by step | Shared types first, then one export context | Medium |
| 5. Ingest structure | CQ-017, CQ-016, CQ-015, CQ-019 | Ends the aliasing trap and the last cycle | Medium |
| 6. The page script | CQ-020R1 to R4, CQ-023 | Engine first, tested; then split | Medium |

Each stage is a release of its own with the suite passing; none changes an output on purpose,
except CQ-001 and CQ-002 (bugs) and CQ-004's label.
