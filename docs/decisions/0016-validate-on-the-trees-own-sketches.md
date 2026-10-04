# ADR-0016: Validate on the tree's own sketches; warn and carry on

- **Status:** Accepted, 2026-10-03 (plan VA; the maintainer: "warn and carry on").
- **Sources:**
  - `docs/archive/plans/vision-autocalibration-2026-10-03.md`;
  - `docs/design/vision-calibration.md`.

## Context

Eye charts measure what a model reads on cards made for it. The maintainer wanted to "perform some
sketches and validation tests so we know what quality to expect from the real ingestion".

## Decision

- **The sample:** after calibrating, up to 4 each of small diagrams, medium ones and modules of
  large ones, from up to 4 of the tree's projects.
- **The question:** each is drawn at the run's sizes, and the model is asked from the image alone
  for the shapes' numbers and names and every connection.
- **The scores,** against the diagram's own truth (the names as drawn, the connections):
  - names read;
  - connections found;
  - directions right;
  - connections invented.
- **The report:** a line before building. Each score under 90%, and invented connections over 10%,
  get a warning naming what will suffer. The run carries on.

## Consequences

- **Lower bounds:** the scores are lower bounds on what the image contributes, not on the
  descriptions, which also get every name and connection as text.
- **Sketch faults:** validation found faults in the sketches that no model could read past
  (plan SK).
