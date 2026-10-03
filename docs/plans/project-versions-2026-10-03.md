# Plan: finding versions of a model, and removing projects from a tree, 2026-10-03

- **Status:** Proposed on 2026-10-03.
- **Step prefix:** `PV`, so steps are `PV-01`, `PV-02` and so on
- **Addresses:** the maintainer's request of 2026-10-02.
  - The sources are "a complete mess of great volume": 282 Cameo files, 125 or more of them
    unique, many of them versions of the same model.
  - What would help is a way to identify the versions and keep the latest of each.
  - On reflection, the maintainer prefers tools to list projects, find groups by shared element
    ids, and remove projects from the tree. A switch that decided for them on every run is
    riskier: two vendors may have started from the same model (forks).
- **Related:** plan KX's exports, which then hold only what remains in the tree.

## What the samples show (2026-10-02)

| Signal | What it shows |
|---|---|
| **Element ids** | Cameo keeps an element's `xmi:id` across saves, so versions share most of theirs. TMT and TMT-2024x share 69,613, which is 88% of the two together (98% of the smaller). No other pair of samples shares more than one id. Reading a model's ids takes about a second for the largest sample (TMT-2024x, 100,000 ids). |
| **Save time** | Cameo writes it at the head of `Records.properties`, as Java does (`#Thu Nov 02 11:39:23 PDT 2023`). It is present in every real sample, and unlike a file's own date, copying doesn't change it. |
| **Project id** | `id="PROJECT-…"` in `com.nomagic.ci.metamodel.project`. It is no use alone: TMT and TMT-2024x have different ones, and a model made from a template keeps the template's (SAF_Blank and SAF Predefined Structure). |

## Design

Nothing is decided for the maintainer. The tool reports, and the maintainer removes.
- **`cameo-ingest scan -o OUT`:** reads the task list's inputs and records the projects they
  contain, as `run` does first. It builds nothing and needs no LLM settings, so that projects
  can be looked at and removed before the expensive build.
- **`cameo-ingest projects -o OUT [--csv FILE]`:** every project in the tree, one line each:
  - the token (`sha256:…`, shortened) and the file name;
  - its status (pending, written, failed, removed);
  - its save time and Cameo version, its project id and its number of elements;
  - every path where it was found, with its `--meta` values.
- **`cameo-ingest groups -o OUT [--csv FILE]`:** projects joined by shared element ids into
  groups, each group newest first. For each member:
  - the share of its ids it shares with the group's newest;
  - the ids that only it has;
  - its save time and paths.

  Links are of two strengths:
  - **Likely versions:** half or more of the two models' ids shared (their Jaccard index), or
    80% of the smaller one's when that is at least 50 ids. A model growing over many versions
    is chained through them.
  - **Related:** at least 20% of the smaller one's ids, and at least 20 ids, as two models built
    from one template would be. Listed, not grouped.

  **Warnings:**
  - **Possible fork:** a group whose members each have many ids the other lacks (10% or more of
    each), since a later version usually keeps most of an earlier one.
  - **No save time:** the dates inside the zip are shown instead, marked as such.

  The report ends with a `remove` command line for the older members of each group, to copy
  if the maintainer agrees.
- **`cameo-ingest remove -o OUT TOKEN... [--dry-run]`:**
  - **What it removes:** each project's output, its work directory, and its entries in the root
    files. A token's first 8 hex digits suffice when they are unique.
  - **What it records:** in a new table, `removed`. The removal outlives the project's input, so
    that `run` skips the project while its file is still in the task list, and if it turns up
    again in another file.
  - **What it keeps:** its LLM answers stay in the store.
- **`cameo-ingest restore -o OUT TOKEN...`:** undoes `remove`. The next `run` builds the
  project again, reusing its stored answers.
- **`status`** counts removed projects. `prune` leaves the `removed` table alone.

## Steps

| Step | What | Status |
|---|---|---|
| PV-01 | **The facts per project** (`fingerprint.py`):<br>- the save time from `Records.properties`, parsed with its time zone (the common abbreviations; otherwise kept as written, and ordered by date only);<br>- the project id and the Cameo version;<br>- the element ids, read with `iterparse` (about a second for the largest model).<br>They are kept in a new table, `fingerprints`, with the ids as sorted 64-bit hashes, compressed, so that `groups` re-reads nothing. They are filled by `scan` (and by `run`'s scan). | |
| PV-02 | **`scan` and `projects`.** `Runner.scan` as a command of its own, then fingerprints for contents without one. `projects` from the state alone. | |
| PV-03 | **`groups`:** the links, groups (connected by "likely version" links), warnings and the report, in Markdown on screen and in CSV. | |
| PV-04 | **`remove` and `restore`:** the `removed` table (schema version 2, added in place), skipped by `run`'s list of work, by `rebuild` and by `export`; output deleted; root files rebuilt. | |
| PV-05 | **Tests and docs.**<br>- **Tests:** the samples' TMT pair grouped as likely versions, newest first; a template and the model made from it reported as related; a fork warned of, with two fictional projects that each change a shared base; `remove` survives a re-scan and `restore` undoes it; a tree from before this plan opens and works.<br>- **Docs:** the README gets a section, "Versions and removal", with the steps for a messy folder (`add`, `scan`, `groups`, `remove`, `run`). | |

**Checks:**
- **The samples:** `groups` reports the TMT pair as likely versions and nothing else, and its
  timings are recorded.
- **The rest of the tree:** a `--no-llm` tree is otherwise unchanged (`treediff`).

**Version:** 0.10.0 (a new state table).

## When to stop and ask

- **Unreliable signals:** save times are missing or contradictory in many of the maintainer's
  files, or element ids turn out not to be kept across saves for some Cameo versions.
