# Research: ledger and generated chunks, in or out of retrieval? 2026-10-05

**Question.** Plan RM (`docs/archive/plans/retrieval-measures-2026-10-05.md`, RE-08 of plan RE). Ledger
chunks list a package's items; generated chunks are the LLM's summaries and descriptions. Do they
help retrieval, or only crowd it? The maintainer's stack reads files, so it can't filter by kind:
what `rag/` holds is what it searches.

**Method.**
- **The tree:** `out/v019/on`, the samples and the fiction at 0.19.0 with the LLM: 83,804 chunks,
  of which 6,417 are ledger chunks and 6,454 generated.
- **The variants:** the same `rag/` files, less some kinds (`retrieval_eval.py --without`, plan
  RM-01). Nothing is rebuilt, and the embeddings are the same.
- **The systems:** e5-large without prefixes, BM25, and their fusion, each also reranked by
  Qwen3's 0.6B reranker; compared question by question with `compare_retrieval.py` (paired
  bootstrap, 95%).
- **The questions:**
  - the 226 standing questions (`questions-ra-th-is.jsonl`), against the release check's run;
  - 8 new list questions (`questions-rm.jsonl`, `fiction.lists()`, plan RM-03), what ledgers are
    for: a package's requirements with what satisfies each, its stakeholder needs, its
    instruments, its diagrams. Graded in parts, one per item.
- **What grading can't see:** a window answers only if it holds the answer's words. A generated
  summary that gives the answer in its own words gets no credit, and questions that only a
  summary answers ("what is this package for?") can't be graded by construction.

## Results

**The standing questions** (226). Changes against the full `rag/`; \* significant.

| System | Without ledgers: MRR@10 | Without generated: MRR@10 | Without both: MRR@10 | Without both: nDCG@10 |
|---|---|---|---|---|
| BM25 | 0.556 → 0.556 | 0.556 → 0.554 | 0.556 → 0.561 | 0.472 → 0.500\* |
| e5-large | 0.756 → 0.743\* | 0.756 → 0.771 | 0.756 → 0.769 | 0.629 → 0.667\* |
| e5-large + BM25 | 0.722 → 0.717 | 0.722 → 0.729 | 0.722 → 0.727 | 0.606 → 0.643\* |
| BM25, reranked | 0.735 → 0.734 | 0.735 → 0.773\* | 0.735 → 0.782\* | 0.607 → 0.665\* |
| e5-large, reranked | 0.761 → 0.768 | 0.761 → 0.792\* | 0.761 → 0.817\* | 0.655 → 0.708\* |
| e5-large + BM25, reranked | 0.767 → 0.772 | 0.767 → 0.793\* | 0.767 → 0.813\* | 0.659 → 0.707\* |

- **Without generated chunks,** every reranked system gains significantly (MRR@10 +0.026 to
  +0.038, nDCG@10 +0.023 to +0.032), and no measure of any system falls significantly.
- **Without ledgers alone,** little changes: e5-large's MRR@10 falls by 0.013, the only
  significant change. Without both, the gains are the largest: MRR@10 +0.045 to +0.056 reranked.
- **Is it grading?** For the hybrid, reranked, a generated window outranked the first answer in
  39 questions. Read one by one, 5 of those windows answer in other words (the catalogue's part
  summaries name the kinds of detector and of controller; the crossing's sequence says a train
  approaching sends rising barriers down again). The other 34 don't: a corridor's summary names
  its junctions but not their site ids, a package's summary its requirements' ids but not what
  they say, the kiosk's summary its computer but not its software. The gain is mostly real:
  generated windows push answers down.
- **Where they help:** 183 of the 226 questions have a generated window in the hybrid's reranked
  top 10, and 43 of those windows hold the answer's words.

**Each generated kind alone** (the standing questions): none accounts for the gain.

| System | Without summaries: MRR@10 | Without diagram descriptions | Without part summaries | Without part descriptions |
|---|---|---|---|---|
| BM25 | 0.556 → 0.554 | 0.556 → 0.555 | 0.556 → 0.547\* | 0.556 → 0.550 |
| e5-large | 0.756 → 0.758 | 0.756 → 0.753 | 0.756 → 0.749 | 0.756 → 0.746\* |
| e5-large + BM25 | 0.722 → 0.719 | 0.722 → 0.725 | 0.722 → 0.719 | 0.722 → 0.716 |
| BM25, reranked | 0.735 → 0.744 | 0.735 → 0.752 | 0.735 → 0.736 | 0.735 → 0.731 |
| e5-large, reranked | 0.761 → 0.765 | 0.761 → 0.769 | 0.761 → 0.764 | 0.761 → 0.753\* |
| e5-large + BM25, reranked | 0.767 → 0.772 | 0.767 → 0.770 | 0.767 → 0.769 | 0.767 → 0.759\* |

- **Summaries** (701) and **diagram descriptions** (2,870), each left out alone: small gains, none
  significant.
- **Part summaries** (2,200) and **part descriptions** (648): small losses; the part
  descriptions' are significant for three systems (nDCG@10 too).
- **Together they act as one:** they say the same things in other words, so when one kind is left
  out, another takes its place above the answer. Only leaving them all out clears the way.

**Kinds together** (the standing questions, MRR@10; \* significant):

| System | All generated out | All but part descriptions | All but part summaries and descriptions |
|---|---|---|---|
| BM25 | 0.556 → 0.554 | 0.556 → 0.556 | 0.556 → 0.558 |
| e5-large | 0.756 → 0.771 | 0.756 → 0.770 | 0.756 → 0.765 |
| e5-large + BM25 | 0.722 → 0.729 | 0.722 → 0.731 | 0.722 → 0.727 |
| BM25, reranked | 0.735 → 0.773\* | 0.735 → 0.769\* | 0.735 → 0.761\* |
| e5-large, reranked | 0.761 → 0.792\* | 0.761 → 0.792\* | 0.761 → 0.779\* |
| e5-large + BM25, reranked | 0.767 → 0.793\* | 0.767 → 0.793\* | 0.767 → 0.784 |

Keeping the part descriptions (648, one per module of a large diagram) gives up nothing: the gain
is the same as with every generated kind out. Keeping the part summaries too gives less.

**Image descriptions** (35 in the samples) were left out with the others, but the fiction has no
embedded images, so no question measured them. Unlike the rest, they hold what no other text
does: what the vision model read in an image.

**The list questions** (8). Changes against the full `rag/`; \* significant.

| System | Without ledgers: coverage@10 | complete@10 | MRR@10 | Without generated: coverage@10 | Without both: coverage@10 |
|---|---|---|---|---|---|
| BM25 | 0.502 → 0.471 | 0.250 → 0.125 | 0.205 → 0.329\* | 0.502 → 0.487 | 0.502 → 0.362 |
| e5-large | 0.792 → 0.708 | 0.625 → 0.500 | 0.556 → 0.550 | 0.792 → 0.792 | 0.792 → 0.698 |
| e5-large + BM25 | 0.583 → 0.542 | 0.500 → 0.375 | 0.427 → 0.331 | 0.583 → 0.583 | 0.583 → 0.458 |
| BM25, reranked | 0.677 → 0.625 | 0.500 → 0.375 | 0.667 → 0.562 | 0.677 → 0.688 | 0.677 → 0.583 |
| e5-large, reranked | 0.906 → 0.771\* | 0.625 → 0.500 | 0.906 → 0.698\* | 0.906 → 0.875 | 0.906 → 0.792\* |
| e5-large + BM25, reranked | 0.729 → 0.633 | 0.500 → 0.375 | 0.792 → 0.608 | 0.729 → 0.746 | 0.729 → 0.648 |

- **Without ledgers,** every system loses coverage and completeness; with 8 questions, only the
  best system's losses are significant.
- **Without generated chunks,** lists barely change.

## Decision

Option A (the maintainer, 2026-10-05: "If generated chunks are a big loss, then we must drop them
as implemented"; ADR-0028): summaries, diagram descriptions and part summaries leave `rag/`; part
descriptions and image descriptions stay. The pages and `chunks.jsonl` keep them all, by kind.
The options were A, B (every generated kind out) and C (all kept).

Ledgers stay: they answer lists, and cost the other questions little.

**Why the summaries crowd,** from their requests (the 0.19.0 store): they ask for a package's
"purpose, main elements, and how they relate", with the names as written, and 73% of the
package-summary inputs on the samples (85% of part summaries') hold no documentation at all, only
names and structure. The answers are inventories of names ("These sites include Harbour Road &
Abbot Lane, Harbour Road & Brindle Street, …"). Diagram descriptions get the legend and the
connections, names and arrows only, and narrate them. Requests that ask for what retrieval can
use are a next experiment.

## Changes

- 2026-10-05: the decision (option A, ADR-0028), in place of "pending the maintainer", and why
  the summaries crowd. Before: `2ba3394`.
