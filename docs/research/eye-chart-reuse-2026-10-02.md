# Research: reusing semantic_pdf_diff's eye chart to calibrate sketches, 2026-10-02

**Question.** The maintainer's other project, `semantic_pdf_diff` (MIT, © 2026 David Barbour),
has an "eye chart": a test of what a vision model actually reads in an image. Its owner says it
is now relatively stable. What can cameo-ingest copy or reuse to calibrate its sketches for
whichever vision model is configured, in place of constants found by hand for gemma-4 on
DeepInfra?

**Method.**
- A survey of the repository at `fc4adc6`, read only, with no runs and no LLM calls.
- Spot checks against its code and notes: the licence, the file sizes, the scoring constants,
  the stroke and arrowhead rules, gemma-4's thresholds and its arrow reversals.
- `SPD/` below means the repository's root.

## What the eye chart is

- **Where:** `SPD/lab/src/semantic_pdf_diff_lab/bench/eyetest.py` (1,038 lines), with a CLI in
  `SPD/scripts/eye_test.py` (`run`, `report`) and tests in `SPD/tests/test_eyetest.py` (156
  lines). The write-ups are `SPD/docs/research/eye-tests-2026-09-30.md` and
  `page-tests-2026-10-01.md`.
- **Cards:** drawn with PyMuPDF at known cap heights, in the image's own pixels, and seeded by
  their ids, so the bytes are the same each run.
  - **Families:** random codes and numbers, real words, pseudo-words, look-alike codes, pairs,
    tables, graphs (boxes joined by labelled arrows) and charts.
  - **The standard suite:** 365 cards, mostly reading at 4–16 px across nine image sizes and
    shapes.
- **Asking:** one prompt per family, for JSON. Each says the content is random, so nothing can be
  guessed.
- **Scoring:** exact, with no rater. Reading scores the tokens matched in order and the
  character error rate. Graphs are scored as right, reversed, label misbound or misread, ends
  wrong, or spurious.
- **The result:** the cap height read 90% of the time (`PASS = 0.9`), fitted monotonically, per
  image size. A "relative" threshold per 1000 px of side shows a fixed pixel budget when it is
  the same across sizes. It reports thresholds, not drawing constants.
- **Cost:** for gemma-4 on DeepInfra, about $0.13 for the standard suite, or $0.0003 a card.
  Answers are recorded, so reruns are free.
- **Maturity:** first committed on 2026-09-30, with results last changed on 2026-10-01; since
  then only moved and tidied. Six models measured, at temperature 0, one sample each.

## What it says about cameo-ingest's sketches today

| Constant | What the eye chart found for gemma-4 on DeepInfra | Verdict |
|---|---|---|
| Pixel budget, 645,120 px in 48 px patches | Prompt tokens stay at 406 from 512² to 2048²; the code threshold grows with the side (5.7 px at 768², 15.8 at 2048²), as a fixed budget would | **Right for gemma-4**, wrong for others: Qwen3-VL reads about 6 px at any size, and its tokens grow tenfold |
| Text, `FONT_PX = 12` (Pillow's Aileron: capitals 9 px) | 90% thresholds at budget-sized images: codes 5.7 px, real words 4.4, pseudo-words 7.0, look-alike codes 7.7 | **Adequate:** 1.6× margin over codes, 1.2× over look-alikes. Aileron and grey text were never tested. Llama-4 and Mistral need 7–9.6 px, so it is borderline for them |
| Arrowheads, 10 px legs (about 9 px long) | All of gemma-4's arrow errors are reversals, 15 of 118. On 1024² graphs: 10 of 39 reversed at 7 px text (heads about 8.8 px long once shrunk), 2 of 39 at 14 px | **Possibly too small:** ours are the size of the cards that reversed one arrow in four. Head and text size were varied together, so this is inferred, not measured |
| Line width, 1–2 px | Never varied (strokes were 0.07 × text size, at least 1 px) | Unknown |
| Modules above 25 shapes, of 6 to 25 | Graphs had at most 9 boxes (gemma-4: 0.83–1.0 at 10 px and up). Tables show density breaking binding before legibility: 3 of 8 cells right in 20-row tables at 8 px, 8 of 8 in 8-row tables | Unknown, and the likeliest place where a threshold matters |

**How much the arrows matter here.** A diagram description is asked with the diagram's text: its
legend, and its connections listed from source to target (FU-001, FU-013). So the model need
not read a direction from an arrowhead, and a reversal in the picture can only conflict with the
text it was given. Larger arrowheads are still cheap, and worth measuring with the rest.

## What to copy, reuse or leave

- **Copy and adapt, about 350 lines,** drawn with Pillow:
  - the generators: random codes, numbers, word lists and look-alike codes;
  - normalising, edit distance and the reading and graph branches of the scoring;
  - the monotone threshold fit and the relative threshold;
  - cards seeded by their ids;
  - a fake "perfect" model for tests.
- **Reuse only as ideas:**
  - checking each card's answer key against what was drawn;
  - prompt tokens as a probe of the budget (our `OpenAIChat` would need to return usage);
  - a profile that picks the nearest measured size.
- **Leave behind:**
  - PyMuPDF, which is AGPL-3.0, so it should not become a dependency here;
  - the pydantic answer models, its dispatcher, fixtures and ledger;
  - the page tests and the PDF tiling plan;
  - the table, pair and chart families, the pseudo-word levels and the large glyphs.

## A calibration step for cameo-ingest

`cameo-ingest calibrate-vision [--suite quick|full] [--apply]`, run against the configured vision
model through `EnrichmentSession`, whose store makes reruns free.

1. **Cards in cameo's own terms:** Aileron, number tags, our arrowheads, 1–2 px lines and our
   faded greys, so that thresholds come out in the units the sketches use.
   - **Reading,** about 36 cards: 6 font sizes, at a half, once and four times the candidate
     budget, 2 seeds. This fits the font threshold, and tells a fixed budget from native
     resolution.
   - **Arrows,** about 12 cards: heads of 6, 10 and 14 px, lines of 1 and 2 px. They score
     reversals and misread tags.
   - **Density,** about 8 cards: graphs of 9, 16, 25 and 36 shapes. The largest with at least 90%
     of its edges right sets the modules' maximum.
2. **Answers** parsed from JSON by a small, lenient parser.
3. **Derived settings:**
   - `image_pixels`, where the threshold stops improving;
   - the font size, the smallest whose capitals are about 1.3 × the code threshold;
   - arrowhead and line sizes, from the arrow cards;
   - `diagram_modules`, from the density cards.
4. **Applied as tree settings** with `--apply`.
   - **Settings:** `image_pixels` and `diagram_modules` exist. The font, arrowhead and line
     sizes would join `TreeSettings` and `ProjectOptions`, so that projects are drawn again.
   - **The record:** the model, endpoint, date and scores, kept in `state.sqlite`.

**Size and cost.** About 600–800 lines and 150–200 lines of tests. A run is about 56 cards, a
cent to three on gemma-4 at DeepInfra, and perhaps 3–5 times that on Qwen3-VL (estimated from
its ledger, not run).

**Caveat.** The eye chart is three days old and measured each model once, at temperature 0, on
clean renders. A calibration should report its scores beside the settings it derives, so that a
surprising setting can be checked.
