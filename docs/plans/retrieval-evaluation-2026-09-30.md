# Plan: retrieval evaluation, 2026-09-30

- **Status:** Proposed on 2026-09-30. It waits on the maintainer's answers to the open questions
  at the end.
- **Step prefix:** `RE`, so steps are `RE-01`, `RE-02` and so on
- **Addresses:** the "Retrieval evaluation" tentative plan in `docs/plans/README.md`, and the
  advice in the README's "Using the output for RAG", which is untested. It also informs the
  tentative plan for splitting chunks. The judging here overlaps with the deferred judge panel
  of `docs/plans/llm-quality-2026-09-30.md` (LQ-04 to LQ-06), so the two should share it.

## Goals

1. **Measure retrieval with the models that will be deployed.** How well do the chunks of an
   output tree (`chunks.jsonl`) come back for realistic questions, with the maintainer's
   in-house embedding models?
2. **Find what to change, with evidence.** Which changes to the output help, and by how much:
   - the text of chunks, and their sizes;
   - the generated chunks (summaries, module descriptions, parts);
   - the ledgers and the metadata.
3. **A repeatable harness.** Run it again after the output changes, as spot checks are run for
   LLM text.

**Not goals:** choosing a vector store, generating answers end to end (a possible later step),
and training or fine-tuning models.

## What we know already

Measured on 2026-09-30.

### The target models

| Model | Dimensions | Input limit (tokens) | Prefixes | Available now |
|---|---|---|---|---|
| `sentence-transformers/all-MiniLM-L6-v2` | 384 | 256 | none | Local TEI container `spd-embed-all-minilm-l6-v2` (`http://localhost:8081/v1/embeddings`; plain HTTP, not HTTPS); DeepInfra |
| `sentence-transformers/all-mpnet-base-v2` | 768 | 384 | none | DeepInfra |
| `intfloat/multilingual-e5-small` | 384 | 512 | `query: `, `passage: ` | Not on DeepInfra (404); runs in the same TEI image |
| `intfloat/multilingual-e5-large` | 1024 | 512 | `query: `, `passage: ` | DeepInfra |

The local container truncates longer inputs silently (`auto_truncate`), as the in-house
deployment probably does too.

### Chunk lengths against those limits

TMT's output tree (version 0.4.0) has 21,279 chunks. Its text runs 2.7 characters per token,
measured with the MiniLM tokenizer; plain English prose runs about 4.

| Kind | Chunks | Tokens (median) | Over 256 | Over 384 | Over 512 |
|---|---|---|---|---|---|
| element | 11,368 | 214 | 28% | 15% | 10% |
| requirement | 4,284 | 469 | 99% | 81% | 39% |
| generated:module_summary | 1,514 | 422 | 100% | 80% | 28% |
| diagram | 1,346 | 613 | 99% | 88% | 68% |
| generated:diagram_description | 1,061 | 266 | 56% | 10% | 3% |
| ledger | 780 | 249 | 49% | 44% | 40% |
| package | 560 | 339 | 61% | 47% | 39% |

- **Most of the text is not for embedding:** 23% of chunk characters are link targets
  (`](../packages/…#anchor-id)`), 14% qualified names and 8% trace lines. They serve readers
  and provenance, but they fill the embedding window first.
- **An example:** a DOORS requirement's chunk spends about 100 tokens on its title
  ("«TMT_Requirement» «HierarchyElement» «ObjectProperties» (unnamed)"), its kind and a 20-level
  qualified name, before the requirement text starts.
- **So MiniLM sees little of most requirements and diagrams.** The first question may be less
  "which model?" than "which text do we give it?".

## The test collection

### Corpora

- **The drone sample** (183 chunks): small enough to check every result by hand.
- **TMT** (about 21,000 chunks): the realistic scale, with many near-duplicates such as
  requirement lists and analysis results.
- **Optionally SAF_FFDS:** another modelling style (the SAF and UAF profiles). Combined with
  the others, it tests confusion between projects in one tree.

### Queries, from three sources, each with its own ground truth

1. **Structural questions, generated from the model.** Their answers are known by
   construction, so they need no judge:
   - by id: "What does REQ-1-OAD-0468 require?";
   - by relationship: "Which requirements is Maneuver Autonomously derived from?";
   - by diagram content: "Which diagram shows Monitor Power sending Power Level Status?";
   - by parameter: "What is the maximum phasing time in the wavefront calibration runs?".

   They share words with their answers, so they favour lexical search and flatter embeddings.
   They serve for regressions and coverage, not to choose a model by themselves.
2. **Natural questions, written by an LLM from a sampled chunk** ("doc2query"). The LLM is told
   to paraphrase rather than copy names where it can, and to tag each question with a
   category. The source chunk is relevant; other chunks are judged by pooling (below).
3. **A gold set from the maintainer:** 25 to 40 questions of the kinds real users ask, each
   with the answer they would expect. It is the smallest source and the most valid. Its
   relevance is judged by pooling, and reviewed by the maintainer.

The categories come from the README's RAG advice:
- **lookup:** what is X;
- **rationale and trace:** why does R exist, what derives from R;
- **listing:** list the activity diagrams, which requirements cover thermal control;
- **behaviour:** what happens after X;
- **structure:** what is X made of, what connects to Y;
- **parameters:** what is the time limit for M3 alignment;
- **provenance:** which models came from supplier X.

### Relevance judgments

- **Structural questions:** graded by construction.
  - **2:** the element's own chunk, or a generated chunk about it.
  - **1:** a chunk that holds the needed fact about it, such as a ledger row or a diagram's
    legend.
- **Other questions:** by pooling. The top 10 of every configuration are pooled, and each pair
  of question and chunk is judged 0, 1 or 2 by an LLM judge, given the question and the
  chunk's text.
  - **Cached:** a pair is judged once, whichever configuration retrieved it.
- **Checking the judge:** Claude and the maintainer label a stratified sample of about 100 pairs
  by hand, and agreement with the LLM judge is measured (Cohen's kappa).
  - **If it agrees well enough:** the judge is used.
  - **If not:** Claude labels the pools instead, which is feasible for a few hundred pairs.

### Measures

- **Recall at 5, 10 and 20:** the context sizes a RAG prompt takes.
- **MRR at 10, and nDCG at 10 (graded):** per category and per corpus.
- **Contributions by chunk kind:** which kinds answer which categories, generated chunks
  included.
- **Cost:** embedding time and price per corpus and model, on a local CPU against DeepInfra.
- **Care with small numbers:** every configuration runs on the same questions, so
  differences are paired; they are reported with bootstrap confidence intervals.

## What is compared

- **Dense retrieval** with the four target models:
  - **MiniLM** both locally and on DeepInfra, to check that the two give the same vectors;
  - **MPNet and e5-large** on DeepInfra;
  - **e5-small** in a local TEI container.

  The e5 models are run with and without their `query: ` and `passage: ` prefixes, in case the
  in-house pipeline doesn't add them.
- **Lexical retrieval:** BM25 over the same chunks.
- **Hybrid retrieval:** BM25 with each dense model, by reciprocal rank fusion.
- **Later, if the stack allows it:** a cross-encoder reranker.

## Changes to try, each measured against the baseline

1. **Text for embedding:** a plain version of each chunk, with the full Markdown kept for
   display. Links are reduced to their labels, the trace line is dropped, the qualified name
   is shortened to its owning package, and the key text comes first (the requirement's id and
   text, the documentation).
2. **Splitting long chunks** into overlapping windows that fit the model, each repeating the
   element's header, or splitting by field (text, tagged values, relationships).
3. **Titles for unnamed requirements:** the requirement's id and the start of its text, in
   place of "(unnamed)", on pages too.
4. **Generated chunks,** included or not.
5. **Ledger chunks,** included or not.

Each change alters the corpus, so its embeddings are computed again. They are cached by the
hash of their text, so unchanged chunks cost nothing.

## The harness

- **Where:** scripts under `scripts/`, with their extra dependencies (numpy, a BM25
  implementation) in an optional dependency group, so that ingesting doesn't need them.
- **Embedding cache:** SQLite, keyed by model, endpoint and the text's sha256. It is resumable,
  like `llm.sqlite`.
- **Search:** exact cosine similarity with numpy. TMT at 1,024 dimensions takes about 90 MB, so
  no vector store is needed.
- **Output:** `out/eval/retrieval/<stamp>/`, holding:
  - the questions and their relevance judgments, and each configuration's results;
  - a report of tables;
  - a page per question, with each configuration's top 10 and their judgments, for inspection.
- **Data:** question sets derived from the samples stay under `out/`, which is gitignored, as
  the samples do. The generators, and a template for the gold set, go in the repository.
- **Cost:** TMT's chunks come to about 8 million tokens per model, which is cents on DeepInfra.
  Local CPU speed is measured in RE-02.

## Steps

| Step | Work | Status |
|---|---|---|
| RE-01 | Inventory: chunk lengths in each model's tokens, and what fills them (links, names, traces), as a script and a research note. | Partly done: the tables above |
| RE-02 | Endpoints and the embedding cache: local TEI (MiniLM, and a container for e5-small) and DeepInfra (MiniLM, MPNet, e5-large). Check that local and DeepInfra MiniLM agree. Record input limits, prefixes and speed. | Not started |
| RE-03 | Questions: the structural generator, the LLM question writer, and a template for the maintainer's gold set. | Not started |
| RE-04 | The harness: indexes, dense, BM25 and hybrid search, measures with confidence intervals, the report and per-question pages. | Not started |
| RE-05 | Judging: the pooled LLM judge, with cached judgments, checked against labels by Claude and the maintainer. | Not started |
| RE-06 | Baseline: the four models, each dense and hybrid, and BM25, on the drone sample and TMT as they are now. | Not started |
| RE-07 | Changes: text for embedding, splitting, titles, generated and ledger chunks included or not. | Not started |
| RE-08 | Recommendations: adopt what helps into the output (with a version bump), rewrite the README's RAG advice, and say what the in-house pipeline should do (prefixes, windows, hybrid search). | Not started |

## Open questions for the maintainer

1. **The production stack:**
   - Which vector store, and how many chunks does a prompt take?
   - Is keyword or hybrid search available, and a reranker?
   - Does the pipeline embed our chunks as they are, or split them again?
   - Does it add the e5 prefixes?
2. **The in-house models' settings:** the input limits (MiniLM is often run at 256 tokens,
   sometimes 512), and whether vectors are normalized.
3. **The gold set:** can you write 25 to 40 real questions, with the answers you'd expect?
   Can they be committed, or do they belong with the samples, outside the repository?
4. **The judge:** is `google/gemma-4-31B-it` on DeepInfra acceptable, checked as above, or
   should a stronger model judge? This is the same question as the deferred judge panel.
5. **The corpora:** is TMT representative of your models? Should SAF_FFDS, or anything else,
   be included?
6. **The output format:** if a plain text for embedding helps, may it go into `chunks.jsonl`
   as a second field (say `embed_text`, with `text` kept for display)? Or should `text` itself
   become plainer?
