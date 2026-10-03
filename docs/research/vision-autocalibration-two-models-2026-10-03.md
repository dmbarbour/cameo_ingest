# Research: calibrating and validating two vision models, 2026-10-03

**Question.** Plan VA makes calibration automatic for whichever vision model is configured,
and validates it on the tree's own sketches. Does it adapt the sketches to models that see
differently? And what quality should a real ingestion expect from each?

**Method.**
- `cameo-ingest calibrate-vision` (0.13.0): the calibration and validation a run does when it
  meets a model for the first time, without building the projects.
- **The tree:** `out/va/v013`, the samples and the fiction, 27 projects.
- **The models,** both at DeepInfra, at the descriptions' temperature (0.1), with 4 requests at
  once:
  - `google/gemma-4-31B-it`: a fixed pixel budget;
  - `Qwen/Qwen3-VL-235B-A22B-Instruct`: native resolution, by the eye chart study
    (`eye-chart-reuse-2026-10-02.md`).
- **The suite:** the standard one: a trial of the image's place (6 cards both ways), 48
  reading cards, 32 arrow and density cards, and 12 of the tree's sketches.
- **gemma-4's answers:** mostly from the store of the earlier calibrations, so that only the
  trial's other order and the validation were new.
- **Cost:** not read from the bill. A few cents for both.
- **Time:** gemma-4, about 2.5 min (the validation). Qwen3-VL, about 7.5 min in all.

## The calibrations

| Setting | gemma-4 | Qwen3-VL | Uncalibrated default |
|---|---|---|---|
| `image_pixels` | 645,120: the threshold grows beyond the budget (9.5 px at 1×, 11.8 px at 2×) | 645,120: the threshold is the same at every size (9.5–9.9 px from 0.5× to 4×), so the budget is a cost | 645,120 |
| Font | 13 px (1.37 × 9.5 px) | 13 px (1.36 × 9.5 px) | 13 px |
| Arrowheads | 10 px | 10 px | 10 px |
| Lines | 1 px | **2 px** | 1 px |
| Modules | 25 shapes | **36 shapes** (the most tested) | 25 shapes |
| The image's place | First (79% each way) | First (78% first, 83% after the text: +5 points, but within twice the standard error of 3) | First |

**The pixel budget:**
- **Qwen3-VL's reading** doesn't change with the image's size: the native-resolution branch of
  the budget rule, on a real model for the first time.
- **gemma-4's** grows beyond the budget, as before.
- **Both read whole codes from about 9.5 px.** The eye chart study had about 6 px for Qwen3-VL,
  in cap height and a different font. In cap height, ours is about 6.9 px. Our scoring also
  counts a code as read only when every character is right.

**Arrows:** 44 arrows per size.

| Arrowhead | Line | gemma-4 right | gemma-4 reversed | Qwen3-VL right | Qwen3-VL reversed |
|---|---|---|---|---|---|
| 6 px | 1 px | 82% | 14% | 86% | 9% |
| 6 px | 2 px | 73% | 27% | 89% | 7% |
| 10 px | 1 px | 95% | 5% | 86% | 2% |
| 10 px | 2 px | 89% | 11% | 95% | 2% |
| 14 px | 1 px | 100% | 0% | 89% | 0% |
| 14 px | 2 px | 95% | 5% | 89% | 0% |

- **The two models fail differently:**
  - gemma-4 reverses arrows: it reads a vertical arrow top to bottom, whatever its head says.
  - Qwen3-VL hardly reverses any once heads are 10 px or more. It misses connections instead,
    more of them with 1 px lines.
- **The calibrations follow:** gemma-4 keeps 1 px lines, Qwen3-VL gets 2 px.
- **Both are at the rule's edge:** 42 of 44 for gemma-4's 10 px heads and 1 px lines, and for
  Qwen3-VL's 10 px and 2 px. 14 px heads read all 44 for gemma-4.

**Density:** connections found, either way round, and the right way round.

| Shapes | gemma-4 found | gemma-4 right way round | Qwen3-VL found | Qwen3-VL right way round |
|---|---|---|---|---|
| 9 | 100% | 82% | 100% | 100% |
| 16 | 97% | 84% | 95% | 89% |
| 25 | 93% | 72% | 95% | 67% |
| 36 | 86% | 57% | 91% | 56% |

- **Finding connections:** Qwen3-VL still finds 91% among 36 shapes, so it gets modules of 36.
- **Directions:** its direction reading falls as fast as gemma-4's among many shapes (56% at
  36). The module size is judged on connections found, since a description gets every
  connection's direction as text. A larger module trades direction reading for fewer,
  broader requests.

## Validation on the tree's own sketches

12 sketches each, drawn at each model's sizes:
- **Sources:** four projects were parsed for the sample (TMT, Library, SAF_Profile and
  SAF_SCM_Profile). The sketches came from TMT (10) and Library (2): the SAF profiles have few
  diagrams to offer.
- **Small:** 4 diagrams of up to 9 shapes.
- **Medium:** 4 diagrams from 10 shapes up to the module size (25 for gemma-4, 36 for
  Qwen3-VL).
- **Modules:** 4 modules of large diagrams.

A first sample took all 12 from TMT. Projects now take turns within each diagram type.

| Sample | gemma-4: names, connections, directions | Qwen3-VL: names, connections, directions |
|---|---|---|
| Small diagrams | 100%, 100%, 100% | 95%, 100%, 100% |
| Medium diagrams | 100%, 62%, 92% | 97%, 73%, 100% |
| Modules of large diagrams | 96%, 82%, 89% | 98%, 91%, 96% |
| All | 99%, 73%, 91% | 97%, 82%, 98% |

- **Names:** both models read the tree's names almost entirely at 13 px. Qwen3-VL's misses:
  - one user interface diagram (`ui`, 0%);
  - one internal block diagram (67%).
- **Connections:** both miss a fifth to a third of them in medium diagrams, and gemma-4 also
  in modules. So `run` warns of them.
- **Directions:** better on real sketches than on the cards (91% and 98%). Real diagrams have
  fewer connections per shape than the density cards.

**Two sketches account for most of the misses,** for both models. In each, the picture
itself is ambiguous:
- **A generalization trunk** (TMT, "Duration Analysis3", a block definition diagram):
  - six generalizations join one trunk line, which ends near the bottom of the container, well
    away from the parent's box;
  - the sketch doesn't show where they go, so neither model can recover them from the image
    (gemma-4 25%, Qwen3-VL 42%).
- **Association classes and nesting** (Library, "InterfaceStandards", module M4):
  - an association class drawn as a box on its association's line reads as a shape that the
    connection passes through: 19–24 and 23–24 for the truth's 19–23;
  - shapes nested in a container read as connected to it: 14–12, 14–19 and so on.

  Both models found 33%.

These are weaknesses of the sketches, not of either model. Validation found them on its first
real run. Descriptions still get these connections as text.

## What this means

- **Calibration adapts to the model, as intended.** The same tree, at the same sizes, would
  draw:
  - for gemma-4: 1 px lines and modules of 25;
  - for Qwen3-VL: 2 px lines and modules of 36.

  Switching models redraws the sketches (3,669 here) and asks again for their descriptions. The
  command says so.
- **Expected quality, for either model:**
  - names nearly always read;
  - connections in medium diagrams and modules 62–91% found from the image alone;
  - directions 89–100% right.

  Descriptions also get the names and connections as text, so these are lower bounds on what
  the image contributes, not on the descriptions.
- **gemma-4's calibration is unchanged** from plan VC's second run, so its defaults stand.

## Follow-ups

- **Ambiguous sketches (rendering):**
  - Generalizations, and other connections drawn through a shared trunk, should visibly reach
    their parent: a head at the parent, or a trunk that ends on it.
  - An association class could be drawn apart from its line, joined to it by a dashed line, as
    UML does.

  Validation will show whether a change helps.
- **A margin for the arrows' rule:** 10 px heads pass at exactly 95% for both models. Unlike
  the font's rule, the arrows' rule has no margin.
- **Direction in large modules:** whether modules of 36 should yield to direction reading,
  if spot checks of descriptions show directions contradicted.
