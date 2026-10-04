# Plan: inputs cut by us, and calibrating to the configured text model, 2026-10-04

- **Status:** Active. CP1 done (0.15.3); CP2 done. The maintainer chose, on 2026-10-04, calibration
  as a guard ("A is fine"): the part size stays 12,000 characters by default, and calibration only
  shrinks it, for a model that reads 12,000 unevenly or an endpoint that cuts inputs. CP3
  done (0.16.0); CP4 in progress.
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
| TC-03 | **Reading cards,** in `textcal.py`, the counterpart of `eyechart.py`:<br>- synthetic package text in the format of real parts (`Section.text`): invented blocks, requirements and activities, with documentation, attributes and relationships;<br>- every name and figure invented and unique, so that a mention is an exact match, as in the fictional projects;<br>- lengths of 6,000, 12,000, 24,000, 48,000 and 96,000 characters;<br>- six cards per length, from fixed seeds.<br>**Two probes on each card:**<br>- **summary:** the real `module-summary` template, scored by the names it mentions in each fifth of the input;<br>- **facts:** five questions about facts planted in different fifths, in a calibration-only template, scored right or wrong.<br>**Tests:** the cards are deterministic, and the scoring is exact on canned answers. | Done, revised once: the first cards' elements were all alike, and a right summary of them names examples from the start. Cards now hold five groups, each with a hub of its own purpose, one a fifth; scored by groups covered. 8 cards a length, up to 192,000 characters |
| TC-04 | **The measurement,** with gemma-4 and DeepSeek-V3.2, both on DeepInfra: about 60 requests a probe, roughly 280,000 input tokens a model. A research note: by length, the share of names from each fifth, facts found by position, and how the two probes agree. | Done: `docs/research/text-reading-2026-10-04.md`. Neither model loses its place on these cards up to 192,000 characters, and the probes agree; but the cards are easier than real packages, which lost their middle above 100,000 in one request |
| TC-05 | **The rule** (decided: a guard). Cards of 6,000, 12,000 and 24,000 characters, 5 of each, both probes: 30 requests. A length passes when at least 90% of groups are covered and 90% of facts are right, and no fifth falls below 60% in either probe (a fifth lost is an input cut short). The part size is 12,000 when 12,000 passes, else 6,000; when 6,000 fails too, 6,000 with a warning. 24,000 is reported, never used: calibration doesn't make parts larger. | Decided |
| TC-06 | **The part size as an option:** the setting `part_chars` and `--part-chars N`. An explicit setting wins, then the text model's calibration, then 12,000. It sets the part's limit, and the size of a package summarized in one request (both 12,000 today). It is in each project's options, so every project's options hash changes once, and the tree rebuilds from the store. The prompts' slot descriptions say so, and no longer say that a long section is cut.<br>**Tests:** a smaller part size gives more parts; an explicit setting wins over a record. | Done: `part_chars` in settings and options, `--part-chars`; the enricher, the partition and the guard on parts take it; slot descriptions corrected |
| TC-07 | **The calibration record:** schema 4 gives `calibrations` a `kind`, `vision` or `text`, in its key, since one model can be both (gemma-4 is). A tree of schema 3 is migrated in place.<br>**Tests:** a schema 3 tree migrates and keeps its vision record; a model's text and vision records coexist. | Done: schema 4, `kind` in the key; schema 3 trees rebuilt in place, their records kept as `vision` |
| TC-08 | **Calibration in `run`:** in the hook where the vision model is calibrated, a text model with no record is calibrated first: about 30 requests, once per model and endpoint; the report is `calibration/<model>-text-<date>/report.md`. `--no-calibrate` skips both. An incomplete calibration isn't recorded, and the run uses the default with a warning. `status` lists both kinds.<br>**Tests,** with fake models: a model that reads well keeps 12,000; one that loses the end of 12,000-character cards gets 6,000, and its projects rebuild; a rerun asks nothing. | Done: `textcal.calibrate_text` in the run's hook, before the vision model's; `status` names each record's kind; tests with a model reading 9,000 characters of each input (it gets 6,000) and one reading all (12,000) |
| TC-09 | **The release check:** the tree rebuilt (its options hash changes); gemma-4 calibrated; the invariants; retrieval compared. An ADR; the design docs and README; 0.16.0. | |

## Checkpoints

| Checkpoint | Steps | Delivers |
|---|---|---|
| CP1: nothing cut | TC-01, TC-02 | 0.15.3: every section's text reaches the model |
| CP2: the measurement | TC-03 to TC-05 | The research note and a proposed rule. **Then stop for the maintainer's review** |
| CP3: calibration in `run` | TC-06 to TC-08 | The part size as an option, guarded per text model |
| CP4: the release check | TC-09 | 0.16.0 |

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

**CP2 (2026-10-04):** `docs/research/text-reading-2026-10-04.md`.
- **On the reading cards,** gemma-4 and DeepSeek-V3.2 cover every group, and find almost every
  planted figure, at every length up to 192,000 characters: 16 times today's part.
- **The cards are easier than real packages.** In real packages of over 100,000 characters,
  gemma-4 lost the middle in one request (the sandwiching study). Real packages are long
  unmarked lists, and the failure is in choosing what matters, which these cards don't test.
- **So the measure saturates for strong models.** It can't say how large their parts may grow.
  It can catch a model that reads worse, or a context window or endpoint that cuts inputs.
- **The part size is also a choice about the summaries.** At 12,000 characters gemma-4's part
  summaries name 94% of the elements; at 48,000, 15%.

## When to stop and ask

- **After CP2,** before calibration changes what runs do.
- **If gemma-4 reads evenly far beyond 12,000 characters,** calibration would make parts larger.
  Larger parts mean fewer requests and fewer levels of synthesis, but coarser part summaries:
  that is a choice about output, not only about reading.
- **If the two probes disagree** about where reading sags.
