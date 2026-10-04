# Rerankers, on the fictional questions

- **Date:** 2026-10-01
- **For:** plan RF, step RF-02 (`docs/archive/plans/related-facts-2026-10-01.md`)
- **Question:** how much does a reranker add to keyword search, to vector search and to hybrids,
  and how deep should it look?
- **Answer:**
  - **Keyword search with a reranker** does as well as vector search: BM25 with Qwen3-Reranker
    over its top 100 has an MRR of 0.79, against 0.77 for e5-large alone.
  - **Any hybrid with a reranker does best:** an MRR of 0.82, with the answer in the top 10 for
    98% of questions.
  - **A small reranker is enough.** The 0.6B model did as well as the 8B one.

## Setup

- **Rerankers:** Qwen3-Reranker-0.6B and 8B on DeepInfra (`cameo_ingest.evaluation.rerank`),
  standing in for the maintainer's in-house rerankers (plan RF, decision 3):
  - **The 0.6B:** about the size of `BAAI/bge-reranker-v2-m3`;
  - **The ms-marco cross-encoders** (MiniLM-L-12, TinyBERT-L-2): much smaller still.
- **The run** (`scripts/retrieval_eval.py --rerank`):
  - each system's top 30 (or 100) is reordered by the reranker's score, for the question and
    the window's text;
  - over the 178 fictional questions (answers known by construction);
  - in the corpus as `rag/` presents it (plain chunks with their source line, among the real
    samples).
- **Cost:** reranking every system's top 30 took about 4 million input tokens: 4 cents with the
  0.6B model, 20 with the 8B.

## Results

Hits in the top 1 and top 10, and MRR at 10; for the reranked systems, the change in MRR with
its 95% interval (paired bootstrap).

| System | Alone | Reranked by 0.6B (top 30) | Reranked by 8B (top 30) |
|---|---|---|---|
| BM25 | 0.46 / 0.78, 0.55 | 0.70 / 0.85, 0.76 (+0.21, +0.16 to +0.27) | 0.66 / 0.86, 0.75 (+0.20) |
| e5-large | 0.67 / 0.95, 0.77 | 0.72 / 0.97, 0.82 (+0.05, −0.00 to +0.11) | 0.70 / 0.97, 0.81 (+0.04) |
| bge-large | 0.66 / 0.94, 0.76 | 0.71 / 0.96, 0.80 (+0.04, −0.01 to +0.09) | 0.68 / 0.97, 0.80 (+0.04) |
| e5-large + BM25 | 0.58 / 0.88, 0.69 | 0.73 / 0.97, 0.82 (+0.13, +0.08 to +0.18) | 0.70 / 0.98, 0.81 (+0.12) |
| e5-large + BM25 at weight 0.25 | 0.67 / 0.94, 0.76 | 0.73 / 0.98, 0.82 (+0.07, +0.02 to +0.11) | 0.71 / 0.98, 0.82 (+0.06) |
| bge-large + BM25 | 0.58 / 0.88, 0.68 | 0.73 / 0.98, 0.82 (+0.14, +0.09 to +0.19) | 0.70 / 0.99, 0.81 (+0.13) |

**Paraphrased questions** (86 of the 178), MRR:

| System | Alone | Reranked by 0.6B | Reranked by 8B |
|---|---|---|---|
| BM25 | 0.31 | 0.62 | 0.65 |
| e5-large | 0.68 | 0.73 | 0.79 |
| bge-large + BM25 | 0.51 | 0.72 | 0.77 |

**Depth** (reranked by the 0.6B; top 1 / top 10, MRR):

| System | Top 30 | Top 100 |
|---|---|---|
| BM25 | 0.70 / 0.85, 0.76 | 0.70 / 0.94, 0.79 |
| BM25, paraphrased questions | 0.53 / 0.76, 0.62 | 0.53 / 0.90, 0.66 |
| bge-large + BM25 | 0.73 / 0.98, 0.82 | 0.73 / 0.98, 0.82 |

## What this says

- **A reranker closes most of BM25's gap on paraphrases.**
  - **Before and after:** BM25 alone finds few paraphrased questions (MRR 0.31); reranked, 0.62
    to 0.66.
  - **For a stack that leans on keyword search,** as the maintainer prefers, a reranker is the
    complement.
- **Rerank deeper behind keyword search.** BM25's top 30 misses answers that its top 100 holds
  (top-10 hits 0.85, against 0.94 at depth 100). Behind a hybrid, the top 30 is enough.
- **Weighted fusion helps without a reranker, and matters little with one.**
  - **Without:** lowering BM25's weight in a hybrid raises its MRR (0.69 at weight 1, 0.76 at
    0.25).
  - **With a reranker:** every hybrid reaches 0.82.
- **The small model is enough.** The 8B reranker was better on paraphrases (0.77 against 0.72)
  and worse on literal questions (0.85 against 0.91); overall the two tie. That bodes well for
  `bge-reranker-v2-m3`, which is the 0.6B's size.

## For the stack

- **If it gets a reranker:** keyword search (or a hybrid) for candidates, then the reranker:
  - **behind BM25:** over the top 100;
  - **behind a hybrid:** the top 30 is enough.
- **Without one:** a hybrid, with BM25 at a lower weight than the vectors (a quarter did best
  here).

## Limits

- **Stand-ins:** the maintainer's rerankers are not on DeepInfra, so these are results for
  Qwen3's. The ms-marco cross-encoders, trained on web search, may do less well on model text.
- **Fictional questions:** their phrasing comes from the models' author (see
  `fictional-projects-2026-10-01.md`).
