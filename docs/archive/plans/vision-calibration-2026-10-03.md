# Plan: calibrating sketches to the vision model, by eye chart, 2026-10-03

- **Status:** Approved on 2026-10-03 ("Looks good… Go", with a few dollars of DeepInfra allowed).
  Done on 2026-10-03 (0.12.0). CP1, CP2 (0.11.0) and CP3 done. Then, following the maintainer's
  decisions:
  - **Recommendations:** from the measurements alone ("no special exceptions just for
    maintaining the existing test cache").
  - **The defaults:** gemma-4's figures, 13 px text among them, are the uncalibrated defaults
    "for now".

  Plan VA (`vision-autocalibration-2026-10-03.md`) builds on this, calibrating automatically to
  whichever vision model is configured.
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

A quick suite (11 cards) checks a model in a cent or so; the standard suite (68 cards)
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

**What it recommends,** from the measurements alone. The report shows the current value beside
each, and the scores behind it, but the current value is never preferred: no cache is a reason
to keep a size (the maintainer's policy, 2026-10-03). Where the cards decide nothing, the
uncalibrated defaults serve.

The reading cards are asked first. The arrow and density cards are then drawn at the font and
budget the reading calls for (80 cards in all, the arrows with four seeds).

| Setting | Derived from |
|---|---|
| `image_pixels` | The largest area read as well as the smallest, at a whole number of 48 px patches. For a model reading at native resolution, the budget is a cost, kept as configured |
| Sketch font size | The size read by 90% at the chosen budget, times 1.3 |
| Arrowhead legs, line width | The thinnest lines and smallest heads with 95% of arrows the right way round |
| `diagram_modules` maximum | The most shapes with 90% of connections found, either way round. Direction is the arrows' measure (changed after the live run: see Results) |

**Applying.**
- **`--apply`:** writes the recommendations to the tree's settings, applied on every run like the
  other switches.
- **The font, arrowhead and line sizes become settings**, as `image_pixels` and
  `diagram_modules` are. `sketch.py` takes them as a style rather than module constants.
- **The defaults:** 0.11.0 kept today's values, and kept the sizes out of the option hashes at
  their defaults. 0.12.0 changed both, by the maintainer's decisions:
  - gemma-4's figures (13 px text) are the uncalibrated defaults;
  - the sizes are always in the options. A new version rebuilds every project anyway, so leaving
    them out spared nothing.
- **The cost:** a changed setting redraws every sketch, and every diagram is described again by
  the LLM (on the samples, about 1,100 requests, about $1). The command says so, with the count,
  before it applies.

## Steps

| Step | What | Status |
|---|---|---|
| VC-01 | **Cards** (`eyechart.py`): the three families, drawn with `sketch.py`'s primitives (which a style object parameterizes, VC-05), each card with its truth and prompt, seeded by its id.<br>**Tests:** the same bytes twice; every truth string fits its image; a perfect answer scores 1.0. | Done |
| VC-02 | **Scoring and fitting:** the reading and arrow scores, the monotone fit and threshold, ported from `semantic_pdf_diff` (MIT, by the maintainer), with a note of where they came from.<br>**Tests:** each kind of error on hand-made answers; a threshold interpolated; a dip smoothed. | Done |
| VC-03 | **`cameo-ingest calibrate-vision -o OUT [--suite quick\|standard] [--apply]`** (with the run settings, `--llm-max-calls` among them, for this calibration only): the cards asked through the session, answers stored. It writes `calibration/<model>-<date>/` with the cards (PNG), the answers, `results.json` and `report.md`.<br>**Tests:** a fake model that reads perfectly, and one that reverses every arrow. | Done |
| VC-04 | **The recommendations** from the results, as in the design. The report shows the current value beside each, and the scores behind it.<br>**Tests:** results that imply a fixed budget, native resolution, and too-small arrowheads give the expected recommendations. | Done |
| VC-05 | **A sketch style as settings:** `SketchStyle(font_px, arrow_px, line_px)`, through `render_png`, the presets and the SVG; in `TreeSettings` and `ProjectOptions`, in the hash only when not the default. `--apply` writes them, and `image_pixels` and `diagram_modules`, after showing what will be drawn and asked again.<br>**Tests:** a `--no-llm` tree at the defaults is the same as before (`treediff`); a changed style changes the sketches and the projects' hashes. | Done |
| VC-06 | **The live calibration:** the standard suite on gemma-4 at DeepInfra, a few cents. Its results go in a research note, comparing the recommendations with today's constants and with the eye chart's findings. | Done |

## Checkpoints

| Checkpoint | Steps | Output |
|---|---|---|
| CP1: cards and scores | VC-01, VC-02, and VC-05's style object (defaults only) | `eyechart.py`; sketches unchanged |
| CP2: the command | VC-03, VC-04, VC-05 | `calibrate-vision`, settings; 0.11.0 |
| CP3: gemma-4 | VC-06 | The research note |

## Results (2026-10-03)

The standard suite on gemma-4 at DeepInfra: 68 requests in 3 min 45 s, about 2 cents
(`docs/research/vision-calibration-gemma4-2026-10-03.md`).

| Setting | Today | Measured | Recommended |
|---|---|---|---|
| `image_pixels` | 645,120 | 90% read at 9.5 px at the budget, 11.8 px at twice it: a fixed budget | Kept |
| Font | 12 px | 12 px read 80 of 80 at the budget; 1.27 times the 9.5 px threshold | 13 px (the 1.3× rule) |
| Arrowheads, lines | 10 px, 1 px | 95% the right way round; 14 px no better, 6 px 73%; line width no matter | Kept |
| `diagram_modules` | 25:6:25 | Connections found among 25 shapes 92%, among 36 83% | Kept |

- **Upward arrows:** reversed 28% of the time, against 10–12% for the other directions.
  Descriptions get every connection's direction as text, so this matters less there than on
  the cards.
- **Changed in the tool after the run:**
  - density judged on connections found;
  - progress counted as cards are answered;
  - the report's wording;
  - box centres in the cards' truth.
- **The maintainer's decision:** no exceptions to keep caches. The note's advice to keep 12 px is
  withdrawn, and the policy is applied:
  - recommendations unanchored;
  - two stages;
  - four seeds for arrows;
  - narrower card boxes;
  - 13 px as the default.

**The second run** (0.12.0): the reading from the store, plus 32 new arrow and density cards at
13 px. Every recommendation is now the default: the maintainer took gemma-4's figures as the
uncalibrated defaults "for now".
- **Arrowheads:** 10 px heads read 42 of 44 the right way round, at the rule's edge; 14 px read
  all 44.
- **Modules:** connections are found among 25 shapes 93% of the time, among 36 86%.
- **The comparison tree:** a `--no-llm` tree of the samples and the fiction differs from 0.11.0's
  only in its sketches.
- **The cost:** trees with LLM descriptions ask again for each sketch's description when next run.

## When to stop and ask

- **Before applying to any tree:** if gemma-4's calibration recommends values other than today's,
  the maintainer decides whether to adopt them, since that redraws the sketches and re-asks the
  descriptions.
- **Answers that can't be scored:** the model's replies to the cards are mostly unreadable, so
  that the prompts need rework.
