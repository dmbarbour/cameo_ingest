# Design: architecture

How cameo-ingest is put together, and the rules that keep it so. The decisions behind it are in
`docs/decisions/`; this describes what holds now (0.15.2).

## The pipeline

```
cli ─► runner: check inputs ─► scan (archive.discover; state: contents, sightings; fingerprints)
           ─► prepare: calibrate the vision model if it has no record, validate (calibrate, validate)
           ─► per stale project, in by-sha256/.work/<sha>/ (pipeline.ingest_project):
                parse (xmi ─► model.ModelIndex) ─► layouts (layout) ─► writer (emit: view, files, sink)
                ─► per diagram: graph (diagram_graph), PNG and SVG sketches (sketch, sketch_svg),
                   its requests queued (enrich, prompt_values, prompts)
                ─► embedded images ─► packages ─► enricher.run (rounds) ─► pages, tables, indices
           ─► publish (rename + one transaction) ─► exports.rebuild (root files, rag/)
export ─► catalog ─► workbook / searchpage
```

- **Project order:** a project's build runs in this order:
  1. parse, then the layouts, then the writer (`ProjectView`, `FilePlan`, `ChunkSink`) and the
     `Enricher`;
  2. each diagram's sketches, with its requests queued; then the embedded images; then the
     packages;
  3. `Enricher.run`: a first round, then large diagrams from their modules and large packages from
     their parts;
  4. the images page, and every page and table.
- **The contract** between a project's build and the tree's rebuild is three files per project:
  `index/chunks.jsonl`, `index/ids.jsonl` and `index/threads.jsonl` (with `index/catalog.jsonl`
  for the exports). Tree switches apply at rebuild (ADR-0004).

## Modules

| Layer | Modules | Holds |
|---|---|---|
| Inputs | `archive`, `xmi`, `layout`, `richtext`, `fingerprint` | Finding projects in files and bundles; reading XMI by its conventions (ADR-0001); layout streams; HTML text; what a project says about itself |
| Model | `model`, `semantics`, `external` | The element index; UML/SysML meaning, the one vocabulary (labels, kind words, `RELATIONS` with their verbs); names for references outside a project |
| Views | `view`, `sections`, `files`, `diagram_graph`, `diagram_text`, `partition` | A project as pages and chunks see it; sections built once as data; where pages are; diagrams as graphs and text; modules and parts |
| Writers | `emit`, `pages`, `tables`, `sink`, `chunks`, `plain`, `ledger`, `catalog`, `provenance`, `annotations` | Pages, tables, chunk records and their checks, the plain packer, ledgers, catalog records, provenance and the generated-by sentence |
| Images | `sketch`, `sketch_svg`, `vision`, `eyechart` | Sketches for the vision model and for people; the pixel budget; eye charts |
| LLM | `llm`, `sqlite_cache`, `prompts`, `prompt_values`, `enrich`, `calibrate`, `validate`, `quality` | Client, store and session; versioned templates and their values; enrichment in rounds; calibration and validation; spot-check sets |
| Tree | `state`, `runner`, `exports`, `config`, `progress`, `cli`, `treediff`, `crossref`, `groups` | The state database (all SQL); runs; root files and `rag/`; settings and options; progress; commands; tree comparison; the identifier index; version groups |
| Exports | `workbook`, `searchpage` | The workbook and the search page (ADR-0021) |
| Evaluation | `evaluation/*` | Retrieval evaluation, fictional projects, judges (ADR-0023); never imported by the ingest |

**Layering rules:**
- **The lowest layers import nothing from the package:** `archive`, `layout`, `progress` and
  `text`.
- **The ingest never imports `evaluation`.**
- **All SQL against `state.sqlite` is in `state.py`.**
- **One vocabulary:** labels, kind words and relationship wording come from `semantics`, never
  rebuilt elsewhere (AR-010, AR-011).
- **One way to make and check a chunk:** `chunks.make` and `chunks.problems` (ADR-0008).
- **Stages pass structure, not rendered text** (ADR-0008).
- **Pillow:** `sketch` loads it, and is imported by `pipeline`, `runner`, `calibrate`, `validate`,
  `eyechart`, `prompt_values` and `sketch_svg`. The rule of plan RA, that only the pipeline
  imports it, no longer holds.

## State and publishing

`state.sqlite` is the authority (ADR-0002). Its tables are below, with two views: `current_sightings`
and `project_status`. Schema version 3 is migrated in place, and a newer schema is refused.

| Table | Holds |
|---|---|
| `meta` | The schema version |
| `inputs` | The task list: path, size, mtime, sha256, status, `--meta` values |
| `contents` | One row per project content: sha256, the name it was first seen under, kind, size |
| `sightings` | Where each content was found: input version and archive chain |
| `projects` | Each project's state: status, tool, options hash, summary |
| `files` | Each written project's files, with their sha256 (the manifest's source) |
| `runs` | Each run's command, times, outcome and LLM report |
| `settings` | The tree's remembered settings (only those that differ from the defaults) |
| `fingerprints` | Save time, project id, exporter, and element ids as sorted 64-bit hashes (ADR-0020) |
| `removed` | Projects removed from the tree, kept apart from `contents` |
| `calibrations` | Each vision model's calibration and validation (ADR-0015, ADR-0016) |

- **Locking:** one run per tree, by a non-blocking `flock` on `state.lock`; a non-POSIX system runs
  without a lock. The database runs in WAL mode, so `status` works during a run. Writes go
  through `tx()` with `BEGIN IMMEDIATE`.
- **Change detection:** an input's size and `mtime_ns` decide whether it is scanned again. An input
  whose sha256 changed by build time is queued for the next run.
- **Resuming:** a work directory is kept only when its project is `working` with the same tool and
  options hash.
- **Publishing:**
  1. the final directory is renamed to `<sha>.old`;
  2. the work directory becomes the final one;
  3. the database records it;
  4. `.old` is removed.
- **A directory holding only `.cache`** counts as empty.

## Identifiers

| What | Form |
|---|---|
| A project | `sha256:<hex>` of its own bytes |
| A chunk | The first 24 hex digits of the sha256 of its identifying parts, joined by `\|` (content, kind, element or file, salt) |
| A locator | Its trace, starting from the project's content (the first 16 hex digits) |
| A short id | The first 8 hex digits |
| Options | The first 16 hex digits of the sha256 of `ProjectOptions.as_dict()` |
| The tool | `cameo-ingest/<version>`, part of each project's stamp |
| An anchor | `slug(name, 80)-slug(id, 200)`, before each heading as `<a id>`; ids keep their case (BASE-009, BASE-003) |

## Robustness and security

- **Isolated failures:** one bad project doesn't stop the run. Failures are recorded, and the run
  exits 4. Damaged nested members are skipped.
- **Archives:**
  - nothing is extracted to disk;
  - a zip-bomb budget applies: 10 GB decompressed per input, and a 1000:1 ratio for members over
    64 MiB (BASE-011);
  - the samples' maxima are a 54:1 ratio, a 38 MB member and 138 MB per input;
  - encrypted ZIPs are rejected.
- **XML** is parsed with entity resolution and network access disabled.
- **Exit codes:**
  - 0, success;
  - 2, a usage or configuration error;
  - 3, an input had no readable model;
  - 4, some projects failed;
  - 5, the LLM endpoint check failed;
  - 130, interrupted.

## How a change is shown to change only what it should

Used for every refactoring and plan since plan RA:
- **`treediff`:** `python -m cameo_ingest.treediff BEFORE AFTER` compares two `--no-llm` trees of
  the samples and the fiction. It ignores run records, work directories and `rag/` stamps, and
  masks the tool version. Every difference must be expected and explained.
- **Replay:** a replay from a copied answer store fails on any prompt that changed.
- **Retrieval:** checked on the fictional questions, paired against the previous tree
  (`docs/design/evaluation.md`).
- **Versions:** the tool version goes up whenever per-project output changes.
- **Heavy jobs** run one at a time, under `systemd-run --user --scope -p MemoryMax=3G -p
  MemorySwapMax=0`: the development machine has 15 GB and has crashed under heavy local work.
