# Repeating the task after long inputs ("sandwiching")

- **Date:** 2026-09-30
- **Asked by:** the maintainer, on FU-005: "We do have a fairly large context for gemma4 (262k
  tokens, IIRC), but I wouldn't count on equal quality for start and end of context, so we might
  also look into sandwiching techniques, e.g. repeat the short headers and prompts again at the
  end to focus attention and reasoning."
- **For:** plan step DV-06 in `docs/plans/diagram-views-2026-09-30.md`.
- **Model:** `google/gemma-4-31B-it` on DeepInfra.
- **Method:** two experiments on the drone sample, SAF_FFDS and TMT.
  - **Parts** (`scripts/sandwich_study.py`): 121 parts of large packages (all 12 of the
    drone's, all 49 of SAF_FFDS's, 60 of TMT's 1,480 drawn at random), each summarized with
    `module-summary@v1` (the task before the input only) and `@v2` (the task repeated after
    it). Then 25 packages were summarized from those part summaries, with
    `package-synthesis@v1` and `@v2`. Inputs are at most 12,000 characters, about 3,000
    tokens: the pipeline's part size.
  - **Whole packages** (`scripts/long_context_study.py`): each package summarized in one request
    with its whole text, with `package-summary@v2` and a sandwiched `@v3`, and as the pipeline
    does, in parts (DV-05). Two size bands: 18 packages of 30,000 to 400,000 characters
    (median 47,836), and 14 of TMT's 17 packages of 100,000 to 600,000 characters (median
    178,730, about 45,000 tokens).
- **Code:** both scripts, and the sandwiched templates (`module-summary@v2`,
  `package-synthesis@v2`, `package-summary@v3`), were retired on 2026-10-02 (plan RA-03); they
  are at tag `studies-2026-10-02`.
- **Measures:**
  - **Adherence:** answers over the word limit, with Markdown, or naming parts by number.
  - **Coverage:** which element names of the input an answer mentions, and from which third of
    the input they come. Attention lost in the middle of a long input shows as a dip in the
    middle third, relative to the other ways of asking.
  - **Blind reading:** 18 of the parts experiment's pairs, read without knowing which version
    wrote which (`pairs.md`), and the three whole-package answers side by side (`whole-blind.md`).

## Results

### Parts (inputs of at most 12,000 characters)

| Template | Items | Words (median) | Over limit | Markdown | Part numbers | Coverage: first third | Middle | Last |
|---|---|---|---|---|---|---|---|---|
| module-summary@v1 | 121 | 103 | 2 | 0 | 0 | 87% | 86% | 86% |
| module-summary@v2 (sandwiched) | 121 | 104 | 1 | 0 | 0 | 89% | 86% | 87% |
| package-synthesis@v1 | 25 | 162 | 0 | 0 | 0 | | | |
| package-synthesis@v2 (sandwiched) | 25 | 163 | 0 | 0 | 0 | | | |

No difference. Read blind, the pairs say the same things in slightly different words, and
neither version is better more often.

### Whole packages in one request

Share of the element names mentioned, by third of the package:

| Band | Way | Names mentioned (median) | First third | Middle | Last |
|---|---|---|---|---|---|
| 30,000 to 400,000 characters | one request | 14 | 45% | 26% | 29% |
| | one request, sandwiched | 14 | 46% | 27% | 27% |
| | in parts | 13 | 50% | 24% | 27% |
| 100,000 to 600,000 characters | one request | 8 | 58% | 13% | 29% |
| | one request, sandwiched | 10 | 63% | 13% | 24% |
| | in parts | 8 | 52% | 21% | 27% |

- **Every way favours the first third.** The first elements of a package are often its
  top-level ones, so part of the skew is in the content, not in the model.
- **Long inputs lose the middle.** Above 100,000 characters, one request draws 13% of its
  names from the middle third, where parts draw 21%.
- **Sandwiching doesn't restore it.** It pulls the answer further towards the start (63%) and
  away from the end (24%), and mentions a few more names in all.
- **Parts cover packages best where they are coherent.** In TMT's "TMT-APS Use Cases" (283,430
  characters), parts name 32 elements, against 17 in one request and 19 sandwiched. In
  "Migrated" (119,257) the counts are 27, 9 and 12.
- **The name count misses results packages.** Packages of analysis results are made of instance
  specifications with long generated names ("m3 Alignment Duration Scenario.aPS Mission
  Logical12.aps operational blackbox.pplc"). Answers rarely repeat such names in full, so in
  four of these packages (113 to 370 elements) no way of asking is credited with more than 4.
  Read, though, their summaries from parts are sound. What the parts cost is FU-022 in the
  follow-up review.

## Decision

- **Don't sandwich.** At the pipeline's input sizes it makes no difference, and in long
  inputs it doesn't fix what goes wrong. `module-summary@v1` and `package-synthesis@v1` stay
  current. The sandwiched versions (`module-summary@v2`, `package-synthesis@v2`,
  `package-summary@v3`) stay in the template registry, as tried and not chosen.
- **Keep inputs short instead.** Splitting large packages into parts of at most 12,000
  characters (DV-05) keeps every request far below the lengths where attention thins, and
  covers the middle of long packages better than one long request.
