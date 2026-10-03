# Plan: calibrating to the configured vision model, and validating on real sketches, 2026-10-03

- **Status:** Approved on 2026-10-03, with three decisions:
  - **Low validation scores:** "warn and carry on";
  - **The second model:** Qwen3-VL, "seems good";
  - **The fallbacks:** "treat the gemma-4 figures as our new uncalibrated defaults for now,
    rather than reverting".
- **Step prefix:** `VA`, so steps are `VA-01`, `VA-02` and so on
- **Addresses:** the maintainer's correction of 2026-10-03:

  > "we must not assume gemma-4 is always our target model. Ideally, we can automatically
  > calibrate to the vision model we've configured, then perform some sketches and validation
  > tests so we know what quality to expect from the real ingestion."

  Plan VC built the measurement (`calibrate-vision`), but as a manual step whose results a
  maintainer applies to a tree. Calibration should instead be how a configurable pipeline adapts
  to whichever model it is given.
- **Builds on:** plan VC as completed in 0.12.0. That provides:
  - eye charts, scoring and recommendations, from the measurements alone;
  - two stages: reading, then arrows and density;
  - sketch sizes as options;
  - gemma-4's figures as the uncalibrated defaults.

  The maintainer judged VC a better foundation than changing course while it was half done.

## What is assumed of gemma-4 today

| Assumption | Where | Measured by this plan |
|---|---|---|
| A pixel budget of 645,120 px (gemma-4's 280 soft tokens at DeepInfra) | `config.IMAGE_PIXELS` | Yes: reading at 0.5–4× a starting budget |
| Image sides in whole 48 px patches | `vision.PATCH_PX` | No. It does little harm for other models: it rounds sides by at most 47 px |
| Sketch sizes: font, arrowheads, lines | `config.SKETCH` | Yes (plan VC) |
| Modules of at most 25 shapes | `config.MODULES` | Yes (plan VC) |
| The image before the text in every vision request (Google's advice for gemma) | `Template.image_first` | Yes, new: some cards asked both ways |

## Design

**Three tiers of sketch settings.** For each project, an explicit setting wins over the
calibration, and the calibration over the fallbacks:

| Tier | What | When |
|---|---|---|
| Explicit | `--image-pixels`, `--diagram-modules`, `--sketch-*-px` given by the maintainer | Always wins; the report marks it as an override |
| Calibrated | The configured vision model's calibration, kept in the tree | Any run with a vision model and rendering on |
| Fallback | gemma-4's figures at DeepInfra, for now (the maintainer's decision): 645,120 px, 13 px text, 10 px heads, 1 px lines, modules of 25 | Without a vision model (sketches for people only), or with `--no-calibrate` |

- **The fallbacks:** plan VC's uncalibrated defaults (0.12.0), unchanged. Their values are
  gemma-4's, but no run takes them as the configured model's calibration.

**Automatic calibration.**
- **The record:** calibrations are kept in the state database, in a new table `calibrations`,
  keyed by endpoint, vision model and the suite's version. Each keeps:
  - the chosen settings;
  - the summary;
  - the date;
  - the path of its report, `calibration/<model>-<date>/`.
- **When it runs:** `run` with a vision model and rendering on calibrates first when the tree
  has no record for that model. It runs after the endpoint check and before any project is
  built, with its own progress phases.
- **Its cost:** about 80 requests, a few minutes. On DeepInfra that is cents; it may be more
  on a slow local model, and the run says so as it starts.
- **Reruns cost nothing:** the answers are in the LLM store, so a rerun or a second tree with
  the same model and cache asks nothing.
- **Switches:**
  - `--no-calibrate` uses the fallbacks.
  - `calibrate-vision` recalibrates on demand, for instance after a host changes its limits.
    `--apply` is retired: the record is what runs use.
- **A new model:** a new record, new options, and the projects rebuilt. Their descriptions
  change with the model in any case.

**What calibration measures,** in addition to plan VC:
- **The image's place:** a dozen cards (reading near the threshold, and arrows at the chosen
  size) are asked again with the image after the text. If the text-first order scores clearly
  better (by more than the noise between seeds), the model's requests put the image last.
  `image_first` becomes an option of the model, not a constant of the templates.
- **The budget's range:** reading at 0.5–4× the starting budget finds a host's own budget
  within that range. Beyond it, the report says "at least 4×" or "at most half", and the
  nearest end is used.

**Validation on real sketches** ("so we know what quality to expect"):
- **The sample:** right after calibration, up to 12 diagrams from the tree's own scanned
  projects, a few parsed for the purpose.
  - It is spread by size: small (up to 9 shapes), medium (10–25), and modules of large ones.
  - It includes the diagram kinds the tree holds most of.
- **The question:** each is drawn at the calibrated sizes, and the model is asked from the
  image alone for:
  - each shape's number and label;
  - the connections, from number to number.
- **The truth:** the diagram's own legend and connections (`DiagramGraph`), scored as the cards
  are.
- **The report,** `validation.md` beside the calibration's, with expected quality by size:
  - labels read;
  - connections found;
  - directions right.

  `run` prints a one-line summary before building, and `status` shows it.
- **Low scores:** a warning naming what will suffer, for example "connections in medium
  diagrams: 71% found; their descriptions may misplace them". The run carries on.
- **How it relates to descriptions:** this measures what the model can see. Descriptions also
  get every label and connection as text, so they should do better than this. A judged check
  of descriptions themselves is a possible later step, not part of this plan.

## Steps

| Step | What | Status |
|---|---|---|
| VA-01 | **The tiers' wording:** the help, config and README describe the three tiers once automatic calibration exists (VA-03); until then, VC's wording stands. | |
| VA-02 | **The calibration record:** the `calibrations` table (schema 3, added in place), written by `calibrate-vision`.<br>**Precedence:** explicit settings, then the record, then the fallbacks, in `ProjectOptions.of`.<br>**Tests:**<br>- a record's sizes reach the projects' options;<br>- an explicit flag wins;<br>- a schema 2 tree migrates. | Done: `calibrate-vision` records; `--apply` retired; runs use the record |
| VA-03 | **Automatic calibration in `run`:** before building, for a vision model with no record; `--no-calibrate`; progress and the cost note; `status` names the model's calibration.<br>**Tests,** with fake models:<br>- a host with half the budget gets half the budget and a larger font, untouched by hand;<br>- a second model in the same tree gets its own record, and its projects rebuild;<br>- a rerun asks nothing. | |
| VA-04 | **The image's place:** the both-ways cards, the choice and `image_first` as an option per model, through `EnrichmentSession.ask`.<br>**Tests:** a fake model that reads only with the text first gets text first; ties keep image first. | |
| VA-05 | **Validation on real sketches:** the sample, the prompt (outside `CURRENT`), scoring against `DiagramGraph`, `validation.md`, and the summary in `run` and `status`.<br>**Tests:**<br>- a perfect reader scores 100% on the fixture's and the fiction's diagrams;<br>- a reader that drops every third label is reported at about 67%, with the warning. | |
| VA-06 | **Docs and version:** the README's calibration section rewritten around automatic calibration and the tiers; 0.13.0. A `--no-llm` tree is the same as 0.12.0's (`treediff`). | |
| VA-07 | **Live check, two models:**<br>- gemma-4 at DeepInfra: the eye charts from the store, the validation new;<br>- a model that reads at native resolution, Qwen3-VL at DeepInfra, if offered: a full calibration and validation, which exercises the other branch of the budget rule.<br>**Results:** a research note comparing the two calibrations and their expected quality. A few cents. | |

## Checkpoints

| Checkpoint | Steps | Output |
|---|---|---|
| CP1: tiers | VA-01, VA-02 | Fallbacks, the record, precedence |
| CP2: automatic | VA-03, VA-04 | `run` calibrates the configured model |
| CP3: validation | VA-05, VA-06 | Expected quality on real sketches; 0.13.0 |
| CP4: two models | VA-07 | The research note |

## When to stop and ask

- **Unreadable replies:** a second model's replies to the cards or the validation are mostly
  unreadable, so that the prompts need rework for it.
- **Image order:** it matters for gemma-4 itself (text first scoring clearly better), which
  would change every description's request layout.
