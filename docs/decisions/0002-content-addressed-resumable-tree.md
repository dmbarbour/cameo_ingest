# ADR-0002: Content-addressed projects in a resumable output tree

- **Status:** Accepted, 2026-09-29 (the maintainer's decisions 1 to 5).
- **Sources:**
  - plan RI (`docs/archive/plans/resumable-ingest-2026-09-29.md`);
  - review BASE: BASE-008, BASE-016 and BASE-017.

## Context

The same project turns up under many names: 3 of the SAF bundle's 9 `.mdzip` files were
byte-identical to standalone samples, and were processed twice. Runs over hundreds of files take
hours, and must survive being stopped. `--force` left stale files that a `**/*.md` loader still
read.

## Decision

- **Identity:** a project is the sha256 of its own bytes (for a nested member, the member's, not
  the bundle's). Output goes to `OUT/by-sha256/<sha256>/`. Every path and archive chain where it
  was seen is a sighting, kept apart.
- **State:** a SQLite database (`state.sqlite`) is the authority: the task list of inputs, the
  contents, their sightings and each project's state. `run.json` records the latest run.
- **The output directory is a workspace:** a missing or empty directory starts a tree, one with
  `state.sqlite` continues, and any other non-empty directory is refused. `--force` is gone.
- **Building:** in `by-sha256/.work/<sha>/`, then published by rename and one transaction, so a
  project directory is always complete.
- **One run per tree,** by `flock` on `state.lock`. Ctrl-C or SIGTERM stops new work and exits 130.
- **Removed inputs** keep their projects until `prune`.
- **Breaking changes to ids are acceptable,** with no compatibility layer.

## Consequences

- **Each project once,** however many files or bundles hold it.
- **Runs resume:** a work directory with the same tool and options is reused.
- **`status`** works during a run (WAL mode).
- **Schema changes** migrate in place; a newer schema is refused.
