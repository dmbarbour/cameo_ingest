# ADR-0015: Calibrate sketches to the configured vision model

- **Status:** Accepted, 2026-10-03 (plans VC and VA).
- **Sources:**
  - `docs/archive/plans/vision-calibration-2026-10-03.md`;
  - `docs/archive/plans/vision-autocalibration-2026-10-03.md`;
  - `docs/research/eye-chart-reuse-2026-10-02.md`;
  - `docs/research/vision-autocalibration-two-models-2026-10-03.md`;
  - `docs/design/vision-calibration.md`.

## Context

The sketch sizes, the pixel budget and the image's place in a request were tuned by hand for
gemma-4 on DeepInfra. The maintainer: "we must not assume gemma-4 is always our target model.
Ideally, we can automatically calibrate to the vision model we've configured."

## Decision

- **Eye charts:** a run calibrates the configured vision model before building, when the tree has
  no calibration for it.
  - The charts are drawn with the sketches' own font, tags, lines and arrowheads, filled at random
    so that nothing can be guessed.
  - About 90 requests, once per endpoint and model; the answers are kept.
- **Three tiers:** the tree's own settings win, then the calibration, then the uncalibrated
  defaults.
  - The defaults are gemma-4's figures "for now" (the maintainer): 645,120 px, 13 px text, 10 px
    heads, 1 px lines, modules of 25, the image first.
- **What is measured, in order, so that nothing depends on the tree's current sizes:**
  1. the image's place: a trial of 6 cards asked both ways; after the text only when clearly
     better;
  2. reading: the budget and the font;
  3. arrows and density, drawn at that font and budget.
- **The budget's rule:**
  - a host that shrinks images gets its own budget;
  - a model that reads at native resolution keeps the configured budget, since there the budget
    is a matter of cost.
- **The record:** calibrations are recorded in `state.sqlite` (`calibrations`). A new suite version
  calibrates again. An incomplete calibration is not recorded, and the run draws to the defaults.
- **The ported parts:** the scoring and fitting are ported from the maintainer's `semantic_pdf_diff`
  (MIT). Its PyMuPDF drawing (AGPL) is not.

## Consequences

- **Models differ:** gemma-4 calibrates to the defaults. Qwen3-VL gets 2 px lines and modules of
  36: it misses thin connections rather than reversing them.
- **Switching models** redraws every sketch, and asks again for every description.
