# ADR-0009: Versioned prompt templates; no wording outside a version

- **Status:** Accepted, 2026-09-30 to 2026-10-02.
- **Sources:**
  - LQ-01 (`docs/archive/plans/llm-quality-2026-09-30.md`);
  - FU-014R1;
  - AR-009R1 to R3 and AR-025;
  - plan RA's decision 4 and CP4.

## Context

Quality ratings, the answer store and replay all depend on knowing exactly what a model was asked.
Wording added outside a template "defeats the versioning that quality ratings rely on".

## Decision

- **Templates** are named, versioned objects in `prompts.py`, keyed `id@vN`:
  - `{{SLOT}}` markers, each slot described;
  - `image_first`, the default place of the image;
  - `fragments`, every sentence a request may add, which belong to the version.
- **Values** are built by one function per template, in `prompt_values.py`. Limits are named
  constants.
- **Versions:**
  - changing a template's text or fragments means a new version;
  - a number is never reused, because the request log names old ones;
  - the code keeps only the versions in use, one per id (an assert);
  - retired templates are at tag `studies-2026-10-02`.
- **Pinned:** a test pins each current template's request by hash.
- **In the options:** the keys of the templates in use are part of each project's options
  (ADR-0004).
- **Outside `CURRENT`:** calibration's and validation's templates (`eye-read`, `eye-arrows`,
  `eye-sketch`), so that they change no project's options.

## Consequences

- **A new version rewrites the projects it affects.** Only the changed requests are paid for.
- **The request log** (`requests` in `llm.sqlite`) names each request's template and values.
