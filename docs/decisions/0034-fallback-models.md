# ADR-0034: Fallback models: each kind's models in order, the first's calibration draws

- **Status:** Accepted, 2026-10-14 (plan FM).
- **Sources:** `docs/archive/plans/fallback-models-2026-10-14.md` (the options weighed); ADR-0015,
  ADR-0024, ADR-0030.

## Context

The maintainer, 2026-10-14: "When building the model, I often have a few hold-out queries that
always time out regardless of how often I ask. This leads to some fragility. It might be
worthwhile to support a list of models (both vision and text) as fallbacks, albeit at the cost of
some extra calibration."

A request that fails every time left its item without text on every run (RN-006, RN-007), and
three such hold-outs in flight together switched off every description after them.

## Decision

- **A list per kind,** in the existing settings: `text-model` and `vision-model` take "A, B", the
  first asked first (`config.parse_setting`, kind `models`; `LLMConfig.text_models`,
  `vision_models`). Rejected: separate fallback settings (two more, and an unclear default for
  the vision list), and one list for both kinds (a vision fallback must read images).
- **Per request, not per run:** a request goes to the next model when the one before fails,
  answers nothing, or answers what the caller can't use (`accept`: subjects' and topics' JSON).
  Rejected: switching the run to the next model after failures (a few hold-outs would move every
  request), and asking the same model again (the client already retries before the first word).
- **Stored answers along the list:** a later build takes B's stored answer without asking A
  again, so a hold-out costs its timeout once.
- **The first model's calibration draws the sketches and cuts the parts.** Every model is
  calibrated, alone; a fallback keeps its own image order, is validated on the first's sketches,
  and gets a warning when it reads best with larger sketches or smaller parts. Rejected: the most
  demanding calibration of the list (a fallback would redraw every sketch, in more modules, for a
  few requests), and each model's own sizes (a large diagram's modules depend on them, so the
  output's structure would depend on which model answered).
- **The breaker per model and kind of request,** after 3 consecutive failures plus one per other
  request in flight (`concurrency - 1`): requests sent together fail together when the endpoint
  does, and a model failing on images may read text well.
- **Provenance:** the derivation names the model that answered; `run.json` counts `fallback`;
  a subjects way names the model that proposed it, and `also` any other that assigned it.
- **The options record the fallbacks** (with each vision fallback's image order), so a change of
  list builds the projects again, from stored answers.

## Consequences

- A hold-out is answered, at the cost of one failure per run that builds its project for the
  first time; later builds take the stored answer.
- A weaker fallback answers its few items less well than the first would; the provenance says
  which items, and the validation how well it reads the tree's sketches.
- An endpoint that is down costs up to three failures per model and kind before it is off.
- More calibration: about 92 vision requests and 30 text requests per fallback, once per model
  and endpoint, from stored answers in any other tree.

## Changes
