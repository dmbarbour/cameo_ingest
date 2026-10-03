# Research: calibrating sketches to gemma-4 on DeepInfra, by eye chart, 2026-10-03

**Question.** Are the sketch constants found by hand for gemma-4 on DeepInfra right, as
measured by the eye charts of plan VC? The constants are:
- the pixel budget of 645,120 px;
- 12 px text;
- arrowheads with 10 px legs, and 1 px lines;
- modules of at most 25 shapes.

**Method.**
- `cameo-ingest calibrate-vision -o out/vc/after --suite standard` (0.11.0) on
  `google/gemma-4-31B-it` at DeepInfra, at the descriptions' temperature (0.1), with 4 requests
  at once.
- 68 cards, one sample each: the quick suite first (11 cards), then the rest of the standard
  suite.
- **Time:** 3 min 45 s.
- **Cost:** not read from the bill. At the eye chart's measured $0.0003 a card, about 2 cents.
- The answers are in the tree's store, so the report can be made again for nothing. That is how
  the changes to the tool below were checked.
- **The cards:** drawn in the sketches' own font (Pillow's default, Aileron), number tags, lines
  and arrowheads, at random, so that nothing can be guessed.
- **Scoring:** a code or number counts as read only when every character is right.

## Results

**Reading:** the share of codes and numbers read, by font size, in images of a half to four
times the budget.

| Area | 6 px | 7 px | 8 px | 10 px | 12 px | 16 px | 90% at |
|---|---|---|---|---|---|---|---|
| 0.5× | 0.25 | 0.95 | 0.80 | 1.00 | 0.99 | 1.00 | 8.4 px |
| 1× | 0.05 | 0.62 | 0.65 | 0.99 | 1.00 | 1.00 | 9.5 px |
| 2× | 0.01 | 0.12 | 0.25 | 0.60 | 0.94 | 0.97 | 11.8 px |
| 4× | 0.00 | 0.00 | 0.03 | 0.23 | 0.43 | 0.79 | none |

- **A fixed budget, as known:**
  - The threshold grows beyond the budget: 9.5 px at 1×, 11.8 px at 2×, and none up to
    16 px at 4×.
  - At half the budget it is about the same, 8.4 px: two seeds of 40 items each can't tell
    those apart.
  - So the budget is right for this host. A larger image is shrunk to it.
- **12 px text:**
  - It is read whole at the budget: 80 of 80 codes and numbers, over two cards.
  - The 90% threshold is 9.5 px, so 12 px is 1.27 times it. The tool's rule asks for 1.3 times,
    and so recommends 13 px.
- **The errors below the threshold are look-alike digits.** At 7 and 8 px, among codes of the
  right length:
  - 6 read as 0 (13 times), 8 as B (8), 6 as 5 (6) and 5 as 9 (4);
  - hyphens read as colons, or dropped ("AZ-514" as "AZ:514", "GC-268" as "GC208").

  A code with one wrong character counts as unread.
- **Against the eye chart's 5.7 px (`semantic_pdf_diff`):** that figure is a cap height. Ours
  are font sizes, and Aileron's capitals are about 0.73 of the size. So 9.5 px here is a cap
  height of about 6.9 px, some 20% worse than the eye chart's at a similar image size.
  Plausible causes: Pillow's hinting at small sizes (the cap height jumps from 6 px at size 9.5
  to 8 px at size 10), and the temperature (0.1 here, 0 there).

**Arrows:** 9 boxes, about 11 arrows each, two cards per combination (22 arrows).

| Arrowhead | Line | Right | Reversed |
|---|---|---|---|
| 6 px | 1 px | 73% | 27% |
| 6 px | 2 px | 77% | 23% |
| 10 px | 1 px | 95% | 5% |
| 10 px | 2 px | 95% | 5% |
| 14 px | 1 px | 95% | 5% |
| 14 px | 2 px | 91% | 9% |

- **Every error is a reversal:** each arrow was found, between the right two boxes.
- **10 px heads are as good as 14 px;** 6 px heads are clearly worse. This answers the eye chart
  note's "possibly too small": the size it suspected was a smaller head, shrunk with its text.
- **Line width makes no difference.**
- **Direction:** of 338 arrows on all 20 arrow and density cards:

  | The arrow points | Reversed |
  |---|---|
  | Up | 28% (24 of 87) |
  | Right | 12% (11 of 92) |
  | Left | 11% (9 of 82) |
  | Down | 10% (8 of 77) |

  The model seems to read a vertical connection from top to bottom whatever its head says.

**Density:** boxes per image at the budget, two cards each.

| Shapes | Connections found | The right way round | Reversed |
|---|---|---|---|
| 9 | 95% | 86% | 9% |
| 16 | 100% | 84% | 16% |
| 25 | 92% | 73% | 18% |
| 36 | 83% | 63% | 20% |

- **Finding connections:** reliable up to 25 shapes, and not at 36. That supports the current
  module size of 25.
- **Direction:** reversals grow with density, from 9% to 20%. They are already 5–9% among 9
  boxes, so smaller modules would not remove them.

## What this means for the sketches

- **The cards are harder than the real task.** A diagram's description request already has:
  - every shape's label, in the legend;
  - every connection with its direction, taken from the model;
  - the instruction not to restate them.

  The sketch serves for the layout, and its number tags tie shapes to the legend. So a model
  that reverses an upward arrow in a card is not thereby writing reversed relationships. The
  text tells it the direction.
- **What the tool recommended:** every constant kept, except the font, 12 → 13 px. 12 px is 1.27
  times the threshold, short of the 1.3× margin.
- **My first advice, withdrawn:** keep 12 px so that no tree would be redrawn. That made the cache
  a reason, and the maintainer ruled it out (below).

## Changes to the tool after the first run

- **Density:** judged on connections found, either way round, rather than on connections the
  right way round. Direction is the arrows family's measure. Reversals happen among few shapes as
  among many, so counting them made every density fail, and said nothing about module size.
  The report shows both.
- **Progress:** cards are counted as they are answered, not in order. Before, a slow card held
  the bar at 4 of 11 for two minutes.
- **The report:** the font's reason is now stated as a ratio to the threshold ("1.27x the
  threshold: short of the 1.3x margin") rather than "too small to read reliably". The
  recommendations table no longer repeats the whole arrow grid.
- **The cards' truth:** each arrow card now records its boxes' centres. The images and requests
  are unchanged, so stored answers still serve. The analysis by direction above uses them.

## The maintainer's policy, and a second run

**The policy (2026-10-03):** "I'd rather not have special exceptions just for maintaining the
existing test cache."
- **Defaults follow the calibration.** Each recommendation is derived from the measurements
  alone; the tree's current value is shown, never preferred.
- **Undecided measurements:** where the cards decide nothing (no arrow size passes, say), the
  tool's reference values serve, never the tree's.
- **The budget at native resolution:** a matter of cost, kept as configured.
- **Pressure:** a test that means to push a model past what it reads comfortably says so, and
  sets its sizes from the calibration.

**What changed in the tool** (0.12.0):
- **Recommendations:** no longer anchored to the current values. A perfect reader now gets the
  smallest sizes tested, and a model whose host has a larger budget gets the larger budget.
- **Two stages:** the reading cards first, which decide the budget and the font. Then the arrow
  and density cards, drawn at that font and budget rather than the tree's current ones.
- **Arrow cards:** four seeds instead of two, so 44 arrows per size. 95% then allows two
  reversals, where 22 arrows allowed one. The standard suite is 80 cards.
- **The cards' boxes:** narrower (2 font sizes of padding, not 3), so that 36 boxes fit at 13 px.
  A count that doesn't fit at the chosen font is left out.
- **The default font:** 13 px. The maintainer took gemma-4's figures as the uncalibrated
  defaults "for now", until a run calibrates to whichever vision model is configured (plan VA).
  The sketch sizes are now always in the
  projects' options hash. A new version rebuilds every project anyway, so leaving them out at
  their defaults spared nothing.

**The second run:**
- The 48 reading cards came from the store. 32 new arrow and density cards were drawn at 13 px,
  taking 5 min at 4 at once, for under a cent.
- **The recommendations:** every one is today's default. The budget, 10 px heads, 1 px lines and
  modules of 25 hold; the font is 13 px, now the default.

| Arrowhead | Line | Right (of 44) | Reversed |
|---|---|---|---|
| 6 px | 1 px | 82% | 14% |
| 6 px | 2 px | 73% | 27% |
| 10 px | 1 px | 95% (42) | 5% |
| 10 px | 2 px | 89% | 11% |
| 14 px | 1 px | 100% (44) | 0% |
| 14 px | 2 px | 95% | 5% |

| Shapes | Connections found | The right way round |
|---|---|---|
| 9 | 100% | 82% |
| 16 | 97% | 84% |
| 25 | 93% | 72% |
| 36 | 86% | 57% |

- **10 px heads pass at the rule's edge:** one more reversal in 44 would have recommended 14 px,
  which read all 44. The rule has no margin, unlike the font's.
- **2 px lines read worse than 1 px** in this run (89% and 95%, against 95% and 100%).
- **Upward arrows,** over all 32 cards: 24% reversed, against 13% right, 17% left and 8% down.

## Open questions

- **The arrows' rule:** should it carry a margin, as the font's does? 10 px heads pass at
  95.5% (42 of 44), and 14 px read all 44.
- **Upward arrows:**
  - Would a filled head, or the mid-line arrow that flows already get, cut the bias?
  - Does it matter, given that directions reach the model as text? A spot check of descriptions
    of diagrams with many upward arrows would tell.
- **Other models:** Qwen3-VL reads at native resolution (by the eye chart). Calibrating it would
  test the "native resolution" branch of the budget rule on a real model.
