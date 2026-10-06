# ADR-0024: The text model's calibration guards the part size; it never enlarges it

- **Status:** Accepted, 2026-10-04 (plan TC; the maintainer: "A is fine"); updated on 2026-10-05 (Changes, below).
- **Sources:**
  - `docs/archive/plans/text-calibration-2026-10-04.md`;
  - `docs/research/text-reading-2026-10-04.md`;
  - `docs/research/sandwiching-2026-09-30.md`;
  - `docs/design/llm-enrichment.md`.

## Context

A large package is summarized in parts of at most 12,000 characters, a size measured for gemma-4
alone. The maintainer asked that the tool "detect via calibration" what the configured text model
reads well, as it does for the vision model (ADR-0015), and "do some cutting ourselves if needed".

Reading cards of up to 192,000 characters, with five groups each and every name invented, were
read evenly by gemma-4 and DeepSeek-V3.2 at every length. But real packages are harder: in one
request gemma-4 lost the middle of real packages over 100,000 characters. And the part size also
sets how fine part summaries are: gemma-4 names 94% of a 12,000-character part's elements, 15% of
a 48,000-character part's.

## Decision

- **Inputs are cut by us, never truncated:** a section longer than a part goes in pieces, each
  headed by its title (0.15.3).
- **The part size** is the text model's calibration, else 12,000.
- **Calibration is a guard:**
  - each text model is read on 30 requests of cards, of 6,000 to 24,000 characters, once per
    model and endpoint;
  - a model that reads 12,000 characters evenly keeps 12,000; one that doesn't, or an endpoint
    that cuts long inputs, gets 6,000;
  - calibration never makes parts larger.

## Consequences

- A weaker model, or a small context window, gets smaller parts without a setting by hand.
- A strong model's parts stay as fine as today's.
- Calibrations are recorded by kind (schema 4), since one model can be both the text and the
  vision model.

## Changes

- 2026-10-05: `--part-chars` is gone: the part size is calibrated or the default (ADR-0030). Before: `3e88bb9`.
