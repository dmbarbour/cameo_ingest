# Chunk styles compared, on judged grades

- **Date:** 2026-10-01
- **For:** plan steps RE-06 to RE-09 in `docs/archive/plans/retrieval-evaluation-2026-09-30.md`. It follows
  `retrieval-baseline-2026-10-01.md`, whose numbers credited only the known answers.
- **Question:** do the chunks find answers better as plain text (`--chunk-style plain`) than
  as the Markdown of the pages, and in what form?
- **Answer:** yes, as plain text, with an element's structural detail kept in its chunk when the
  whole fits in one part (1,500 characters), and in a details chunk of its own only when it
  doesn't.
  - **It is the default from version 0.5.0.** `--chunk-style markdown` gives the old chunks.

## In short

- **Plain text is never significantly worse** than Markdown, on any question set or system.
- **On the plain-written natural set, plain is significantly better** for every dense model:
  e5-large's MRR rises from 0.61 to 0.70, and bge-large's from 0.67 to 0.75.
- **On the Markdown-written natural set, the two tie** for e5-large (0.76 and 0.75) and
  bge-large (0.75 and 0.74), despite Markdown's home advantage.
- **Over both natural sets,** e5-large's top 10 rises from 0.91 to 0.96.
- **Requirements by id:** BM25 finds the requirement first for 20 of 20, against 6 of 20 on
  Markdown.
- **The weak models gain most.** MPNet's MRR on natural questions rises from 0.47 to 0.64, and
  MiniLM's from 0.50 to 0.62.
- **Half the tokens to embed:** 8.1 M e5 tokens against 17.2 M, in 37,490 windows against 47,164.
- **Where the details go:**
  - **Short details stay with their element.** In a chunk of their own they are a decoy for
    the element's name.
  - **Details stay in the index.** Left out, as a separate file would leave them, questions
    about members, ports and tagged values go unanswered.

## What was compared

**Four corpora** of the same 20 projects (every sample but TMT-2024x, plus the synthetic one).
Each is cut into windows of 512 tokens with 64 of overlap, as the production stack does:

| Corpus | Chunks | Windows | Characters |
|---|---|---|---|
| Markdown, as on the pages (`out/all`, 0.4.3) | 28,257 | 47,164 | 41.8 M |
| Plain, details always in a chunk of their own (`out/all-plain`) | 45,779 | 48,648 | 26.8 M |
| **Plain, details apart only when long** (`out/all-plain2`; the default from 0.5.0) | 34,343 | 37,490 | 25.0 M |
| Plain, details outside the index (simulated: `out/all-plain` without its 14,656 details chunks) | 31,123 | 33,067 | – |

**The plain style** (`cameo_ingest.plain`):
- **No apparatus:** links reduced to their labels, no trace line (the metadata keeps the
  provenance), no Markdown marks.
- **A heading on every chunk:** what the item is, its readable name, where it is (the last three
  packages of its path) and the project. For example, "Block Movement Channel in
  M-SysML::Facility::Material Handling System (project NIST_M-SysML.mdzip)".
- **Titles for unnamed requirements:** their id and the start of their text, in place of
  "(unnamed)".
- **Parts:** long text is split into parts of at most 1,500 characters, at line boundaries, each
  repeating the heading.
- **Meaning first:** structural detail (members, tagged values) comes after the documentation,
  requirement text, relationships and diagrams.

**Four question sets:**
- **Synthetic (28):** about the synthetic project, graded by construction.
- **Structural (88):** literal questions from the tables: a requirement by its id, an element by
  its name, and what an element is allocated to, derived from or satisfied by.
- **Natural (75):** written by DeepSeek-V3.2 from sampled Markdown chunks. Each comes with a
  quote from its chunk that answers it.
- **Natural, plain (75):** the same writer and prompt, from sampled chunks of `out/all-plain2`.
  - **Why a second set:** a question written from a chunk favours the style it was written
    from, so the two natural sets are read together. Each style has the home advantage on one.

**The systems:**
- **Dense:** e5-large (without prefixes, which made no difference: see the baseline),
  bge-large-en-v1.5 (standing in for ember-v1), MPNet and MiniLM, all on DeepInfra.
- **Keyword:** BM25.
- **Hybrid:** each dense model fused with BM25.

## Judging

- **The pools:** the top 10 of every system, per corpus and question set: 25,000 pairs of
  question and passage in all.
- **The panel:** DeepSeek-V3.2 and Qwen3-235B grade every pair 0, 1 or 2
  (`eval-relevance-judge@v1`). Kimi-K2-Instruct-0905 was to settle their disagreements, but the
  check set shows that the measures reported here don't need it.
  - **How often they disagree:** on a quarter to a third of pairs (kappa 0.43 to 0.51).
  - **Cost:** about 20 M input tokens for the two main judges, and 1.8 M for Kimi.
- **The check set:** Claude labelled 200 pairs blind, and the panel was measured against those
  labels.
  - **The pairs:** 120 on which the two main judges disagreed and 80 on which they agreed, from
    both the Markdown and the plain pools.

On the 120 disagreements, each judge and each way of settling them, against Claude's labels.
Kimi graded the 70 from the Markdown pools; it was stopped before the plain ones (see Limits).

| Rater | Pairs | Same grade as Claude | Kappa | Same answer-or-not call |
|---|---|---|---|---|
| DeepSeek-V3.2 | 120 | 57% | 0.27 | 87% |
| Qwen3-235B | 120 | 36% | 0.04 | 68% |
| **The lower of the two** (the headline scores) | 120 | 66% | 0.35 | 94% |
| Kimi-K2-Instruct (the tie-breaker) | 70 | 79% | 0.61 | 94% |

**What the check set shows:**
- **The scores count answers only:** a hit or a reciprocal rank needs a passage graded 2.
- **The headline scores take the lower grade** when the main judges disagree, so a disagreement
  is never an answer.
  - **As good as the tie-breaker for that call:** it agrees with Claude's answer-or-not on 94%
    of the disagreements, as Kimi does.
  - **It needs no third model.** Kimi agrees better with Claude on the full grade, which counts
    for nDCG only (not reported here).
- **Where the two judges agree, Claude mostly does too:** on 43 of 52 pairs both graded 0 or 1.
- **The panel is generous with 2s ("answers it").** Of 28 pairs that both judges graded 2,
  Claude graded 13 so.
  - **What it credits:** passages about a similar element (a customization of another
    stereotype, a requirement with a nearby id), and lists that only name the subject.
  - **The absolute scores are therefore optimistic,** hits at 1 especially.
  - **The comparison between styles holds.** It is paired (the same questions, the same
    judges), and if anything the generosity favours Markdown. Claude agreed with 4 of 14 such 2s
    in the Markdown pools, against 9 of 14 in the plain ones. Markdown's windows are full of
    names (ledger rows, member lists, link targets) that look like answers.
- **A stricter judge prompt** would make the absolute numbers more trustworthy (a follow-up in
  plan RE).

## Results: Markdown against plain

Hits in the top 1, 5 and 10, MRR at 10, and the change in MRR with its 95% interval (paired
bootstrap over the questions). "Plain" is the default corpus, with details apart only when
long.

**Structural (88)**

| System | Markdown: top 1 / 5 / 10, MRR | Plain: top 1 / 5 / 10, MRR | MRR change (95% interval) |
|---|---|---|---|
| e5-large | 0.66 / 0.76 / 0.78, 0.70 | 0.67 / 0.78 / 0.83, 0.73 | +0.03 (-0.03 to +0.09) |
| bge-large | 0.58 / 0.74 / 0.77, 0.65 | 0.69 / 0.83 / 0.85, 0.75 | +0.10 (+0.02 to +0.18) |
| MPNet | 0.32 / 0.55 / 0.62, 0.43 | 0.36 / 0.56 / 0.60, 0.45 | +0.02 (-0.02 to +0.06) |
| MiniLM | 0.48 / 0.67 / 0.70, 0.57 | 0.45 / 0.68 / 0.73, 0.55 | -0.01 (-0.07 to +0.05) |
| BM25 | 0.56 / 0.88 / 0.92, 0.71 | 0.68 / 0.89 / 0.94, 0.77 | +0.07 (-0.01 to +0.14) |
| e5-large + BM25 | 0.70 / 0.91 / 0.93, 0.78 | 0.72 / 0.94 / 0.98, 0.82 | +0.04 (-0.03 to +0.10) |
| bge-large + BM25 | 0.70 / 0.91 / 0.93, 0.78 | 0.72 / 0.94 / 0.98, 0.82 | +0.04 (-0.04 to +0.11) |

**Both natural sets (150)**

| System | Markdown: top 1 / 5 / 10, MRR | Plain: top 1 / 5 / 10, MRR | MRR change (95% interval) |
|---|---|---|---|
| e5-large | 0.57 / 0.83 / 0.91, 0.68 | 0.59 / 0.92 / 0.96, 0.72 | +0.04 (-0.01 to +0.09) |
| bge-large | 0.61 / 0.87 / 0.90, 0.71 | 0.63 / 0.89 / 0.93, 0.75 | +0.04 (-0.01 to +0.09) |
| MPNet | 0.37 / 0.56 / 0.73, 0.47 | 0.55 / 0.76 / 0.81, 0.64 | +0.17 (+0.10 to +0.23) |
| MiniLM | 0.39 / 0.66 / 0.73, 0.50 | 0.50 / 0.79 / 0.89, 0.62 | +0.12 (+0.06 to +0.18) |
| BM25 | 0.47 / 0.68 / 0.77, 0.56 | 0.46 / 0.74 / 0.85, 0.58 | +0.02 (-0.02 to +0.07) |
| e5-large + BM25 | 0.53 / 0.83 / 0.89, 0.66 | 0.57 / 0.89 / 0.93, 0.71 | +0.05 (+0.01 to +0.10) |
| bge-large + BM25 | 0.54 / 0.84 / 0.88, 0.67 | 0.59 / 0.87 / 0.93, 0.71 | +0.04 (-0.01 to +0.09) |

**Synthetic (28; by construction)**

| System | Markdown: top 1 / 5 / 10, MRR | Plain: top 1 / 5 / 10, MRR | MRR change (95% interval) |
|---|---|---|---|
| e5-large | 0.82 / 1.00 / 1.00, 0.90 | 0.82 / 0.96 / 1.00, 0.88 | -0.03 (-0.09 to +0.03) |
| bge-large | 0.75 / 0.96 / 1.00, 0.84 | 0.86 / 0.96 / 1.00, 0.91 | +0.07 (+0.01 to +0.13) |
| MPNet | 0.36 / 0.79 / 0.86, 0.48 | 0.68 / 0.89 / 0.93, 0.78 | +0.29 (+0.15 to +0.44) |
| MiniLM | 0.71 / 0.86 / 0.96, 0.79 | 0.75 / 0.93 / 0.93, 0.82 | +0.03 (-0.05 to +0.11) |
| BM25 | 0.61 / 0.79 / 0.86, 0.70 | 0.61 / 0.82 / 0.89, 0.71 | +0.01 (-0.00 to +0.03) |
| e5-large + BM25 | 0.82 / 0.96 / 1.00, 0.88 | 0.82 / 0.93 / 0.96, 0.88 | -0.00 (-0.09 to +0.09) |
| bge-large + BM25 | 0.75 / 0.96 / 0.96, 0.83 | 0.89 / 0.96 / 1.00, 0.92 | +0.09 (+0.02 to +0.17) |

**The home advantage, in MRR:** each natural set favours the style it was written from, and
plain's margin on its own set is larger than Markdown's on its own.

| System | From Markdown chunks: Markdown, plain | From plain chunks: Markdown, plain |
|---|---|---|
| e5-large | 0.76, 0.75 | 0.61, **0.70** |
| bge-large | 0.75, 0.74 | 0.67, **0.75** |
| MPNet | 0.46, **0.66** | 0.49, **0.63** |
| MiniLM | 0.54, 0.62 | 0.45, **0.62** |
| BM25 | 0.58, 0.64 | 0.53, 0.52 |
| e5-large + BM25 | 0.70, 0.74 | 0.61, 0.67 |
| bge-large + BM25 | 0.68, 0.73 | 0.65, 0.69 |

Bold: significantly better than the other style (the interval excludes zero).

**By template** (structural questions; top 1 and MRR):

| Template (questions) | e5-large | bge-large | BM25 | bge-large + BM25 |
|---|---|---|---|---|
| A requirement by its id (20) | 0.20, 0.24 → 0.25, 0.32 | 0.00, 0.05 → 0.30, 0.40 | 0.30, 0.55 → 1.00, 1.00 | 0.40, 0.55 → 0.70, 0.85 |
| A documented element by name (47) | 0.83, 0.88 → 0.83, 0.88 | 0.83, 0.89 → 0.81, 0.86 | 0.55, 0.71 → 0.49, 0.65 | 0.85, 0.90 → 0.72, 0.83 |
| What an element is allocated to (11) | 0.45, 0.50 → 0.55, 0.61 | 0.27, 0.44 → 0.64, 0.69 | 0.64, 0.69 → 0.64, 0.67 | 0.36, 0.53 → 0.45, 0.56 |
| What derives from, or satisfies, a requirement (10) | 1.00, 1.00 → 0.90, 0.95 | 0.90, 0.95 → 1.00, 1.00 | 1.00, 1.00 → 1.00, 1.00 | 1.00, 1.00 → 1.00, 1.00 |

## Where the details go

The four corpora, on the structural and the Markdown-written natural questions (top 1, top 10,
MRR):

| System | Markdown | Details always apart | **Details apart when long** | Details outside the index |
|---|---|---|---|---|
| e5-large, structural | 0.66, 0.78, 0.70 | 0.62, 0.80, 0.68 | **0.67, 0.83, 0.73** | 0.65, 0.81, 0.70 |
| bge-large, structural | 0.58, 0.77, 0.65 | 0.60, 0.84, 0.68 | **0.69, 0.85, 0.75** | 0.65, 0.78, 0.70 |
| bge-large + BM25, structural | 0.70, 0.93, 0.78 | 0.66, 0.95, 0.77 | **0.72, 0.98, 0.82** | 0.76, 0.93, 0.84 |
| e5-large, natural | 0.67, 0.95, 0.76 | 0.60, 0.92, 0.71 | **0.64, 0.96, 0.75** | 0.59, 0.81, 0.66 |
| bge-large, natural | 0.68, 0.89, 0.75 | 0.56, 0.88, 0.68 | **0.64, 0.91, 0.74** | 0.55, 0.77, 0.62 |
| MPNet, natural | 0.35, 0.75, 0.46 | 0.49, 0.79, 0.60 | **0.57, 0.80, 0.66** | 0.47, 0.69, 0.55 |

- **Details always apart:** a short details chunk is mostly heading ("Stereotype SAF_A2_GRID in
  SAF_Profile::DiagramStereotype …, details. Members: icon Image"). For "What is X in P?" it
  outranks the element's own description. On the 47 lookups, the two hybrids' MRR fell from 0.87
  and 0.90 to 0.77.
- **Details apart only when long** (the default): they go apart for 12% of the elements that
  have them (1,523 of 12,793), and the rest stay with their element. Dense lookups are back to
  Markdown's level, and the hybrids recover about half of the loss (0.83 against 0.90).
- **Details outside the index** (a separate file, as first suggested):
  - **What it gains:** a few first places on the structural questions.
  - **What it loses:** the natural questions about structure, such as "What are the constituent
    parts of the TC2030-NL connector?" or "What is the type of the maintenance port?".
    e5-large's top 10 on the natural set falls from 0.92 to 0.81.
  - **So details stay in `chunks.jsonl`.** The long ones come as chunks of kind
    `<kind>:details`, which a store can filter or weight.

## Why plain text helps, and where it doesn't

- **Ids and names come first.** A requirement's id is in its title and heading, not 100 tokens
  into the chunk after "(unnamed)". BM25 finds any requirement by its id, and bge-large ranks it
  first 6 times in 20, against none.
- **Every part says whose it is.** The heading is repeated in each part of a long section, so
  the part holding an element's relationships is found by the element's name. For "What is X
  allocated to?", bge-large's MRR rises from 0.44 to 0.69.
- **The weak models gain most.** Markdown's link targets and trace lines fill their short
  windows with ids.
- **First places are still lost to near neighbours.** On the Markdown-written natural set,
  e5-large and bge-large each lose about 10 first places to Markdown and win 7. In most of those
  losses, the answer is second or third. A stack that passes a few chunks to the LLM, or neighbouring chunks with each hit, doesn't
  lose them.
- **Package questions written from Markdown chunks** (13) are the one group where plain does
  worse: e5-large's MRR on them falls from 0.80 to 0.61.

## What this means for the stack

- **Keyword search pays most for ids.** With plain text, BM25 alone finds any requirement by
  its id. Hybrid search puts the answer in the top 10 for 0.98 of the structural questions,
  against 0.83 for e5-large alone.
- **e5-large and bge-large are close,** and both are well ahead of MPNet and MiniLM. e5's
  prefixes don't matter here (baseline).
- **Take five or more chunks.** With e5-large on plain chunks, the first chunk answers 59% of the
  natural questions, and the first five answer 92%.

## Limits

- **No tie-broken comparison.** Kimi graded the Markdown pools' disagreements, but not all of the
  plain pools'. DeepInfra's Kimi slowed to one or two requests a minute, so it was stopped. On
  the check set it would change few answer calls (above), and its grades so far are cached.
- **The panel is generous with 2s** (above), so absolute scores, top-1 hits especially, are
  optimistic.
- **The natural questions await the maintainer's spot check.** The second set was written the
  same way.
- **Small sets:** 75 to 88 questions each. Differences under about 0.07 in MRR are within the
  noise, as the intervals show.
- **One pipeline simulated:** 512-token windows with 64 of overlap over `chunks.jsonl`. Windows
  over the pages are not tested.
- **Generated and ledger chunks were indexed in every corpus.** Whether to index them is not
  tested here.
