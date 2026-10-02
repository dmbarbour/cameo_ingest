# Related facts brought together: an index across models, and threads

- **Date:** 2026-10-01
- **For:** plan RF, steps RF-03 to RF-06 (`docs/plans/related-facts-2026-10-01.md`)
- **Question:** do assembled chunks help find answers spread over several places?
  - **The index:** for each identifier, every place in every model that holds it.
  - **Threads:** for each derivation tree, its requirements with what satisfies and verifies
    them.
- **Answer:** the index, yes; threads, not measurably. Both are on by default.
  - **The index** brings answers spread over several companies' models into the top 10:
    coverage@10 rose from 0.77 to 0.97 with a reranker.
  - **Threads** made no significant difference to questions along a model's derivations
    (corrected on 2026-10-02, below), and cost nothing measurable.
  - **The per-line references** to each place's chunk cost more than they give, so they are off
    by default (`--line-refs`).

> **Corrected on 2026-10-02 (review AR-006):** the first version graded the within-model
> questions by bare names and ids, which was both too lenient (a test's or a block's name is
> in 13 to 20 chunks) and too strict (a derived requirement's id is only in its own chunk and
> the ledger, not in its source's "X is derived from this"). Their parts are now relationships,
> in the wording of every chunk that states them (`cameo_ingest.evaluation.grading`). The
> within-model table and what it says are corrected. The rest was measured again with the new
> grading and reproduced exactly.

## Setup

- **The projects:** the six fictional projects (`out/fic3`):
  - three rival proposals for the Riverbend works, all under one file name: the first one,
    Halvorsen's and Aquila's (`cameo_ingest.evaluation.fiction.rivals`);
  - three other projects.
- **The corpus:** the projects among the real samples, as `rag/` presents them.
- **Five variants:**
  - **base:** no assembled chunks;
  - **index:** with the index, references on;
  - **threads:** with threads, references on;
  - **both:** with both, references on;
  - **both, without references:** each line names only its project.
- **The questions:** 210 fictional questions.
  - **Single-fact (192):** the earlier ones, plus the rivals' own.
  - **Across models (10):** "Which proposals address RWT-REG-002, and how?", one evidence group
    per proposal.
  - **Within a model (8):** "Which tests verify the requirements derived from SN-02?", one group
    per relationship in the answer ("Warning Time Test verifies Warning Time B").
- **Measures:**
  - **coverage@10:** the share of the answer's parts that the top 10 hold between them;
  - **complete@10:** whether one window in the top 10 holds them all;
  - **MRR:** for the single-fact questions, as a harm check.
- **Systems:** BM25, e5-large, bge-large and their hybrid, alone and reranked (Qwen3-Reranker
  0.6B over the top 30).

## Results

\* marks a change from base whose 95% interval (paired bootstrap) excludes zero.

**Across models (10 questions):** coverage@10, then complete@10.

| System | Base | Index | Index and threads, no references |
|---|---|---|---|
| BM25 | 0.62, 0.00 | 0.83\*, 0.20 | 0.90\*, 0.60\* |
| bge-large | 0.70, 0.00 | 0.77, 0.20 | 0.80, 0.50\* |
| bge-large + BM25 | 0.80, 0.00 | 0.93, 0.20 | 0.97\*, 0.60\* |
| BM25, reranked | 0.70, 0.00 | 0.97\*, 0.20 | 0.97\*, 0.60\* |
| bge-large + BM25, reranked | 0.77, 0.00 | 0.97\*, 0.20 | 0.97\*, 0.60\* |

**Within a model (8 questions):** coverage@10, then complete@10.

| System | Base | Threads | Index and threads, no references |
|---|---|---|---|
| BM25 | 0.77, 0.50 | 0.79, 0.62 | 0.67, 0.38 |
| e5-large | 0.85, 0.50 | 0.94, 0.50 | 0.94, 0.62 |
| e5-large, reranked | 0.96, 0.75 | 1.00, 0.62 | 1.00, 0.75 |
| bge-large + BM25, reranked | 0.90, 0.50 | 1.00, 0.75 | 0.94, 0.62 |

No change is significant: with eight questions, every interval includes zero.

**Single-fact questions (192), MRR:**

| System | Base | Index | Index and threads, no references |
|---|---|---|---|
| BM25 | 0.57 | 0.56 | 0.55 |
| bge-large | 0.76 | 0.72\* | 0.72\* |
| bge-large + BM25 | 0.70 | 0.68 | 0.68 |
| bge-large + BM25, reranked | 0.81 | 0.80 | 0.79 |

## What this says

- **The index finds answers across models.**
  - **Keyword search finds the entry:** a question naming a requirement's id finds the entry
    that lists every model holding it, with what each says. Almost every part of the answer is
    then in the top 10, whatever each company's structure: requirements copied with the
    customer's ids, ids cited in documentation, a tagged value, another requirement's text.
  - **This is the maintainer's first need,** "requirements to source files": each line names
    the project by its short id, which `rag/meta/_sources.json` resolves to the files.
- **The per-line references cost more than they give.**
  - **The cost:** each reference (`[9ffd7a2c:14d101e0b1d2]`) adds about 15 tokens to a line, so
    an entry for an id held in many places splits into more parts, and its answer over more
    windows.
  - **The gain from dropping them:** complete@10 across models rose from 0.20 to 0.60.
  - **What remains:** the project's short id on each line is enough to find the source file;
    `--line-refs` adds the chunk's.
- **Threads make no measurable difference within a model.**
  - **The measure:** coverage rose with most systems and complete@10 moved both ways; no
    change is significant on eight questions. (The first version of this note found one
    significant gain, which the corrected grading doesn't confirm.)
  - **The threads measured were flawed (review AR-027):** a thread split into parts lost its
    first line's indentation, so a part could show a requirement as derived from the wrong
    one, and a part that starts inside the tree doesn't say what its first lines derive from.
    The first is fixed (0.5.3); repeating each part's ancestors is worth trying and measuring.
  - **They stay on:** they cost nothing measurable for single facts, and they are the one place
    a model's derivation tree reads whole.
- **For single facts, the assembled chunks cost little.**
  - **Without a reranker:** index entries sometimes outrank the chunk that answers (bge-large
    alone: 0.76 to 0.72).
  - **With a reranker:** no measurable cost.

## On the real samples

- **Counts:** 927 index entries (1,336 chunks with parts) and 39 threads (the drone sample's
  derivations among them). TMT has none: it has no derive relationships.
- **Time:** about 12 seconds with the rest of a run's tree files.
- **An example:** in TMT, the entry for `REQ-1-OAD-0468` pairs the live requirement with a
  deleted copy that cites the same id in its text, a link no relationship records.

## Limits

- **Small sets:** 10 questions across models and 8 within, written by the models' author. The
  fictional derivations are shallow (two or three levels).
- **Long entries still split:** an id held in many places makes an entry of several parts, and
  a whole answer then spans several windows. Ordering lines so that each part holds one model
  whole might help.
- **Facet lists** (requirements sharing a tag value) are deferred: TMT's run to hundreds of
  requirements a value, and choosing the tags needs heuristics with one example to test them
  on.
