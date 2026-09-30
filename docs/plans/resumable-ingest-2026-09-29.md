# Plan: resumable, content-addressed ingest, 2026-09-29

- **Status:** Draft, awaiting the maintainer's review of the open questions
- **Step prefix:** `RI`, so steps are `RI-01`, `RI-02` and so on
- **Addresses:** BASE-008R1, BASE-016R2, BASE-017R1 and BASE-021R1 in
  `docs/reviews/baseline-2026-09-29.md`
- **Starting point:** commit `e6adbe1`

## Goals

These come from the maintainer's findings in the baseline review.

1. **Process by content.** Each Cameo project is identified by the sha256 of its own bytes.
   It is processed once, however many paths, bundles or names it is found under. Every
   place it was found is recorded as provenance (BASE-017).
2. **Keep inputs apart.** Two different inputs never share or overwrite each other's output,
   whatever their names (BASE-016).
3. **Continue, don't restart.** A run can be stopped at any point, by Ctrl-C, a crash or a
   lost session, and running the same command again continues where it stopped. The
   output directory is a workspace that runs start or continue. `--force` goes away
   (BASE-008R1, BASE-021).
4. **Share one output tree.** Many inputs, across one run or many, go into one output
   directory, and its root files describe all of them.

## Where things stand

The baseline fixes already provide several pieces:

- **LLM store:** an SQLite store, `llm.sqlite`, that is atomic per answer, keyed by
  endpoint, model and request hash, and replayable.
- **Content-only prompts:** since BASE-022R6, prompts no longer contain locators.
- **Isolation:** a project that fails doesn't stop the others (`manifest["failed"]`).
- **Reproducibility:** outputs are deterministic, and the run record is in `run.json`.
- **Progress:** progress is reported by phase, and LLM requests can run concurrently.
- **Stopgap guard:** a project directory holding other content is refused (BASE-016R1).

**What is still missing:**

- **Identity:** it still comes from the top-level input's hash plus the archive path.
- **Where state lives:** in memory only.
- **Output:** written only at the end of each project and, for the root files, at the end
  of the run.

## Design

### State database

`OUT/state.sqlite` records what the tool knows and has done. Every change is committed as
soon as it happens, so the database always describes finished work.

| Table | Holds |
|---|---|
| `inputs` | Each input path seen, with size, mtime and sha256. An unchanged input (same path, size and mtime) is not hashed again. |
| `contents` | Each project's content sha256, name, kind (`.mdzip` or bare XMI) and size. |
| `sightings` | Where each content was found: the input's sha256 and path, and the archive chain inside the input. |
| `projects` | For each content: the tool version and options hash its output was made with, the output directory, the stage reached, the summary, and any error. |
| `files` | Each output file per project, with its sha256. It says what the tool owns, what to remove when a project is rewritten, and what the root manifest lists. |
| `runs` | Each run's id, times, command line and outcome (replacing `run.json`, or feeding it). |

`llm.sqlite` stays a separate file. It can be shared between output directories through
`--cache-dir`, and it doubles as the test fixture (BASE-022R5). The state database refers
to it but doesn't absorb it.

A run takes an exclusive lock on the output directory, so two runs cannot write the same
tree at once.

### Identity and output layout

- **Project identity:** the sha256 of the project's own bytes. For a nested `.mdzip`,
  these are the member's bytes, not the bundle's.
- **Output directory:** `OUT/<name>--<sha12>/`, readable and unique. The same content
  found under another name reuses the first directory.
- **Locators** start from the project hash:
  `sha256:<project sha16>!<entry>#<xmi:id>@L<line>`. The archive chain that led to the
  project is no longer part of the locator. It is a sighting.
- **Chunk IDs** hash the project's content sha256, then kind, element and salt, so the
  same content always gives the same IDs.
- **Sightings** live in the state database and the root `manifest.json`, not in per-project
  files. A new sighting of known content then changes no project output (BASE-015).

### Stages and resuming

Each project moves through five stages: discovered, parsed, rendered, enriched and
written.

- **Parsing** is not saved. The model index lives in memory, and rebuilding it is cheap
  (3 s for TMT). A resumed project parses again.
- **Rendering** records each PNG in `files` as it is written, and a resume skips diagrams
  already drawn. It is the costliest stage without an LLM: 48 s for TMT.
- **Enrichment** is resumed by `llm.sqlite`, since every answer is already committed.
- **Writing** writes to temporary names and renames them into place. The project is marked
  written, with its file list, in one transaction. Files the tool wrote for an earlier
  version of the project and no longer produces are then removed.
- **The root files** (`manifest.json`, `chunks.jsonl`, `LEDGER.md`) are rebuilt from the
  database at the end of every run. They cover every written project in the tree, not
  just those of the last run.

**Interruption:** on SIGINT or SIGTERM, no new work is scheduled, requests in flight get a
short grace period, state is committed, and the run exits with code 130 and a message to
run the same command again.

### Invalidation

A project whose tool version or options differ from the current run is written again.
Unchanged LLM prompts are answered from `llm.sqlite`, so this costs parsing, rendering and
writing, not LLM time. The options include `--no-render`, the model names and the budget.

### Command line

- **Inputs:** `cameo-ingest SOURCE... -o OUT` accepts several files and directories.
  Directories are walked for files that are ZIP archives or XMI documents; the extension
  doesn't matter.
- **Output directory:** a missing or empty directory is started. A directory with
  `state.sqlite` is continued. Any other non-empty directory is refused (BASE-008R1, as
  agreed).
- **Removed:** `--force`.

## Steps

All steps start as **Not started**.

| Step | Work |
|---|---|
| RI-01 | `state.py`: schema, migrations (a `schema_version` row), the directory lock, and helpers for inputs, contents, sightings, projects, files and runs. Unit tests. |
| RI-02 | Content identity: `discover` hashes each project's bytes, and `Project` carries the hash and its archive chain. Locators, chunk IDs and output directories are derived from the project hash (breaking change, see question 4). |
| RI-03 | Several inputs and directories in one run; skip hashing unchanged inputs; record sightings; process each content once. |
| RI-04 | Staged, resumable projects: render skips recorded PNGs, writing is atomic, a project's files are recorded and stale ones removed. |
| RI-05 | Output directory rules: start, continue or refuse; remove `--force` (BASE-008R1). |
| RI-06 | Root files rebuilt from the state database, covering every written project, with sightings in `manifest.json`. |
| RI-07 | Invalidation when the tool version or options change. |
| RI-08 | Interrupt handling: stop cleanly, commit, exit 130. |
| RI-09 | Progress across inputs (an overall "input N of M" phase) and a resume summary ("12 projects done, 3 to go"). |
| RI-10 | Tests. Kill and resume: a fake LLM client raises `KeyboardInterrupt` after K requests, the run is repeated, and the result must equal an uninterrupted run. Also: the same content under two paths gives one directory and two sightings; a changed tool version rewrites the project; stale files are removed; a foreign directory is refused. Slow test: the SAF_Plugin bundle plus the standalone SAF samples (BASE-017's evidence) give one directory per content. |
| RI-11 | Docs: README (inputs, output layout, resuming), and closing BASE-008, BASE-016, BASE-017 and BASE-021 in the review. |

Steps RI-01 to RI-03 can land together, followed by RI-04 to RI-06, then RI-07 to RI-09.
RI-10 grows alongside each group.

## Open questions for the maintainer

1. **Directory names.** `OUT/<name>--<sha12>/` (proposed), or `OUT/by-sha256/<sha>/` with a
   readable index at the root?
2. **Paths in provenance.** Per-project files would carry the content hash only, with
   sightings (input paths and archive chains) in the state database and the root
   manifest. That keeps project output stable when new sightings appear. Is that enough,
   or should each project's README also list where its content was seen, at the cost of
   rewriting it when a sighting is added?
3. **Removed inputs.** When an input disappears from the command line or from a directory,
   should its projects stay in the tree (proposed: yes, content is kept until a `--prune`),
   or be removed at once?
4. **Breaking changes.** Locators and chunk IDs change (RI-02). Since this is 0.x, the plan
   makes no attempt at compatibility: the first run of the new version rewrites everything.
   Acceptable?
5. **Is `run.json` still needed?** The `runs` table replaces it. Keep `run.json` as a
   readable export of the latest run (proposed), or drop it?
