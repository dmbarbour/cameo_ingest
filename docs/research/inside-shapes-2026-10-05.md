# Research: does saying what shapes hold help retrieval? 2026-10-05

**Question.** Plan IS (`docs/plans/inside-shapes-2026-10-05.md`) adds to each drawn diagram's
page and details chunk what its shapes show inside them: a block's properties, operations and
ports; a transition's trigger; a state's regions. Does it help questions that start from a
diagram, and does it hurt others?

**Method.**
- **The fiction** writes `usedObjects` as Cameo does: what a diagram draws, and its blocks' values,
  parts and ports.
- **Questions** (`fiction.shown()`, `out/eval/fiction/questions-is.jsonl`): four, each asked
  literally and as a paraphrase: "Which properties and ports do the blocks on the Kiosk Structure
  diagram show?" They cover the Kiosk Structure (15 members), KOIS Structure (9), Crossing Sites
  (21) and the Riverbend Overview (59).
  - **Graded in parts,** one per member shown.
  - **A part is held** by the block's own chunk (its heading, the member's line, and the diagram
    among those it is shown in), or by the diagram's line for the block.
- **Two trees** of the samples and the fiction at 0.19.0, from one store, identical but for the
  block: `on` as released, `off` with the block patched out. Retrieval ran on both, over the 210
  standing questions, the 8 hierarchy questions and these 8.

## Results

**The 8 diagram questions, without → with:** every gain significant (paired bootstrap, 95%).

| System | coverage@10 | complete@10 | hit@10 | MRR@10 |
|---|---|---|---|---|
| BM25 | 0.03 → 0.77 | 0.00 → 0.50 | 0.25 → 0.88 | 0.06 → 0.62 |
| e5-large | 0.25 → 1.00 | 0.00 → 0.75 | 0.50 → 1.00 | 0.18 → 0.59 |
| e5-large + BM25 | 0.05 → 1.00 | 0.00 → 0.75 | 0.50 → 1.00 | 0.12 → 0.84 |
| BM25, reranked | 0.16 → 0.88 | 0.00 → 0.62 | 0.50 → 0.88 | 0.09 → 0.47 |
| e5-large, reranked | 0.03 → 0.88 | 0.00 → 0.62 | 0.13 → 0.88 | 0.03 → 0.53 |
| e5-large + BM25, reranked | 0.09 → 0.88 | 0.00 → 0.62 | 0.50 → 0.88 | 0.08 → 0.47 |

Without the block, a block's chunk holds its members and its diagrams together only when they
fall in one chunk. In the Crossing Sites diagram, that is true of 3 of 21 members.

**The 8 hierarchy questions:** unchanged.

**The 210 standing questions:** small losses, consistent in direction, and so significant.

| System | nDCG@10 | MRR@10 | hit@10 | Lost from the top 10 |
|---|---|---|---|---|
| BM25 | −0.004 | 0.000 | 0.800 → 0.800 | none |
| e5-large | −0.003 | 0.000 | 0.914 → 0.914 | none |
| e5-large + BM25 | −0.005 | −0.001 | 0.943 → 0.938 | hal-q04 (paraphrase) |
| BM25, reranked | −0.008 | −0.006 | 0.867 → 0.857 | pct-q15, rwt-q19 (paraphrases) |
| e5-large, reranked | −0.006 | −0.001 | 0.962 → 0.957 | pct-q15 (paraphrase) |
| e5-large + BM25, reranked | −0.010 | −0.004 | 0.957 → 0.952 | pct-q15 (paraphrase) |

**The cause** is mostly Port Calder's twelve corridor diagrams. Each lists 17 to 21 intersections
with their properties (site id, cabinet, ward…), so a question that names an intersection ("When
can people cross diagonally at Cormorant Road and Bramble Walk?") meets a diagram chunk naming it
too. The answer is then ranked lower, and for one question it falls out of the top 10.

## Open

The plan stops here for the maintainer: the block helps the questions it is for, a great deal, and
costs the others a little.
