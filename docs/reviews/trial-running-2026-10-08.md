# Review: running a tree, from the maintainer's trial of 2026-10-08

- **Status:** Open; remediation under way (plan below).
- **Prefix:** `RN`. Findings are `RN-001` and so on; remediation steps are `RN-001R1` and so on.
- **Subject:** 0.30.0, run by the maintainer on their own models: calibration, LLM requests,
  progress on a terminal, and `config`.
- **Method:** the maintainer's notes (quoted under each finding), traced in the code. RN-002's
  cause was reproduced on DeepInfra (gemma-4-31B-it): with a 4 s timeout, a request for 600 words
  failed at 4.2 s, while the same request streamed finished in 35.9 s, its first words after
  0.9 s. RN-003's display was reproduced in a terminal emulator (pyte, 100 x 20), before and after.
  RN-006 was found while tracing RN-002. The maintainer's models weren't available.

## Summary

| Finding | What | Kind | Priority |
|---|---|---|---|
| RN-001 | One unanswered eye chart throws away a calibration; unanswered cards count as misread | Bug | High: every run draws to the defaults |
| RN-002 | Slow answers time out: requests aren't streamed, and a reply cut short is lost | Bug | High: many items without text |
| RN-003 | A log line breaks the progress bars, which are drawn again below it | Display | Medium |
| RN-004 | The timeout can't be set | Feature | Medium; with RN-002 |
| RN-005 | `config -i` is documented but doesn't work; settings can't be exported or imported | Feature | Low, quick |
| RN-006 | An item left without text by a failed request is never asked for again | Bug | Medium: RN-002's losses stay |

## Findings

### RN-001: one unanswered card throws away a calibration

> "I'm getting a regular timeout on one of the 92 cards for vision calibration. But because
> there's even a single failure, one 'unasked' card, we're currently ignoring the 98% (91/92)
> cards that were asked. I edited that in-place mid-trial to bypass, but it should be fixed
> properly."

- **Where:** `calibrate.problem` refuses a calibration with any card unasked; `textcal.problem`
  likewise for any request unanswered.
- **Also:** `calibrate.summarize` counts an unasked card as read and wrong (score 0, no arrows
  found), so even a calibration let through would be biased low in the cards' groups.
- **Weighed:**
  - *Refuse on any gap (as now):* simple, but one slow card discards the rest, and the next run
    asks the same card again and fails again.
  - *Ask the unasked cards again at the end:* recovers a passing fault, but a card that always
    times out costs another timeout; RN-002 removes most of these anyway.
  - *Accept a few gaps, measured without them:* the measures are averages over groups of cards;
    a group that keeps most of its cards measures nearly as well. Needs a limit on how many.
  - Chosen: the last, with unasked cards left out of every measure. Limit: at most 5% of the
    requests unanswered (at least one), and every group measured keeps at least half its cards.
    92 cards may miss 4; the text calibration's 30 requests may miss 1.
- **Done:** R1. `calibrate.summarize` leaves unanswered cards out; `calibrate.thin`, `max_unasked`
  and `problem`; `textcal.problem`. Tests: `test_a_few_unanswered_cards_are_left_out` (one card
  timing out every time: recorded, as a perfect reader's; a group lost, or 8 of 92: not),
  `test_a_few_unanswered_requests_are_allowed`.

### RN-002: slow answers time out

> "I'm seeing a lot of timeouts that I think might not be true timeouts. Just very slow to produce
> the full output. We should support streaming outputs, and make use of a partial answer where
> feasible."

- **Where:** `llm.OpenAIChat.complete` asks without streaming, with a 120 s timeout. The OpenAI
  SDK makes it a read timeout: 120 s without a byte. Unstreamed, the endpoint sends nothing until
  the whole answer is written, so any answer that takes over 120 s to write fails, however fast
  the words come. Streamed, the words arrive as written, and the timeout is the longest wait
  between them (reproduced: 4.2 s failure, against 35.9 s success, above).
- **A reply cut short:** today a failure, whatever it held.
- **Weighed, for what a reply cut short becomes:**
  - *Always a failure:* simple, honest; wastes what was said, and a model that runs on (repeating
    itself, say) never gets an answer.
  - *Used as far as its last whole sentence, where the template's answer is prose:* the
    descriptions and summaries read well cut at a sentence; JSON answers (subjects, topics,
    calibration, judges) don't, and stay failures.
  - *Stored, or asked again next run:* an answer cut by the time limit is what the model says in
    the time allowed, and asking again costs the same time for much the same answer: stored,
    marked with the limit it was cut at, and asked again only when the limit is raised. An answer
    cut by a broken connection is not the model's answer: used for this run, not stored, and so
    asked again (RN-006).
  - Chosen: the second and third. The text says nothing of it; the item's provenance does
    (`derivation.partial`), and `run.json` counts them.
- **Done:** R1 and R2. `llm.OpenAIChat.complete` streams, retries a timeout before the first word,
  and raises `llm.Partial` (`time`, `output`, `broken`); `Template.partial` on the eight prose
  templates; `EnrichmentSession._complete` keeps a cut reply to `text.whole_sentences`, stores a
  limit's cut with its `partial` row (`ResponseStore.cut`), asks again under a longer limit, and
  never stores a broken one; outcomes `partial` and `broken_off`. Tests: `tests/test_streaming.py`
  (a fake stream: slow and steady is whole; a stall is retried, then fails; a broken reply, the
  time limit and the output limit say what they held; the session's three cases). The live tests
  pass on DeepInfra, streamed.

### RN-003: a log line breaks the progress bars

> "The tqdm heartbeats aren't quite what I imagined. Whenever there's another message, e.g. due
> to reporting a timeout, the bar is rebuilt. What I'd like for terminal use is something closer
> to pinning of the progress bar while having a rolling log separately."

- **Where:** the console's log handler and `print(..., file=sys.stderr)` write to stderr while
  tqdm's bars are on its last lines: the message lands on the bar's line, and the bar is drawn
  again under it (reproduced: each warning leaves a fragment of a bar).
- **Weighed:**
  - *tqdm's own pattern* (`tqdm.write`, as `tqdm.contrib.logging.logging_redirect_tqdm` uses):
    clears the bars, writes the line, draws the bars again below: the bars stay at the bottom,
    the log scrolls above. No new dependency; it covers logging only, so prints need the same.
  - *rich* (`Progress` with `RichHandler`): the same effect, nicer bars; a new dependency and a
    rewrite of `progress.py` and the console handler.
  - *enlighten:* pins bars with the terminal's scroll region; a new dependency, less common.
  - Chosen: tqdm's pattern, for logs and prints alike, through one stream that writes lines with
    `tqdm.write` (reproduced: the bars stay as the last lines, the messages above them).

### RN-004: the timeout can't be set

> "We should probably be able to configure timeouts."

- **Where:** `llm.TIMEOUT` (120 s) and `RETRIES` (2) are fixed since 0.21.0, when the old
  `--llm-timeout` flag was retired.
- **Weighed:** ADR-0027 keeps heuristics out of settings; a timeout isn't one: it depends on the
  endpoint, which the user knows. Two settings, since streaming separates them: `timeout`, the
  longest wait for the next words (the first included); `time-limit`, the longest a request may
  take, after which RN-002's rule applies. The old setting's stored name (`llm_timeout`) stays
  retired: what a tree remembers from 0.20 meant something else.
- **Done:** R1. `TreeSettings.request_timeout` and `request_time_limit`, set as `timeout` and
  `time-limit`; `session.llm_config` passes them; ADR-0030 updated.

### RN-005: `config -i`; exporting and importing settings

> "`cameo-ingest config -i` is mentioned but doesn't work - we should probably remove it,
> favoring set/unset for now. A config import/export to JSON would also be convenient."

- **Remedy:** `config -i` and `cli/interactive.py` go, and the README's mentions. `config export
  [FILE]` writes the tree's own settings as JSON (stdout without FILE), keyed as `config` names
  them; `config import FILE` sets each one, `null` unsets, and an unknown key or bad value saves
  nothing.
- **Done:** R1 and R2. `config.exported` and `imported` (format 1), `configure.import_settings`;
  `tests/test_cli.py::test_config_export_and_import`. ADR-0030 updated.

### RN-006: an item left without text is never asked for again

- **Where:** a project is `written` whatever its LLM requests did; `State.stale_contents` builds
  only projects missing, failed, or made with other options. An item whose request failed (a
  timeout, the call budget, enrichment switched off after 3 failures) stays without text until
  the options change.
- **Weighed:**
  - *A flag to ask again:* ADR-0027 and the maintainer's preference are against switches for
    what the tool can decide.
  - *The next run builds again the projects with such gaps:* answers are stored, so only the gaps
    are asked; the cost is the project's build. A request that always fails would rebuild its
    project every run: limited to 3 builds with gaps per project and options.
  - Chosen: the second.

## Remediation plan

Easiest first. Each step: tests, `uv run pytest`, lint, a commit naming its IDs.

- **RN-005R1:** remove `-i` (`cli/__init__.py`, `cli/configure.py`, `cli/interactive.py`), the
  README's mentions and `design/llm-enrichment.md`'s; tests that used it.
- **RN-005R2:** `config export [FILE]`, `config import FILE` (`cli/configure.py`, values through
  `config.parse_setting`); tests: a round trip between two trees, `null`, a bad key saving nothing.
- **RN-001R1:** `calibrate.summarize` leaves unasked cards out of every measure; `problem` accepts
  up to `MAX_UNASKED` (5%, at least 1) and needs half of each group; `textcal.problem` the same.
  Tests: one unasked card is recorded and doesn't move the thresholds; too many refuse.
- **RN-004R1 with RN-002R1:** `OpenAIChat.complete` streams; `timeout` (idle) and `time_limit`
  in `LLMConfig`, from the settings `timeout` and `time-limit` (defaults 120 s and 600 s); a reply
  cut short raises `llm.Partial(text, why)`; no words before a timeout are retried (`retries`).
  Tests with a fake stream: slow but steady succeeds, a stall times out, the limit cuts.
- **RN-002R2:** `Template.partial` for the prose templates; the session uses a partial reply to its
  last whole sentence (`text.whole_sentences`), stores a time-limit cut in a `partial` table of the
  store (asked again under a higher limit), never stores a broken one; `Derivation.partial`;
  `run.json` counts. Tests.
- **RN-003R1:** `progress.py` gives the console one stream that writes lines through `tqdm.write`
  while bars are shown, for the log handler and for `sys.stderr`; check in the emulator.
- **RN-006R1:** projects record their LLM gaps and builds with gaps; `stale_contents` includes
  those with gaps and fewer than 3 such builds, when the LLM is on. Tests.
- **Close:** design/llm-enrichment, design/vision-calibration, README, roadmap; release.
