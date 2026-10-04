# Plan: inputs cut by us, and calibrating to the configured text model, 2026-10-04

- **Status:** Active. CP1 done (0.15.3); CP2 in progress.
- **Step prefix:** `TC`, so steps are `TC-01`, `TC-02` and so on.
- **Addresses:** the maintainer, 2026-10-04, on the roadmap's chunk splitting:

  > "As for cutting inputs, that seems like something we might be wise to detect via
  > calibration, and do some cutting ourselves if needed."

  The maintainer then said "Please proceed" to splitting first, as its own step, with
  calibration following as a plan in checkpoints, like plan VA.
- **Builds on:**
  - plan DV's parts (`docs/archive/plans/diagram-views-2026-09-30.md`);
  - the sandwiching study (`docs/research/sandwiching-2026-09-30.md`);
  - plan VA's calibration record and its hook in `run` (ADR-0015).

## What is assumed of the text model today

| Assumption | Where | Measured by this plan |
|---|---|---|
| A package of up to 12,000 characters is read evenly in one request | `prompts.SUMMARY_CHARS` | Yes (CP2) |
| A large package's parts are 3,000 to 12,000 characters | `prompts.PART_CHARS` | The upper bound (CP2). The lower is "the smallest worth its own request", not a reading limit |
| A section longer than a part may be cut | `prompt_values.module_summary` | Replaced: never cut (CP1) |
| At most 150 shapes and connections per diagram request | `prompts.DIAGRAM_ITEMS` | Later, if CP2's measure suits it |
| Instance digests of 8,000 and 4,000 characters | `prompts.DIGEST_CHARS` | Later, likewise |

**The evidence so far,** for gemma-4 at DeepInfra:
- at 12,000 characters (about 3,000 tokens), a part's start, middle and end are read evenly: 87%,
  86% and 86% of names mentioned;
- in one request of more than 100,000 characters, the middle is lost: 13% of the names mentioned
  come from the middle third, against 21% in parts.

Between the two, nothing was measured.

## Steps

| Step | What | Status |
|---|---|---|
| TC-01 | **Split, don't cut:** `enrich.repack` keeps a part that fits as it is. Otherwise it packs the part's sections, in order, into as few requests as fit. A section too long for one request goes in pieces (`enrich.pieces`), cut between lines, or between words in a longer line. Each piece is headed by the section's title and "(piece i of n)", and each request is a part of its own. The page lists each part's elements, so a split section appears in several parts.<br>**Tests:**<br>- every character of the section, in order, within the limit;<br>- a run with a 34,000-character section: no `truncated_input`, every sentence sent once;<br>- the replay fixture recorded again, now with nothing cut. | Done (0.15.3) |
| TC-02 | **The release check:** the whole tree rebuilt from 0.15.2's store; the requests that change; the invariants; retrieval compared (`scripts/compare_retrieval.py`). Version 0.15.3. | Done: 546 new requests (517 parts, renumbered where a section was split, 16 of them pieces; 29 syntheses), none failed, none cut; the invariants hold; retrieval identical to 0.15.2's for every system |
| TC-03 | **Reading cards,** in `textcal.py`, the counterpart of `eyechart.py`:<br>- synthetic package text in the format of real parts (`Section.text`): invented blocks, requirements and activities, with documentation, attributes and relationships;<br>- every name and figure invented and unique, so that a mention is an exact match, as in the fictional projects;<br>- lengths of 6,000, 12,000, 24,000, 48,000 and 96,000 characters;<br>- six cards per length, from fixed seeds.<br>**Two probes on each card:**<br>- **summary:** the real `module-summary` template, scored by the names it mentions in each fifth of the input;<br>- **facts:** five questions about facts planted in different fifths, in a calibration-only template, scored right or wrong.<br>**Tests:** the cards are deterministic, and the scoring is exact on canned answers. | |
| TC-04 | **The measurement,** with gemma-4 and DeepSeek-V3.2, both on DeepInfra: about 60 requests a probe, roughly 280,000 input tokens a model. A research note: by length, the share of names from each fifth, facts found by position, and how the two probes agree. | |
| TC-05 | **The rule,** drafted from TC-04: the longest length still read evenly, with a margin such as plan VA's `FLAT`, and which probe decides. | |

## Checkpoints

| Checkpoint | Steps | Delivers |
|---|---|---|
| CP1: nothing cut | TC-01, TC-02 | 0.15.3: every section's text reaches the model |
| CP2: the measurement | TC-03 to TC-05 | The research note and a proposed rule. **Then stop for the maintainer's review** |
| CP3: calibration in `run` | Expanded after CP2 | As for vision: explicit setting, then the calibration record (per text model and endpoint), then the uncalibrated defaults. The part size is in each project's options, so a change rebuilds. `status` lists it |
| CP4: the release check | Expanded after CP2 | A second model's calibration; an ADR; the design docs; a version |

## Results

**CP1 (2026-10-04):**
- **The release check:** the whole tree rebuilt from 0.15.2's store in 23 minutes.
  - 546 new requests: 517 parts and 29 syntheses. A package with a split section has more parts,
    so all its parts' "k of n" changed; 16 of the new requests are pieces.
  - None failed, and the run reported no cut input (0.15.2's had 14).
  - The invariants hold, and retrieval on the 210 fictional questions is identical to 0.15.2's.
- **The pieces read well:** the drone's "Perform Delivery Operations", in two pieces, is
  summarized from both. One answer of 16 repeats the marker "(piece 2 of 2)" as if it were part of
  a name. Rewording the marker would change those requests again; noted, not changed.

## When to stop and ask

- **After CP2,** before calibration changes what runs do.
- **If gemma-4 reads evenly far beyond 12,000 characters,** calibration would make parts larger.
  Larger parts mean fewer requests and fewer levels of synthesis, but coarser part summaries:
  that is a choice about output, not only about reading.
- **If the two probes disagree** about where reading sags.
