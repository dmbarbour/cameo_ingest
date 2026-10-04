# ADR-0014: Measurements set the defaults; caches are no reason to keep a value

- **Status:** Accepted, 2026-10-03 (the maintainer's policy).
- **Sources:**
  - `docs/archive/plans/vision-calibration-2026-10-03.md`;
  - `docs/research/vision-calibration-gemma4-2026-10-03.md`.

## Context

The first calibration recommended keeping each setting unless it failed, and advised keeping 12 px
text, so that no tree would be redrawn and no description asked again. The maintainer: "I'd rather
not have special exceptions just for maintaining the existing test cache."

## Decision

- **Values come from the measurements alone.** Recommendations, and the tool's defaults, follow
  what was measured, never the value in use.
- **When the data decide nothing,** the tool's reference defaults serve, never the tree's current
  value.
- **The cost of a change** (sketches redrawn, descriptions asked again) is reported as
  information, never as a reason to keep a value.
- **Pressure tests are named:** a test that means to push a model past what it reads comfortably
  says so, and sets its sizes from the calibration.

## Consequences

- **The default text size** went from 12 to 13 px (0.12.0).
- **The sketch sizes are always in the projects' options** (ADR-0004). Leaving them out at their
  defaults spared nothing, since a new version rebuilds every project anyway.
