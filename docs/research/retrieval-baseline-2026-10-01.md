# Retrieval baseline, before judging

- **Date:** 2026-10-01
- **For:** plan steps RE-05 and RE-07 in `docs/archive/plans/retrieval-evaluation-2026-09-30.md`
- **Status:** preliminary, and superseded by the judged grades in
  `docs/research/chunk-styles-2026-10-01.md`, which also tests the changes suggested at the end.
  - **The synthetic questions are graded fully:** their answers are known by construction.
  - **The others are not yet:** the structural and natural questions credit only their known
    answer, so another chunk that also answers (a ledger row repeating a requirement, say) counts
    as a miss until the judge panel (RE-06) grades it. Their scores are lower bounds.
  - **The natural questions** await the maintainer's spot check.
- **The corpus:** `out/all` (version 0.4.3): every sample but TMT-2024x, plus the synthetic project.
  That's 20 projects and 28,257 chunks, cut into 47,164 windows of 512 tokens with 64 of overlap,
  on e5-large's tokens. Every system ranks the same windows.
- **The models:** on DeepInfra (decision 8), each at its standard input limit. `bge-large-en-v1.5`
  stands in for ember-v1.
- **The method:** `scripts/retrieval_eval.py`, with `--questions synthetic`, `structural` (88
  questions from `scripts/write_questions.py`) and `natural` (75). Embedding cost about $0.75 in
  all; each model took 10 to 17 minutes at 24 requests at a time.

## Results

Hits in the top 1 and the top 10, and MRR at 10 (the mean of 1/rank of the first answer):

| System | Synthetic (28): top 1 / top 10 / MRR | Structural (88): top 1 / top 10 / MRR | Natural (75): top 1 / top 10 / MRR |
|---|---|---|---|
| e5-large | 0.82 / 1.00 / 0.90 | 0.26 / 0.62 / 0.38 | 0.47 / 0.80 / 0.56 |
| e5-large, no prefixes | 0.82 / 1.00 / 0.90 | 0.27 / 0.62 / 0.40 | 0.53 / 0.84 / 0.61 |
| bge-large (stand-in for ember-v1) | 0.75 / 1.00 / 0.84 | 0.39 / 0.67 / 0.49 | 0.56 / 0.76 / 0.63 |
| MPNet | 0.36 / 0.86 / 0.48 | 0.17 / 0.42 / 0.25 | 0.17 / 0.47 / 0.25 |
| MiniLM | 0.71 / 0.96 / 0.79 | 0.10 / 0.40 / 0.20 | 0.19 / 0.47 / 0.27 |
| BM25 alone | 0.61 / 0.86 / 0.70 | 0.25 / 0.82 / 0.42 | 0.29 / 0.60 / 0.39 |
| e5-large (no prefixes) + BM25 | 0.82 / 1.00 / 0.88 | 0.30 / 0.81 / 0.46 | 0.40 / 0.80 / 0.53 |
| bge-large + BM25 | 0.75 / 0.96 / 0.83 | 0.36 / 0.84 / 0.53 | 0.45 / 0.77 / 0.57 |

The synthetic questions split by how they are asked (top 1 / MRR):

| System | Literal (14) | Paraphrase (14) |
|---|---|---|
| e5-large | 0.93 / 0.96 | 0.71 / 0.85 |
| bge-large | 0.86 / 0.91 | 0.64 / 0.77 |
| MiniLM | 0.79 / 0.89 | 0.64 / 0.70 |
| BM25 alone | 0.93 / 0.96 | 0.29 / 0.43 |

The structural questions split by template (top 1 / top 10):

| Template (questions) | e5-large, no prefixes | bge-large | MiniLM | BM25 | bge-large + BM25 |
|---|---|---|---|---|---|
| A requirement by its id (20) | 0.10 / 0.10 | 0.00 / 0.10 | 0.00 / 0.00 | 0.30 / 0.90 | 0.25 / 0.80 |
| A documented element by name (47) | 0.36 / 0.87 | 0.47 / 0.89 | 0.19 / 0.62 | 0.23 / 0.83 | 0.38 / 0.91 |
| What an element is allocated to (11) | 0.00 / 0.18 | 0.36 / 0.45 | 0.00 / 0.00 | 0.00 / 0.45 | 0.18 / 0.45 |
| What derives from a requirement (5) | 0.00 / 1.00 | 0.60 / 1.00 | 0.00 / 0.60 | 0.00 / 1.00 | 0.40 / 1.00 |
| What satisfies a requirement (5) | 1.00 / 1.00 | 1.00 / 1.00 | 0.00 / 0.60 | 1.00 / 1.00 | 1.00 / 1.00 |

## What the results say so far

- **e5-large and bge-large lead,** close to each other. MiniLM and MPNet trail far behind on the
  real samples. MPNet, usually the stronger of those two, is the weakest here. Its endpoint
  behaves normally on plain sentences, and what beats its answers are fragments of long chunks
  that are mostly link targets and ids. It seems to suffer most from our noisy text.
- **e5's prefixes don't help on this text.** Without them it does as well or better (natural
  questions: MRR 0.61 against 0.56).
- **Requirement ids defeat every embedding model.** They find the requirement for "What does
  requirement CPBLTY-15 state?" in the top 10 at most one time in ten; BM25 does nine times in
  ten. Ids are opaque tokens to embeddings, and they come about 100 tokens into a requirement's
  chunk, after a title that reads "(unnamed)" for requirements imported from DOORS.
- **Relationships at the end of long sections are lost.** "What is X allocated to?" fails
  everywhere. When a long section is cut into windows, the window holding its relationships no
  longer carries the element's name, so nothing ties it to the question.
- **Keyword search pays off for literal questions** (ids and exact names), and costs a little
  on paraphrases: fused with BM25, e5 and bge lose 5 to 10 points of top-1 hits on natural
  questions. It would help most where people look things up by id.
- **The synthetic facts are found** among 28,000 chunks: by e5-large always in the top 5, and
  first four times in five.

## What this suggests trying next (RE-08)

1. **Plainer chunk text:** link labels without their targets, no trace line, the qualified name
   shortened, and the key text first.
2. **Ids and names up front:** a requirement's id and the start of its text as its title, in
   place of "(unnamed)".
3. **The element's heading in every window:** split long sections ourselves, repeating the heading
   (name, kind, id) in each part, so that a part about relationships still says whose they are.
4. **Keyword search,** once the stack can take it, mainly for ids.

These are output changes, each measured against this baseline once the judges have graded the
pools, so that their effect on all three question sets can be compared fairly.
