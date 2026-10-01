# Plan: retrieval evaluation, 2026-09-30

- **Status:** Proposed on 2026-09-30, and revised the same day with the maintainer's answers
  (Decisions, below). Ready to start.
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

## Decisions

All answered by the maintainer on 2026-09-30.

| # | Question | Decision |
|---|---|---|
| 1 | The production stack | Not fully known, nor controlled by the maintainer. It cuts text into 512-token chunks, with some overlap between neighbouring chunks. There is no reranker. Keyword search is wanted, but can't be added cleanly yet. |
| 2 | The in-house models' settings | Unknown. The evaluation measures what the unknowns cost (below), so they can be raised with the stack's owners. |
| 3 | A gold set from the maintainer | No: the maintainer doesn't know the samples well enough to be a gold standard. The maintainer spot-checks a sample of the generated questions for sense instead. |
| 4 | The judge | High-quality models: Claude, and a few strong models on DeepInfra, within a modest budget. |
| 5 | The corpora | Several sample projects, ideally all of them. |
| 6 | A second text field for embedding | Not pursued: the stack embeds whatever text it is given, and we can't change which field it reads. If plainer text helps, `text` itself becomes plainer. |
| 7 | Which models (added later that day) | Production probably doesn't use MiniLM. The in-house list has `llmrails/ember-v1` (512 tokens) beside the two e5 models, and one reranker, `BAAI/bge-reranker-v2-m3` (8,192 tokens). |
| 8 | Local models (after two crashes that day) | Not restarted: only what DeepInfra serves is evaluated. |
| 9 | A gold standard (the maintainer's suggestion) | A synthetic project with planted facts and questions whose answers are known by construction. |
| 10 | Keyword search (2026-10-01, after the baseline) | A future plan: a keyword index of the corpus, and an export searchable without special tools (Ctrl+F in Excel). It is in the plan index's tentative list. |
| 11 | The changes to try (2026-10-01) | Plainer chunk text, with structural detail kept apart from meaning, perhaps in a separate file; readable titles; the heading repeated in each part of a long section. Judge first, then try them. |

### What these mean for the design

- **Simulate the production pipeline.** The baseline cuts each chunk's text into 512-token
  windows that overlap their neighbours, as the stack does. The overlap is unknown, so 64
  tokens is assumed, with 0 and 128 as a check. Whether the stack reads `chunks.jsonl` or the
  Markdown pages is also unknown, so both are run.
- **Measure what the unknowns cost.**
  - **Window against model:** a 512-token window embedded by MiniLM at its usual 256-token limit
    is embedded by half. MPNet's limit is 384 tokens. Each model is run at its standard limit,
    and the loss is reported.
  - **e5 prefixes:** the e5 models are run with and without their `query: ` and `passage: `
    prefixes.
- **Keyword search is secondary.** BM25 and hybrid search are measured, to show what they would
  add once they can be integrated. The recommendations assume dense retrieval alone.
- **The models (decisions 7 and 8), all on DeepInfra:**
  - **e5-large,** with and without its prefixes.
  - **`BAAI/bge-large-en-v1.5`, standing in for ember-v1,** which DeepInfra doesn't serve. It has the
    same shape (BERT-large, `[CLS]` pooling, 1,024 dimensions, 512 tokens) and nearly the same
    benchmark score (63.2, against ember-v1's 63.5). It is reported as a stand-in, not as ember-v1.
  - **MPNet,** kept from the first list.
  - **MiniLM,** only as a cheap point of reference.
  - **Not evaluated:** e5-small, which DeepInfra doesn't serve (e5-large shows how the family
    reads our text). The reranker `bge-reranker-v2-m3` isn't served either. DeepInfra's
    `Qwen/Qwen3-Reranker-4B` could stand in for it later, to show what a reranking stage adds.
- **Why not locally:** this machine has 8 cores, 15 GB of memory and no GPU. In local containers,
  e5-small embedded about 6 chunks a second and ember-v1 under 0.2, so a model would take hours to
  days. Running ember-v1 alongside other work also coincided with the machine's second crash.
- **Memory:** heavy local work (tokenizing, indexing) runs one job at a time, under a systemd memory
  cap (`systemd-run --user --scope -p MemoryMax=3G`), so that a runaway job is killed rather than
  the machine.

## What we know already

Measured on 2026-09-30.

### The target models

| Model | Dimensions | Input limit (tokens) | Prefixes | Available now |
|---|---|---|---|---|
| `sentence-transformers/all-MiniLM-L6-v2` | 384 | 256 | none | DeepInfra (and the same vectors from a local container) |
| `sentence-transformers/all-mpnet-base-v2` | 768 | 384 | none | DeepInfra |
| `intfloat/multilingual-e5-small` | 384 | 512 | `query: `, `passage: ` | Not on DeepInfra (404); not evaluated (decision 8) |
| `intfloat/multilingual-e5-large` | 1024 | 512 | `query: `, `passage: ` | DeepInfra |
| `llmrails/ember-v1` | 1024 | 512 | none | Not on DeepInfra; `BAAI/bge-large-en-v1.5` stands in (decision 8) |
| `BAAI/bge-reranker-v2-m3` (reranker) | | 8,192 | | Not on DeepInfra; not evaluated (decision 8) |

Both kinds of endpoint cut longer inputs silently, at each model's standard limit (DeepInfra
reports 260, 388 and 516 tokens for an input of 2,000), as the in-house deployment probably
does too. MiniLM gives the same vectors locally and on DeepInfra (cosine similarity 1.000000 on
300 TMT chunks), so either can stand in for the other.

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

All the samples (decision 5), ingested with LLM enrichment into one tree, as production would
hold them:
- **TMT** (about 21,000 chunks): the realistic scale, with many near-duplicates such as
  requirement lists and analysis results. It is ingested already (`out/tmt-dv`), and its answers
  are cached.
- **The others:** SAF_FFDS, SAF_Profile and SAF_Blank (the SAF and UAF profiles), NIST_M-SysML,
  MDK_DocGen, OpenSUT (two projects), EOSS, GTRI, MDK_CSyncTest, cusa26 and the drone sample.
  Their enrichment should cost a few dollars at most.
- **TMT-2024x:** probably the same model as TMT, saved by a later Cameo. Two near-identical
  answers would make "the right chunk" ambiguous, so it is left out of the main index. It is a
  ready-made test of confusion between versions, if that matters later.
- **Results by project:** reported for each project, and for the whole. The drone sample (183
  chunks) stays the one small enough to check every result by hand.

### Queries, from four sources, each with its own ground truth

0. **A synthetic project with planted facts** (decision 9; `cameo_ingest.evaluation.synthetic`).
   - **The project:** the Kestrel Orchard Irrigation System, an invented orchard irrigation
     system, built in Cameo's own format. It has eight blocks, seven requirements with
     «satisfy» and «deriveReqt» links, two activities and three diagrams.
   - **Planted facts:** names and figures that appear nowhere else ("Brine Valve K7", "340
     milliseconds", "Verdant-3").
   - **The questions:** 14 facts, each asked twice, by hand: literally, with the model's own names,
     and as a paraphrase without them. That gives 28 questions, and their answers are the
     elements that hold the facts, known by construction.
   - **Checked:** a test ingests the project and checks that each answer's chunks contain the
     planted fact, so the answer key can't drift.
   - **In the index:** the project is ingested into `out/all` with the samples, so its facts are
     needles in a haystack of 28,000 chunks. It also checks the judges: one that misses these
     answers can't be trusted on the others.

1. **Structural questions, generated from the model.** Their answers are known by
   construction, so they need no judge:
   - by id: "What does REQ-1-OAD-0468 require?";
   - by relationship: "Which requirements is Maneuver Autonomously derived from?";
   - by diagram content: "Which diagram shows Monitor Power sending Power Level Status?";
   - by parameter: "What is the maximum phasing time in the wavefront calibration runs?".

   They share words with their answers, so they favour lexical search and flatter embeddings.
   They serve for regressions and coverage, not to choose a model by themselves.
2. **Natural questions, written by a strong LLM from a sampled chunk** ("doc2query"). The LLM is told
   to paraphrase rather than copy names where it can, and to tag each question with a
   category. The source chunk is relevant; other chunks are judged by pooling (below).
3. **The maintainer's spot check:** a random sample of the questions from both sources above is
   shown to the maintainer, who marks any that make no sense or that nobody would ask. Those
   point to faults in the generators, which are fixed before the questions are used. (Decision
   3: no gold set.)

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
  of question and chunk is judged 0, 1 or 2 by a panel, given the question and the chunk's
  text.
  - **Cached:** a pair is judged once, whichever configuration retrieved it.
- **The panel (decision 4):**
  - **Two models on every pair,** from different families, strong but cheap:
    `deepseek-ai/DeepSeek-V3.2` and `Qwen/Qwen3-235B-A22B-Instruct-2507`.
  - **A third, stronger model on the pairs they disagree on,** and on a check set:
    `moonshotai/Kimi-K2.5` or `deepseek-ai/DeepSeek-V4-Pro`.
  - **Claude:** labels a stratified check set of about 200 pairs by hand, in session, and
    settles a sample of the remaining disagreements.
  - **`google/gemma-4-31B-it`, the enrichment model, also judges the check set,** to learn
    whether a cheap judge would do for later runs.
- **Checking the judges:** each judge's agreement with Claude's labels is measured (Cohen's
  kappa). A judge that agrees poorly is dropped, and the final label is the panel's majority.
- **Budget:** a judgment reads about 800 tokens and writes a few. With about 300 questions and
  heavy overlap between configurations, the pools come to perhaps 6,000 to 10,000 pairs:
  - the two main judges, about $1 to $3 per full round;
  - the stronger one, on disagreements and the check set, well under $5;
  - embeddings, cents per model for all the samples ($0.005 to $0.01 per million tokens).

### Measures

- **Recall at 5, 10 and 20:** the context sizes a RAG prompt takes.
- **MRR at 10, and nDCG at 10 (graded):** per category and per corpus.
- **Contributions by chunk kind:** which kinds answer which categories, generated chunks
  included.
- **Cost:** embedding time and price per corpus and model, on a local CPU against DeepInfra.
- **Care with small numbers:** every configuration runs on the same questions, so
  differences are paired; they are reported with bootstrap confidence intervals.

## What is compared

- **The simulated production pipeline** is the baseline: 512-token windows with overlap, over
  `chunks.jsonl` and over the Markdown pages (see Decisions).
- **Dense retrieval** with the four target models:
  - **MiniLM** both locally and on DeepInfra, to check that the two give the same vectors;
  - **MPNet and e5-large** on DeepInfra;
  - **e5-small** in a local TEI container.

  The e5 models are run with and without their `query: ` and `passage: ` prefixes, in case the
  in-house pipeline doesn't add them.
- **Lexical retrieval:** BM25 over the same windows, to show what keyword search would add.
- **Hybrid retrieval:** BM25 with each dense model, by reciprocal rank fusion.

## Changes to try, each measured against the baseline

1. **Plainer chunk text:** links reduced to their labels (pages keep them), the trace line left
   to the metadata that already holds it, the qualified name shortened to its owning package,
   and the key text first (the requirement's id and text, the documentation). If it helps, it
   replaces `text` itself (decision 6).
   - **Meaning apart from structure (decision 11):** what an element means (its kind, name,
     documentation, requirement text, relationships in words) in its chunk; its structural detail
     (members, tagged values, configuration) in a separate detail chunk or file, so that neither
     dilutes the other.
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
| RE-01 | Inventory: chunk lengths in each model's tokens, what fills them (links, names, traces), and how the simulated 512-token windows fall; as a script and a research note. | Done: `scripts/chunk_inventory.py`, `docs/research/chunk-inventory-2026-09-30.md` |
| RE-02 | Endpoints and the embedding cache: the models on DeepInfra, their input limits, prefixes and speed. | Done: `cameo_ingest.evaluation.embed`, `scripts/embedding_check.py`. Local containers dropped (decision 8) |
| RE-03 | Corpora: ingest every sample except TMT-2024x into one tree, with LLM enrichment, reusing TMT's cached answers. | Done: `out/all`, 19 projects, 28,220 chunks; about 400 new LLM requests |
| RE-04 | Questions: the synthetic project (decision 9), the structural generator and the LLM question writer. A sample goes to the maintainer to spot-check for sense; the generators are fixed where it finds faults. | In progress: the synthetic project (28 questions), 88 structural and 75 natural questions; the spot check (`out/eval/questions/spot-check.md`) awaits the maintainer |
| RE-05 | The harness: the simulated pipeline (windows over chunks and over pages), indexes, dense, BM25 and hybrid search, measures with confidence intervals, the report and per-question pages. | Done for windows over chunks (`cameo_ingest.evaluation.harness`, `scripts/retrieval_eval.py`); windows over pages to come |
| RE-06 | Judging: the judge panel, with cached judgments; Claude's check set; agreement per judge; the panel's labels. | Not started |
| RE-07 | Baseline: the four models (at their standard limits; e5 with and without prefixes), dense alone, and BM25 and hybrid for comparison, on every project. | Preliminary: `docs/research/retrieval-baseline-2026-10-01.md`, before judging |
| RE-08 | Changes: plainer chunk text, splitting, titles for unnamed requirements, generated and ledger chunks included or not. | Not started |
| RE-09 | Recommendations: adopt what helps into the output (with a version bump), rewrite the README's RAG advice, and write down what to ask of the stack (model limits, overlap, prefixes). | Not started |

## Questions to raise with the stack's owners

The evaluation will put numbers on these. They are listed here so they can be asked meanwhile:
1. **Which model,** and at what input limit? MiniLM is usually run at 256 tokens, so a 512-token
   chunk would be embedded by half.
2. **How much overlap** between chunks, and does the splitter respect paragraphs?
3. **What is ingested:** `chunks.jsonl`, the Markdown pages, or both?
4. **For e5 models:** are the `query: ` and `passage: ` prefixes added?
5. **How many chunks** go into a prompt?
