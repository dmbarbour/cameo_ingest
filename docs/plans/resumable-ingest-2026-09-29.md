# Plan: resumable, content-addressed ingest, 2026-09-29

- **Status:** Accepted on 2026-09-29, with the maintainer's answers under Decisions; in progress
- **Step prefix:** `RI`, so steps are `RI-01`, `RI-02` and so on
- **Addresses:** BASE-008R1, BASE-016R2, BASE-017R1 and BASE-021R1 in
  `docs/reviews/baseline-2026-09-29.md`
- **Starting point:** commit `53cebf7`

## Goals

These come from the maintainer's findings in the baseline review.

1. **Process by content.** Each Cameo project is identified by the sha256 of its own bytes.
   It is processed once, however many paths, bundles or names it is found under. Every
   place it was found is recorded as provenance (BASE-017).
2. **Keep inputs apart.** Two different inputs never share or overwrite each other's output,
   whatever their names (BASE-016).
3. **Continue, don't restart.** A run can be stopped at any point, by Ctrl-C, a crash or a
   lost session, and running again continues where it stopped. The output directory is a
   workspace, and `--force` goes away (BASE-008R1, BASE-021).
4. **Queryable state and a task list.** State lives in SQLite, where it can be queried. Inputs
   can be added over time and processed when convenient.

## Decisions

All decisions were made on 2026-09-29.

| # | Question | Decision |
|---|---|---|
| 1 | Directory names | `OUT/by-sha256/<sha256>/`, plus an index file at the root (`INDEX.md`). |
| 2 | Paths in provenance | Per-project output carries a stable token, `sha256:<content hash>`, and nothing about where the content was found. Sightings (input paths, archive chains, `--meta` values) are kept separately and looked up by the token. |
| 3 | Removed inputs | Their projects stay until explicitly pruned (`prune`). |
| 4 | Breaking changes to IDs | Acceptable: locators, chunk IDs and the layout change with no compatibility layer. |
| 5 | Run record | Keep producing `run.json`, but most state goes in SQLite, so it can be queried and inputs can be added to a task list over time. |

## Design

### Output tree

```
OUT/
  state.sqlite           task list and state (see below): the authority for everything else
  INDEX.md               every project: name, token, counts, status, where it was found
  manifest.json          every project: token, directory, summary, files with sha256
  provenance.jsonl       one record per token: sightings with input paths, archive chains, --meta
  chunks.jsonl           all projects' chunks, with --meta values joined in for filtering
  run.json               the latest run, exported from state.sqlite
  .cache/llm.sqlite      LLM answers (unchanged; shareable with --cache-dir; the replay fixture)
  by-sha256/<sha256>/    one project per content hash: README.md, LEDGER.md, packages/,
                         diagrams/, images/, tables/, index/ (as today)
  by-sha256/.work/       unfinished projects (see Stages)
```

Per-project directories depend only on the content, the tool version and the options.
Their text names the project and its token, never a path or an input, so a project
directory is byte-identical whichever file or tree it came from, and it is never rewritten
because the content turned up somewhere else. The root files are derived from
`state.sqlite` at the end of every run. They cover every project in the tree, not just
the latest run's. Only `provenance.jsonl`, `run.json` and `state.sqlite` contain local
paths.

### Identity and provenance

- **Content hash:** the sha256 of the project's own bytes. For a nested `.mdzip`, these are
  the member's bytes, not the bundle's. For a bare XMI document, they are the document's.
- **Token:** `sha256:<64 hex>`. It is the project's directory name, the chunks'
  `metadata.content`, and the front matter's `provenance.content`.
- **Locators** start from the content: `sha256:<16 hex>!<entry>#<xmi:id>@L<line>`.
- **Chunk IDs** hash the content sha256, then kind, element and salt.
- **Project name:** the file name under which the content was first seen, recorded once.
  It does not change when the content is found under other names.
- **Sighting:** a (content, input version, archive chain) triple. The `--meta` values belong
  to the input.

### State database (`OUT/state.sqlite`)

Every change is committed as soon as it happens. Views give the common queries (pending
inputs, failed projects, sightings by token), and the schema is documented in the README
so that `sqlite3` can be used directly.

| Table | Holds |
|---|---|
| `inputs` | The task list: each input path (a file; `add DIR` adds the files under it), with status (`pending`, `done`, `failed`, `missing`), `--meta` values, size, mtime, sha256, the times it was added and processed, and any error. |
| `contents` | Each content: sha256, name (first seen), kind, size, first seen. |
| `sightings` | Content sha256, input id and input sha256, archive chain. |
| `projects` | For each content: status (`pending`, `working`, `written`, `failed`), tool version, options hash, summary, error, and the time it was updated. |
| `files` | Each written project's files, with sha256 (for `manifest.json`). |
| `runs` | Each run: id, start and finish, command line, outcome (`finished`, `interrupted`, `failed`), LLM report. |
| `settings` | The tree's run settings: models, `--no-render`, budget, concurrency, `--env` path. Never secrets. |

A run holds an exclusive lock on the output directory (`flock`), so two runs cannot write
the same tree at once.

### Stages and resuming

- **Work directory.** A project is built in `by-sha256/.work/<sha256>/`, and then published
  by replacing `by-sha256/<sha256>/` in one rename. A project directory is therefore always
  complete, whatever happened, and files a new version no longer produces disappear with
  the old directory.
- **What a resume reuses.** If a run stops, the next run finds the work directory with the
  same tool version and options, and keeps its diagram sketches: rendering is the costliest
  stage without an LLM (48 s for TMT). LLM answers are reused from `llm.sqlite`. Parsing is
  repeated, since it is cheap (3 s for TMT).
- **Failures.** A failed project is recorded with its error, and retried by the next run.
- **Interruption.** On Ctrl-C or SIGTERM, no new work starts, requests in flight are
  cancelled, the run is recorded as `interrupted`, the root files are rebuilt, and the
  command exits with code 130 and says how to continue.

### Invalidation

A written project whose tool version or options hash differs from the current run's is
written again. The options that count are rendering, the text and vision models, and the
call budget. Unchanged LLM prompts are answered from `llm.sqlite`, so this costs parsing,
rendering and writing, not LLM time.

### Command line

| Command | Does |
|---|---|
| `cameo-ingest add -o OUT PATH... [--meta K=V] [--meta-file F]` | Adds inputs to the task list, walking directories for ZIP archives and XMI documents. Nothing is processed. |
| `cameo-ingest run -o OUT [options]` | Checks inputs for changes or disappearance, processes pending inputs and unfinished projects, and rebuilds the root files. |
| `cameo-ingest ingest -o OUT PATH... [options]` | `add` then `run`. It is the default, so `cameo-ingest FILE -o OUT` still works. |
| `cameo-ingest status -o OUT [--json]` | Inputs and projects by status, failures with their errors, and the latest run. |
| `cameo-ingest prune -o OUT [--dry-run]` | Removes missing inputs from the task list, and the projects that no remaining input contains. |

**Output directory rules:** a missing or empty directory is started, a directory with
`state.sqlite` is continued, and any other non-empty directory is refused (BASE-008R1).
`--force` and the BASE-016R1 stopgap are removed.

**Settings:** a run's LLM and rendering flags become the tree's settings. A later `run` with
no flags uses them, so a forgotten flag can't quietly rewrite every project without LLM
text. The rule from BASE-020 (name a model or pass `--no-llm`) applies only while the tree
has no settings.

## Steps

| Step | Work | Status |
|---|---|---|
| RI-01 | `state.py`: schema with a `schema_version`, views, the `flock` lock, and helpers for each table. Unit tests. | Done |
| RI-02 | Content identity: `discover` hashes each project's bytes, and `Project` carries the hash and its archive chain. Per-project outputs use the token: locators, chunk IDs, front matter and page text, with no source path, name or `--meta`. | Done |
| RI-03 | Command line: subcommands, the default `ingest`, output directory rules, settings; remove `--force` and the BASE-016R1 guard. | Done, except `status` and `prune` (RI-08) |
| RI-04 | The run loop: check inputs, discover, record contents and sightings, build projects in the work directory and publish them, handle failures and retries. | Done |
| RI-05 | Root files from `state.sqlite`: `INDEX.md`, `manifest.json`, `provenance.jsonl`, `chunks.jsonl` (with joined `--meta`), `run.json`, and the `ledger:projects` chunk. | Done |
| RI-06 | Invalidation when the tool version or options change. | Done (landed with RI-04: one condition in the work query) |
| RI-07 | Interruption and resume: reuse work-directory sketches, exit 130. | Not started |
| RI-08 | `prune` and `status`. | Not started |
| RI-09 | Progress across inputs ("input N of M") and a resume summary. | Not started |
| RI-10 | Tests. Kill and resume must equal an uninterrupted run. Also: the same content under two paths gives one directory and two sightings; `add` then `run`; a changed tool version rewrites the project; `prune`; a foreign directory is refused; settings are reused. Slow test: the SAF_Plugin bundle plus the standalone SAF samples give one directory per content. | Not started |
| RI-11 | Docs: README (layout, commands, state schema, RAG join), and closing BASE-008, BASE-016, BASE-017 and BASE-021 in the review. | Not started |

The steps land in three commits: RI-01; then RI-02 to RI-05; then RI-06 to RI-09. RI-10 grows
with each, and RI-11 closes the plan. RI-02 was moved in with RI-03 to RI-05 (it was first
paired with RI-01), because content identity and the new layout change the same outputs and
tests; landing them apart would have meant throwaway intermediate code.
