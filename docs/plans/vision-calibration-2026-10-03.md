# Plan: calibrating sketches to the vision model, by eye chart, 2026-10-03

- **Status:** Proposed on 2026-10-03.
- **Step prefix:** `VC`, so steps are `VC-01`, `VC-02` and so on
- **Addresses:** the tentative plan "Vision calibration by eye chart" (plan index). Sketches are
  drawn to constants found by hand for gemma-4 on DeepInfra (FU-012, FU-015):
  - the pixel budget (645,120 px, 48 px patches);
  - 12 px text;
  - arrowheads with 10 px legs, and 1 px lines;
  - modules above 25 shapes.

  For another model or host they may be wrong. The maintainer's eye chart in
  `semantic_pdf_diff` measures what a vision model reads.
- **Research:** `docs/research/eye-chart-reuse-2026-10-02.md`.
  - **For gemma-4:** the budget is right, and the text has a 1.2–1.6× margin. Our arrowheads
    are the size at which gemma-4 reversed about one arrow in four. That is inferred, since head
    and text size were varied together.
  - **The eye chart itself:** draws with PyMuPDF (AGPL), so its ideas and scoring are ported, not
    its drawing. Its line widths, and densities above 9 boxes, were never tested.

## Design

**Cards in the sketches' own terms.** Calibration draws test images ("cards") with
`sketch.py`'s own font (Pillow's default, Aileron), boxes, number tags, arrowheads and lines.
The thresholds it finds are then in the units the settings use. Each card has random content,
seeded by its id, so that nothing can be guessed and the same card is the same bytes every
time. Three families:

| Family | What it measures | Cards (standard suite) |
|---|---|---|
| **Reading** | Lines of random codes and numbers, in the sketch font, at font sizes 6–16 px. Each is drawn into images of a half, one, two and four times the current budget, so that a fixed budget shows as a threshold that grows with the image (gemma-4 on DeepInfra) and native resolution as one that doesn't (Qwen3-VL). | 6 sizes × 4 areas × 2 seeds = 48 |
| **Arrows** | Boxes named by random codes and tagged with numbers, as shapes are, joined by arrows drawn as sketches draw them. Arrowhead legs of 6, 10 and 14 px, lines of 1 and 2 px. The model lists every arrow, from number to number, as its descriptions must. Reversed arrows are counted apart. | 3 heads × 2 lines × 2 seeds = 12 |
| **Density** | The same, at 9, 16, 25 and 36 shapes per image at the budget: how many shapes an image can hold before connections are misread. That sets the size of a large diagram's modules. | 4 sizes × 2 seeds = 8 |

A quick suite (about 16 cards) checks a model in a few cents; the standard suite (68 cards)
calibrates it.

**Asking.**
- **The route:** the tree's configured vision model and endpoint, through `EnrichmentSession`.
  Images go first for gemma, at the temperature the descriptions use.
- **Answers:** kept in the answer store, so that a rerun or a new report costs nothing.
- **Templates:** calibration has its own (`eye-read`, `eye-arrows`), outside `CURRENT`, so that
  they change no project's options.
- **Replies:** asked for as JSON, and read leniently.

**Scoring,** ported from the eye chart:
- **Reading:** tokens matched in order.
- **Arrows:** right, reversed, wrong ends, missed or spurious.
- **The fit:** a monotone fit per image size, with the threshold where 90% are read.

**What it recommends,** each derived with a margin. The report shows the current value
beside each, and the scores behind it:

| Setting | Derived from |
|---|---|
| `image_pixels` | The largest area at which the reading threshold still holds, at a whole number of 48 px patches; for a model reading at native resolution, the current budget is kept, as more pixels then cost more tokens |
| Sketch font size | The smallest size read by 90% at the chosen budget, times 1.3 |
| Arrowhead legs, line width | The smallest with 95% of arrows the right way round |
| `diagram_modules` maximum | The most shapes with 90% of connections right |

**Applying.**
- **`--apply`:** writes the recommendations to the tree's settings, applied on every run like the
  other switches.
- **The font, arrowhead and line sizes become settings**, as `image_pixels` and
  `diagram_modules` are. `sketch.py` takes them as a style rather than module constants.
- **The defaults stay today's values,** so a tree that doesn't calibrate draws the same sketches
  and keeps its projects' option hashes.
- **The cost:** a changed setting redraws every sketch, and every diagram is described again by
  the LLM (on the samples, about 1,100 requests, about $1). The command says so, with the count,
  before it applies.

## Steps

| Step | What | Status |
|---|---|---|
| VC-01 | **Cards** (`eyechart.py`): the three families, drawn with `sketch.py`'s primitives (which a style object parameterizes, VC-05), each card with its truth and prompt, seeded by its id.<br>**Tests:** the same bytes twice; every truth string fits its image; a perfect answer scores 1.0. | |
| VC-02 | **Scoring and fitting:** the reading and arrow scores, the monotone fit and threshold, ported from `semantic_pdf_diff` (MIT, by the maintainer), with a note of where they came from.<br>**Tests:** each kind of error on hand-made answers; a threshold interpolated; a dip smoothed. | |
| VC-03 | **`cameo-ingest calibrate-vision -o OUT [--suite quick\|standard] [--max-calls N] [--apply]`:** the cards asked through the session, answers stored. It writes `calibration/<model>-<date>/` with the cards (PNG), the answers, `results.json` and `report.md`.<br>**Tests:** a fake model that reads perfectly, and one that reverses every arrow. | |
| VC-04 | **The recommendations** from the results, as in the design. The report shows the current value beside each, and the scores behind it.<br>**Tests:** results that imply a fixed budget, native resolution, and too-small arrowheads give the expected recommendations. | |
| VC-05 | **A sketch style as settings:** `SketchStyle(font_px, arrow_px, line_px)`, through `render_png`, the presets and the SVG; in `TreeSettings` and `ProjectOptions`, in the hash only when not the default. `--apply` writes them, and `image_pixels` and `diagram_modules`, after showing what will be drawn and asked again.<br>**Tests:** a `--no-llm` tree at the defaults is the same as before (`treediff`); a changed style changes the sketches and the projects' hashes. | |
| VC-06 | **The live calibration:** the standard suite on gemma-4 at DeepInfra, a few cents. Its results go in a research note, comparing the recommendations with today's constants and with the eye chart's findings. | |

## Checkpoints

| Checkpoint | Steps | Output |
|---|---|---|
| CP1: cards and scores | VC-01, VC-02, and VC-05's style object (defaults only) | `eyechart.py`; sketches unchanged |
| CP2: the command | VC-03, VC-04, VC-05 | `calibrate-vision`, settings; 0.11.0 |
| CP3: gemma-4 | VC-06 | The research note |

## When to stop and ask

- **Before applying to any tree:** if gemma-4's calibration recommends values other than today's,
  the maintainer decides whether to adopt them, since that redraws the sketches and re-asks the
  descriptions.
- **Answers that can't be scored:** the model's replies to the cards are mostly unreadable, so
  that the prompts need rework.
