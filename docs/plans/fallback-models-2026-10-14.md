# Plan: fallback models, and subjects robust to a failed request

- **Status:** CP1 done (0.31.4), CP2 (0.31.5); CP3 under way.
- **Prefix:** `FM`. Steps are `FM-01` and so on.
- **From:** the maintainer, 2026-10-14:

  > "When building the model, I often have a few hold-out queries that always time out regardless
  > of how often I ask. This leads to some fragility. It might be worthwhile to support a list of
  > models (both vision and text) as fallbacks, albeit at the cost of some extra calibration.
  > Also, when partitioning subjects, on any timeout it's reported something about "LLM's ways"
  > failing and sorting by subject first. It isn't clear whether this is a fragile failure or just
  > local to a specific decision branch, but I'd like to ensure the model and reports are robust
  > to the occasional timeout."

## What a failed request costs today

Traced in the code (0.31.3):

- **An item's description** (`EnrichmentSession._complete`): the item is left without text, and
  its project is built again by the next run (RN-006, RN-007), which asks the same model again.
  A request that fails every time fails every run.
- **The breaker:** 3 consecutive failures switch enrichment off for the rest of the run. With
  `concurrency` 8, the few requests that always fail can be in flight together and fail one after
  another: three hold-outs in a row turn off every description after them. This is the most
  fragile point, and the maintainer's "a few hold-out queries" can trip it.
- **A family's subjects** (`subjects.ways_for`, `entry`): one proposal request, then one request
  per batch of 30 diagrams per way (3 ways).
  - The proposal fails: the family has no LLM ways this run ("failed"), shared elements first.
  - One assignment fails: its 30 diagrams are unsorted in that one way. But `entry` takes the
    worst way: past 5% unsorted, shared elements become the default for the whole family, though
    the other two ways are complete. One timeout demotes the family, and the topics across models
    change with it (they are built from the families' default views).
  - The warning, "the LLM's ways failed; X is shown first until a run completes them", doesn't
    say how many requests failed, which way, or how many diagrams.
- **Topics across models:** the same, with one way.

So the maintainer's reading is right on both counts: a single failure is local in the data
(one way's batch) but global in its effect (the family's default, the topics), and the report
doesn't say which.

## Decisions

### FM-D1: what a fallback is

- *A list of models per kind, tried in order for each request (chosen):* the request goes to the
  first model; on a failure, an empty answer, or an answer the caller can't use (JSON it can't
  read), to the next. Pros: the hold-outs get an answer; the first model answers everything else.
  Cons: one more failure path to test; the provenance must name the model that answered.
- *Switch the whole run to the next model after failures:* simpler; but a few hold-outs would
  move every later request to the second model, though the first answers them well.
- *Retry the same model later in the run:* cheap; but the maintainer's hold-outs fail "regardless
  of how often I ask", and the client already retries a timeout before the first word.

### FM-D2: where the fallbacks are set

- *`text-model` and `vision-model` take a list, "A, B", in order (chosen):* one setting per kind;
  `config show` shows the order; `vision-model` unset still means "as the text model(s)". Cons: a
  setting whose value is a list (no model id holds a comma at the endpoints we know).
- *Separate settings, `text-fallbacks` and `vision-fallbacks`:* explicit; but two more settings,
  and the default of `vision-fallbacks` when `vision-model` is unset is hard to say.
- *One `fallback-models` list for both kinds:* fewer settings; but a vision fallback must read
  images, and a text model may not: the kinds differ.

### FM-D3: whose calibration draws the sketches and cuts the parts

Each model in each list is calibrated, as the first is today (the "extra calibration" the
maintainer expects): vision models with the standard suite and the validation, text models with
the part-size guard. The question is which calibration sets the sizes:

- *The first model's (chosen):* the sketches and parts are what the first model reads best, and it
  answers nearly everything. A fallback reads them as they are; its own calibration gives it its
  image order, its validation says how well it reads the tree's sketches, and a warning says when
  it calls for larger sketches or smaller parts than it gets. Cons: a weaker fallback may misread
  some of the few items it answers.
- *The most demanding of the list:* every model reads every sketch well; but adding a fallback
  would redraw every sketch, in more modules, for the sake of a few requests.
- *Each model's own:* each request at its model's sizes; but the modules a large diagram is cut
  into depend on the sizes, so the output's structure would depend on which model answered.
  Rejected.

### FM-D4: the breaker

- *Per model, tripping after `3 + concurrency - 1` consecutive failures (chosen):* requests in
  flight together share a fate, so a breaker that counts them separately trips on one bad moment.
  Per model, a broken first model sends the rest to the fallback at once, without each request
  waiting out its timeout. Enrichment is off when every model of a kind is.
- *Count only errors that mean the endpoint is unusable (connection, authentication, unknown
  model):* precise when the errors say so; but a hanging endpoint shows only timeouts.
- *As now:* convenient, and the fragility above.

### FM-D5: a family's default view

- *The first LLM way with at most 5% unsorted (chosen):* a failed batch costs its way, not the
  family; the fallback is first only when no way is complete enough. The record's status is
  `incomplete` while any diagram is unsorted, so the next run asks again for those.
- *As now (the worst way decides):* simple, and fragile as above.

### FM-D6: stored answers along the list

A request answered by the second model is stored under that model. On a later build of the
project, the store is searched along the list before any model is asked, so the first model isn't
asked again for what it couldn't answer (each run would wait out its timeout again). If the list
changes, the requests follow the new list.

## Checkpoints

### CP1: subjects and topics robust to a failed request (FM-01 to FM-03)

- **FM-01:** `subjects.entry` takes, as the default, the first LLM way with at most
  `UNSORTED_LIMIT` unsorted; shared elements go first only when there is none. `topics.entry` is
  unchanged in kind (one way), but FM-02's counts reach it. Check: a test where one batch of one
  way fails: the family's default is still an LLM way, its status `incomplete`, the next run asks
  only the failed batch.
- **FM-02:** `ways_for` (and `topics.llm_view`) count the requests that failed: the proposal, or
  each way's batches, with the diagrams they leave unsorted, into the record (`failed`:
  `{"proposal": bool, "batches": n, "unsorted": n}`), for the warnings and `status`.
- **FM-03:** the warnings say what happened and what it costs, one line per family:
  - "subjects of X: 1 of 10 requests failed (way 2 leaves 30 of 88 diagrams unsorted); way 1 is
    shown first; the next run asks again for the 30";
  - "subjects of X: the proposal failed, so shared elements are shown first; the next run asks
    again";
  - `status`: the same lines, under its subjects line.
- Commit; 0.31.4.
- **Done:** `subjects.entry` (the first way within the limit, moved first), `ways_for` and
  `topics.llm_view` (`requests` per LLM view), `subjects.problem` and `topics.problem` (the log,
  and `status` under its subjects line, one line each). ADR-0031, design/subjects. Tests:
  `test_subjects_and_their_fallbacks` (one batch lost: "By activity" shown first, no shared view,
  the line), `test_a_run_writes_subjects` (`status`), `test_the_llms_topics_and_its_failures`.

### CP2: the breaker per model (FM-04)

- **FM-04:** `EnrichmentSession` keeps consecutive failures per model; a model is off for the
  rest of the run after `MAX_CONSECUTIVE_FAILURES + concurrency - 1`; a request whose models are
  all off is `skipped_disabled`. `run.json`'s `disabled_after_failures` lists the models.
  `concurrency` reaches the session from the runner. Check: tests at concurrency 1 (unchanged:
  3) and 8 (10); a success resets the count.
- Commit.
- **Done:** `EnrichmentSession.off`, `_failures` per model, `breaker`; `LLMConfig.concurrency`
  from the setting (`session.llm_config`), rather than from the runner, so calibrations count
  the same way. `run.json`'s `disabled_after_failures` lists the models. Test:
  `test_the_breaker_is_per_model_and_counts_requests_in_flight`.

### CP3: fallback models (FM-05 to FM-09)

- **FM-05:** `config.parse_setting` reads `text-model` and `vision-model` as a list, "A, B" (no
  empty or repeated names); `LLMConfig` keeps `text_model` and `vision_model` (the first) and
  gains `text_models` and `vision_models` (the lists); `session.llm_config` fills them.
- **FM-06:** `EnrichmentSession.ask` builds the request per model (the image order is per model),
  looks in the store along the list (FM-D6), then asks each model that isn't off, in order, until
  one answers; `accept(text) -> bool` lets a caller refuse an answer it can't use (the four JSON
  templates of subjects and topics). Outcomes gain `fallback` (an item answered by a model after
  the first). `Derivation.model` is the model that answered; subjects' and topics' views record
  the models that answered them.
- **FM-07:** `ProjectOptions` gains the lists (and each fallback's image order), so a change of
  list builds the projects again (from stored answers).
- **FM-08:** `preflight`, `config test` and `config models` cover every model of both lists.
- **FM-09:** tests: a hold-out answered by the fallback; stored, and not asked of the first model
  on the next build; JSON refused by the first and accepted from the second; provenance and
  `run.json`.
- Commit.

### CP4: calibrating the fallbacks (FM-10 to FM-11)

- **FM-10:** `calibration_for_run` calibrates every model in each list (calibrations and
  validations are of one model: `EnrichmentSession.only(model)` for their duration); the first
  model's sizes draw and cut (FM-D3); each fallback's image order reaches the session; a warning
  when a fallback's calibration calls for larger sketches or smaller parts than the first's.
  `calibrate-vision` and `calibrate-text` take `--model NAME` (default: the first), so a fallback
  can be calibrated again on demand.
- **FM-11:** tests with fake models: two vision models, each calibrated once; the run's sizes are
  the first's; the warning.
- Commit.

### CP5: close

- README (settings, the breaker, fallbacks), design/llm-enrichment, design/vision-calibration,
  ADR-0030 (the settings' lists), a new ADR for fallback models (FM-D1, D3, D4, D6), roadmap;
  the plan archived. Suite in a fresh venv and the live tests; release 0.32.0.
