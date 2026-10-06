# ADR-0004: Tree settings, project options, and versions

- **Status:** Accepted, 2026-09-29 to 2026-10-02; updated on 2026-10-05 (Changes, below).
- **Sources:**
  - plan RI (flags become settings);
  - AR-013R1 and R2;
  - FU-014R1 and R2;
  - plan RA's CP6.

## Context

A forgotten flag must not quietly rewrite every project without its LLM text. Some choices apply
to the whole tree (whether to write `rag/`, the index across models). Others change what a
project's own files contain, and must make the project again when they change.

## Decision

- **`config.TreeSettings`:** the tree's remembered settings.
  - Stored in `state.sqlite`, and only where they differ from the defaults, so that a tree follows
    a default that changes with the tool.
  - Set only with `cameo-ingest config` (ADR-0030). The rule of BASE-020 (name a model or turn
    the LLM off) applies to every run.
  - Switches (`rag-files`, `rag-source`) apply to the whole tree when the root files are rebuilt.
- **`config.ProjectOptions`:** what changes a project's output, hashed into its identity:
  - rendering, models, call budget, and the calibrated pixel budget, modules, sketch sizes and
    image order;
  - the versions of the prompt templates in use.

  A change makes the project again; stored LLM answers make that cheap.
- **The tool version is part of each project's stamp.** It goes up whenever per-project output
  changes, which rebuilds every project.

## Consequences

- **Effective sizes:** the vision model's calibration (ADR-0015), then the defaults.
- **Settings are never secrets:** the endpoint's key is the environment's, never stored.

## Changes

- 2026-10-05: the switches `cross-index`, `threads` and `line-refs` (and `hierarchies`, added by
  ADR-0026) retired for fixed defaults (ADR-0027), and left out of the list of switches. Before:
  `f2b13e2`.

- 2026-10-05: settings are set only with `config`, not by a run's flags; sizes are no longer settings, and `--env` is gone (ADR-0030). Before: `9bf1c07`.
