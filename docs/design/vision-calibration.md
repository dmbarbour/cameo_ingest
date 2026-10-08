# Design: calibrating sketches to the vision model, and validating them

How a run fits its sketches to whichever vision model is configured, and measures what quality to
expect. Decisions: ADR-0014 to ADR-0016. The README's "Calibrating sketches to the vision model"
gives the user's view.

## Where sizes come from

Two tiers, applied in `ProjectOptions.of` (`TreeSettings.calibrated`); the tree's own sizes,
which came first, went in 0.21.0 (ADR-0030):
1. **The configured vision model's calibration,** from `state.sqlite` (`calibrations`), for the
   sizes in `config.CALIBRATED`.
2. **The uncalibrated defaults,** gemma-4's figures at DeepInfra "for now" (the maintainer):
   - `IMAGE_PIXELS` 645,120;
   - `SKETCH` (13, 10.0, 1);
   - `MODULES` (25, 6, 25);
   - the image first.

A run without a vision model, or with `--no-calibrate` (a developer's flag), draws to the
defaults. Every size is in
each project's options, so a change of model redraws its sketches (ADR-0004).

## When a run calibrates

In the runner's `prepare` hook, after the scan and before the build (`cli.calibration_for_run`):
- **No record, sketches drawn:** a vision model with no record calibrates, then validates. That is
  about 92 requests, then about 12, a few minutes on a hosted model.
- **A record without validation:** validation runs alone.
- **An incomplete calibration** isn't recorded, and the run draws to the defaults with a warning.
  A calibration is incomplete when more than 5% of the cards went unanswered (4 of 92; at least
  one), more than half of one group's did (a reading area and font, an arrowhead and line, a
  density, a way round in the trial), more than half the replies were unreadable, or no font size
  was read (`calibrate.problem`). Unanswered cards are left out of every measure (RN-001); before
  0.31.0, one unanswered card made a calibration incomplete, and counted as misread.
- **Calibrating on demand:** `cameo-ingest calibrate-vision -o OUT [--suite quick|standard]`. The
  quick suite (11 cards) checks a model and is never recorded.
- **Recorded:** a record is keyed by endpoint (`''` for the OpenAI default), model and
  `calibrate.SUITE_VERSION`. A new suite version calibrates again. Answers are stored, so a rerun
  asks nothing.

## The eye charts (`eyechart.py`)

Cards are drawn with the sketches' own primitives: Pillow's default font (Aileron), number tags,
`_polyline` and `_arrowhead`.
- **Seeded by id:** each card is seeded by its id, so the same card is the same bytes every time.
- **Random content:** letters exclude I, O and Q; box numbers are shuffled.
- **Shape:** images are 4:3, with sides in whole 48 px patches.

| Family | What it measures | Standard suite |
|---|---|---|
| Image order (trial) | Reading at 7, 8, 10 and 12 px at the budget, and 2 arrow cards, each asked with the image before and after the text | 6 cards, both ways |
| Reading | Lines of codes and numbers at 6, 7, 8, 10, 12 and 16 px, in images of 0.5, 1, 2 and 4 times the starting budget | 48 |
| Arrows | 9 numbered boxes joined by arrows; heads of 6, 10 and 14 px, lines of 1 and 2 px, four seeds (44 arrows per size) | 24 |
| Density | 9, 16, 25 and 36 boxes in one image; counts that don't fit at the chosen font are dropped | 8 |

**Stages:**
1. the trial chooses the image's place;
2. the reading decides the budget and the font;
3. the arrow and density cards are drawn at that font and budget.

So nothing measured depends on the tree's current sizes.

**Scoring and fitting** are ported from the maintainer's `semantic_pdf_diff` (MIT):
- **Reading:** a code or number counts only when every character is right (tokens matched in
  order).
- **Arrows:** each is scored right, reversed, wrong ends, missed or spurious.
- **Fitting:** a monotone fit (pool-adjacent violators), interpolated where the share read reaches
  `eyechart.PASS` = 0.9.

## The rules (`calibrate.recommend`)

From the measurements alone (ADR-0014). Where the cards decide nothing, the defaults serve.

| Setting | Rule | Constant |
|---|---|---|
| Image's place | After the text only if it reads better by at least 5 points and by more than twice the standard error of the per-card difference | `ORDER_GAIN` = 0.05 |
| `image_pixels` | Areas whose 90% threshold is within 1.15× of the smallest read "as well". If all do, the model reads at native resolution, or its host's budget is at least 4×: either way the budget, a cost, stays as configured. Otherwise, the largest area that, with every smaller one, reads as well, in whole patches; when that is the smallest tested, the report says the host's budget is at most half, perhaps less | `FLAT` = 1.15 |
| Font | `ceil(1.3 × the threshold)` at the chosen budget (at 1× for a native-resolution model) | `FONT_MARGIN` = 1.3 |
| Arrowheads, lines | The thinnest lines, then the smallest heads, with 95% of arrows the right way round. No margin | `ARROWS_PASS` = 0.95 |
| Modules | The most shapes among which 90% of connections are found, either way round (a monotone fit across counts); `N:min(6,N):N` | `DENSITY_PASS` = 0.9 |

- **Density ignores direction:** direction is the arrows' measure, and reversals happen among 9
  boxes as among 36. Counting them made every density fail.
- **The budget's range:** 0.5× to 4×. A host whose budget is beyond 4× reads flat at every area,
  like a model at native resolution, and the report names both. Either way larger images read no
  smaller text, so the configured budget is kept. A host below 0.5× gets the smallest tested, and
  the report says its budget may be smaller still.
- **Unmeasured:** image sides in whole 48 px patches; they round a side by at most 47 px.

## Validation on the tree's own sketches (`validate.py`)

ADR-0016.
- **The sample:**
  - up to `PER_STRATUM` (4) each of small diagrams (up to `SMALL` = 9 shapes), medium ones (up to
    the module size) and modules of large ones;
  - from up to `MAX_PROJECTS` (4) projects under `MAX_BYTES` (30 MB), ordered by a hash of their
    sha256;
  - within a stratum, the commonest diagram kinds first, round robin, with projects taking turns.
- **The question,** `eye-sketch@v2`, with the sketch's reading guide: from the image alone, every
  numbered shape with its name, and every connection from number to number.
- **The truth** is the diagram's own: names as drawn (the last word of a name cut with "…"
  dropped), and connections among the drawn shapes.
- **The scores:**
  - names read (word by word);
  - connections found (either way round);
  - directions right;
  - connections invented (listed, but not in the diagram).
- **Warnings:** under 90% on the first three, over 10% invented, or more than half the sketches
  unreadable. The run carries on.
- **Once per record:** a tree without diagrams records an empty sample, so runs don't look again.
- **Lower bounds:** the scores bound what the image contributes, not description quality, since
  descriptions also get every name and connection as text.
- **Comparing versions or prompts:** `scripts/validate_sketches.py` chooses a sample by key
  (`choose`, with `--faults` to target), draws and asks with any version from 0.13.0 on (`ask`,
  `--no-guides`), and scores runs alike (`score`).

## Calibrated models (2026-10-03)

| | gemma-4 (31B, DeepInfra) | Qwen3-VL (235B, DeepInfra) |
|---|---|---|
| How it sees | Shrinks images to a fixed budget (threshold 9.5 px at 1×, 11.8 px at 2×) | Native resolution (9.5 to 9.9 px at every area) |
| Sizes | The defaults | 2 px lines, modules of 36 |
| Image's place | First (no difference) | First (+5 points after the text, within the error) |
| Validation: names, connections, directions | 99%, 73%, 91% | 97%, 82%, 98% |
| How it fails | Reverses arrows; upward ones 24 to 28% of the time | Misses thin connections; reads clean trees top-down |

Sources:
- `docs/research/vision-calibration-gemma4-2026-10-03.md`;
- `docs/research/vision-autocalibration-two-models-2026-10-03.md`;
- `docs/research/sketch-ambiguities-2026-10-03.md`.

Both read whole codes from about 9.5 px, a cap height of about 6.9 px. The eye chart study found
5.7 px; Pillow's hinting and temperature 0.1 are likely causes.
