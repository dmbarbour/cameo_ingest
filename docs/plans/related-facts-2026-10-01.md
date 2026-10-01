# Plan: related facts brought together, 2026-10-01

- **Status:** Proposed on 2026-10-01, and revised the same day with the maintainer's answers
  (Decisions). In progress.
- **Step prefix:** `RF`, so steps are `RF-01`, `RF-02` and so on
- **Addresses:** the maintainer's request of 2026-10-01. The maintainer leans towards keyword
  search (BM25) to find related facts, since requirements and other items are named and looked
  up by keyword. The request is preprocessing that finds related facts and requirements
  *within* a model, so that they are already close together for searching, tracing and keeping
  provenance.
- **Related:** plan RE (retrieval evaluation), whose fictional projects (RE-10) measure this
  without judges. The tentative plan for keyword search and a workbook export (plan index)
  overlaps with the concordance below.

## Decisions

All answered by the maintainer on 2026-10-01.

| # | Question | Decision |
|---|---|---|
| 1 | Which tracing matters most | From whatever the RAG returns back to the source file: "requirements to source files". The RAG holds thousands of files, not only models, and locating things in it is troublesome. Fine-grained tracing within a model is an opportunistic convenience, used where it makes sense. |
| 2 | How requirements are structured | Unknown, and not consistent: the models come from several companies competing for one contract, with little guidance beyond "provide models in Cameo". Nothing may assume one structure. |
| 3 | Rerankers | Stand-ins on DeepInfra. No local models: the maintainer's machine can't take the load (plan RE, decision 8). |
| 4 | Size | Repetition is welcome where it helps comprehension. |
| 5 | Provenance in assembled chunks | A trace on every line is too long. Short logical ids on each line, resolved elsewhere (to file paths, locators and so on), are worth trying as an experiment, behind a switch. |

**What follows for the design:**
- **Source files first:** every chunk file says which input file it came from: by full path in
  its metadata, and by a short id in its text, which a table resolves to the paths. Paths
  themselves stay out of the text, since some are longer than a whole window.
- **Across models:** a requirement asked about may be answered in several companies' models, so
  an index from requirement ids and names to every model, element and file that mentions them
  serves "requirements to source files" across the corpus, whatever each model's structure.
- **Within a model:** trace cards and threads come after, where a model's relationships make
  them worthwhile.

## Why

A tracing question needs several facts, which sit in several chunks:
- **Where the facts are:** a requirement's chunk says what it requires; its parent's chunk why;
  the chunk of the block that satisfies it how; a test case's chunk how it is checked.
- **What retrieval returns:** top-k retrieval returns chunks one by one, and each must be
  found on its own merits.
- **What keyword search sees:** it matches the terms of the question, an id or a name, and
  only the chunk that names them scores.
- **The evidence so far:**
  - **Trace and multi-hop questions:** the fictional ones (RE-10) are found less often than
    lookups.
  - **Behaviour:** activities and state machines are the hardest to find.
  - **Ids:** keyword search finds them, and embeddings rarely do.

**Where relatedness lives in the samples** (requirements, `out/all-plain2`):

| Project | Requirements | Relationships touching them | Neighbours per requirement (median / 90th / max) | Derivation depth | Requirement ids cited in other text |
|---|---|---|---|---|---|
| Package_Delivery_Drone | 42 | DeriveReqt 41 | 1 / 4 / 12 | 3 | 0 |
| SAF_FFDS | 25 | custom refinement and imposition stereotypes (42) | 2 / 4 / 5 | 1 | 0 |
| OpenSUT_overview | 12 | Satisfy 11 | 1 / 2 / 2 | 1 | 1 |
| TMT | 4,284 | Refines 695, a few others | 0 / 1 / 42 | 1 | 319 |

Models built in SysML relate their requirements with relationships. TMT, imported from DOORS,
does it otherwise:
- **Nesting:** 4,178 of its 4,284 requirements sit under another requirement (DOORS sections
  and headings).
- **Facet tags:** for example `Applicable_Subsystems`, on 2,892 requirements, and
  `Acceptance_State`.
- **Ids cited in text:** 319 citations.

Preprocessing has to serve both kinds of model.

## What "related" covers

All of it can be read from the model, deterministically, with no LLM:
1. **Relationships:** derive, satisfy, verify, refine, trace, copy and allocate, and custom
   stereotyped dependencies such as SAF's refinements.
2. **Hierarchy:** requirements nested in requirements (DOORS sections), and package containment.
3. **Facets:** tagged values that many requirements share (applicable subsystems, acceptance
   state, release).
4. **Citations:** the ids and names of other elements, mentioned in requirement text,
   documentation or notes.
5. **Structure and behaviour:** parts, ports and connectors; actions allocated to blocks; the
   state machines a block owns.
6. **Diagrams:** the elements shown together.

## Forms to try

Each is a new kind of chunk, in `chunks.jsonl` and as files in `rag/`. Each fact in it keeps its
source.
- **A. Trace cards** (one hop): one per requirement, and one per block that satisfies or is
  allocated something. The element's own text comes first, then a line per related element,
  for example:
  - "satisfied by Chlorine Contact Tank: a serpentine tank that holds chlorinated water... [3]";
  - "verified by CT Compliance Test [4]";
  - "derived from RWT-REG-002: the works shall achieve 4-log inactivation... [5]".
  - **What it gives keyword search:** a search for the id finds, in one chunk, the facts one
    step away.
- **B. Threads:** one per top-level requirement or stakeholder need. It is the derivation or
  DOORS hierarchy, as an outline down to the elements that satisfy the leaves and the tests that
  verify them. It answers "where does this come from" and "what implements this", whole.
  Threads are split into parts, each part repeating its path from the root.
- **C. Facet lists:** one per value of a facet tag, such as "Requirements applicable to M1CS
  (142)", listing each with its id and title. They answer "everything about subsystem X".
- **D. Concordance:** one entry per id or name, listing every place it is mentioned, with the
  sentence and its source: the index at the back of a book.
  - **What it gives keyword search:** a query naming an item finds one entry pointing to all its
    mentions, including the citations in text that no relationship records.
- **Deferred: graph bundles** (communities of the relationship graph, as modules are found in
  diagrams). They are harder to explain to a reader than A to D.

**Provenance in assembled chunks:**
- **Inline:** each line ends with a short reference such as [3].
- **At the end:** a Sources block lists each reference with its trace locator, followed by
  the usual Source and Trace lines.
- **Their derivation:** "assembled", deterministic, and listing the inputs, as generated text
  lists its inputs today.
- **Why in the text:** a RAG tool that reads files keeps only their text, so the sources must
  be in it.

**Costs:**
- **Duplication:** assembled chunks repeat facts that the element chunks hold, so the index
  grows; that is part of what is measured.
- **No LLM:** none of this needs one.

## How to measure

- **New fictional questions, needing several facts:**
  - "Which tests verify the requirements derived from SN-02?";
  - "What do the requirements satisfied by the Backwash System require?";
  - "Which requirements apply to subsystem X?";
  - "Which requirements cite PCT-SYS-0302?".
- **The traffic project grows DOORS-like structure:** requirements nested under sections,
  facet tags, and ids cited in text.
- **Measures:**
  - **Complete in one window:** every evidence phrase in a single retrieved window.
  - **Coverage at 5 and 10:** the share of the evidence phrases found among the top windows.
  - **A harm check:** hits and MRR on the existing 178 fictional questions.
- **Systems:**
  - **BM25:** the maintainer's lean.
  - **Dense:** e5-large and bge-large.
  - **Hybrid:** fused at a lower weight for BM25.
  - **A reranker:** if one is agreed (below).
- **Real samples:** checked by eye on TMT and Package_Delivery_Drone; judged later only if
  needed.

## Rerankers

- **The in-house list:** `BAAI/bge-reranker-v2-m3`, `cross-encoder/ms-marco-MiniLM-L-12-v2`
  and `cross-encoder/ms-marco-TinyBERT-L-2-v2`.
- **What DeepInfra serves:** none of those. It has Qwen3-Reranker (0.6B, 4B, 8B) and NVIDIA's
  `llama-nemotron-rerank-vl-1b-v2`, a different and larger kind of model.
- **Why one would help:**
  - **BM25 alone:** it finds what is named and misses paraphrases (fictional paraphrases: MRR
    0.30 against 0.74 for bge-large).
  - **Keyword search, then a reranker:** retrieving with keywords and reordering by meaning
    keeps the keywords' strength and covers the weakness.
- **How to test one:** either a Qwen3 reranker on DeepInfra as a stand-in, or the TinyBERT
  cross-encoder (about 4 million parameters) locally, on the CPU, under a memory cap.
  - **Local runs:** plan RE's decision 8 rules out local models, so only with the maintainer's
    agreement.

## Steps

| Step | Work | Status |
|---|---|---|
| RF-01 | Source files in every chunk file: the input paths (with archive chains) in each file's metadata, a table from each project's short id to its files, and short ids in the text's source line behind a switch. | Done: `source_id`, `source_file` and `source_files` in `rag/meta/<project>/<sha256>.json`; `rag/meta/_sources.json`; `--rag-source trace|id`, set for the whole tree. Paths never go in the text: some are longer than a window (the maintainer, 2026-10-01). Nor do file names, which can be very long and repeat across groups: chunk text names a project by a label, the start of its file name and its short id (`TMT [9ffd7a2c]`; 0.5.2). Also `CAMEO_INGEST_DEST` for the output tree, in place of `-o` |
| RF-02 | Rerankers: Qwen3-Reranker on DeepInfra (decision 3) in the harness, reordering the top candidates of BM25, dense and hybrid search; measured on the fictional questions. | Not started |
| RF-03 | An index across models: requirement ids and names (and other ids) to every model, element and source file that mentions them. Fictional: two companies' models answering one set of requirements. | Not started |
| RF-04 | Questions and measures: cross-model and multi-fact questions in the fictional projects; DOORS-like structure in one of them; grading that wants every evidence phrase. | Not started |
| RF-05 | Within-model forms (trace cards, threads, facet lists) where relationships make them worthwhile, with short logical ids per line behind a switch (decision 5). | Not started |
| RF-06 | Evaluate and adopt what helps (defaults, the README's advice, a version bump). | Not started |

RF-01's inventory of relatedness (the table under "Why") is done for requirements.

## Questions for the maintainer

Answered on 2026-10-01: see Decisions.
