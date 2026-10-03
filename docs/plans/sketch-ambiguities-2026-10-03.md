# Plan: sketches that read as drawn, and a release check with the LLM, 2026-10-03

- **Status:** Approved on 2026-10-03 ("Go with 1 then 2"; on the cost of the release check,
  "NP"). CP1 done; CP2 measured and halted at its stop rule, for the maintainer to decide how
  trees are drawn (see SK-05). Type hierarchies as text, for search, are a tentative plan of
  their own (plan index).
- **Step prefix:** `SK`, so steps are `SK-01`, `SK-02` and so on
- **Addresses:**
  - The follow-ups of plan VA's live check
    (`docs/research/vision-autocalibration-two-models-2026-10-03.md`). Validation on the tree's
    own sketches found that most connections models miss are in sketches whose pictures are
    ambiguous, for gemma-4 and Qwen3-VL alike.
  - The maintainer's choice of 2026-10-03: "Go with 1 then 2". First fix the sketches; then one
    LLM run of the samples, checking the release end to end, with retrieval, before the real
    corpus.

## What the samples show (2026-10-03)

Two of the sketches that validation scored lowest were taken apart, then every diagram in the
samples and the fiction (3,246 diagrams, 25,409 shapes, 21,795 connections) was surveyed for
the same faults.

| Fault | Cause | How common |
|---|---|---|
| **Generalization trees drawn as floating stubs** | Cameo draws a tree of generalizations as a horizontal bar, a vertical bar up to the parent, and a short stub from each child to the bar. The bars are a view of their own, `Tree` (`baseShape`, `verticalBarX`, `verticalBarY`, `horizontalBarLeft`, `horizontalBarRight`, `horizontalBarY`), named by each member's `treeID`. The layout reader skips that view, so only the stubs are drawn, each with a hollow head on the bar, pointing at nothing. | 503 trees; 2,111 generalizations, of 3,083. In 326 trees no path reaches the parent at all: EOSS's "Instruments" shows five heads on a bar with nothing above it. In 464 trees the parent is above the bar; in 39, below. |
| **Shapes hidden by a frame** | Shapes of the same nesting depth are drawn in layout order. A frame drawn later around others (a `RectangularShape`, which Cameo draws transparent) is filled white over them, and only their names show. | 310 shapes, in 80 diagrams: the tree's parent in TMT's "Duration Analysis3"; ScrewClamp in Library's "InterfaceStandards". |
| **Connection labels drawn as numbered shapes** | `AssociationTextBox` (an association's name) and `MessageSignature` (a sequence message's) are views of their connection's text, but are drawn and listed as shapes, with numbers. | 54 and 111. |
| **Association-class links drawn as connections** | `LinkAttribute`, the line from an association to its class, is drawn solid. UML draws it dashed. | 67. |
| **Nesting read as connections** | Asked for connections, models also list a container and the shapes inside it. | Seen in validation. Not measured yet: validation scores connections found, not those invented. |

Object flows that end on pins, beside their actions, are drawn correctly. Sequence diagrams
repeat a lifeline's name on its line and activations; that belongs to the roadmap's "better
module boundaries", not here.

## Design

**Part 1: the sketches** (0.14.0).
- **Trees:**
  - The layout reader keeps `Tree` views, with their bars and base shape, and each path's
    `treeID`.
  - The diagram's graph lists its trees: the parent shape, the bars and the member connections.
  - The sketch, and the SVG for people, draw the bars and one hollow head where the vertical
    bar meets the parent. A member's stub keeps its line and loses its head.
  - The legend and connection list are unchanged: each generalization still reads child to
    parent.
- **Drawing order:** within a nesting depth, larger shapes are drawn first, so that a frame lies
  under the shapes inside it, as in Cameo.
- **Connection labels:** `AssociationTextBox` and `MessageSignature` join the decorations that
  are neither drawn nor listed. The connection's name is in the connection list already.
- **Association-class links:** `LinkAttribute` is drawn dashed.
- **Validation:**
  - **A new score:** connections invented (listed, but not in the diagram), so that misreadings
    like nesting are measured.
  - **A comparison script:** `scripts/validate_sketches.py` validates a fixed sample, larger
    than a run's, with an old and a new version. The sample is the same diagrams by key, and
    it includes a targeted stratum: whole diagrams with a tree, a hidden shape, an association
    class or a message label.

**Part 2: the release check** (no version of its own).
- **The run:** the samples and the fiction at 0.14.0, with gemma-4 at DeepInfra, 8 requests at
  once, in a new tree (`out/sk/llm`).
- **The store:** a copy of plan RA's store (`out/ra/llm-cache`), so that unchanged requests are
  free. The calibration and validation run on their own, as on a first run.
- **New requests:** every sketch's description, since every sketch changed (13 px text in 0.12.0,
  and part 1). Also the large diagrams' descriptions built from them, and the summaries plan UL
  changed.
- **Estimate:** 3,500 to 4,500 new requests, 1 to 1.5 h, $2 to $4. The last full build
  answered 2,862 new requests in an hour. `--llm-max-calls 6000` caps it.
- **Checks:**
  - the run's outcomes: no failures, nothing left incomplete;
  - the tree's invariants;
  - a reading of the descriptions of the six diagrams named above and six drawn at random,
    before (`out/ra/final-llm`, 0.7.2) and after;
  - retrieval on the fictional questions (`questions-ra.jsonl`, 210 questions, the same
    windows), against `out/ra/final-llm`, with the report's significance test.

## Steps

| Step | What | Status |
|---|---|---|
| SK-01 | **Trees:** `Tree` views and `treeID` in `layout.py`; `DiagramGraph.trees`; the bars and one head in `sketch.py` and `sketch_svg.py`; no head on members' stubs.<br>**Tests:** a fixture diagram with a tree, parent above and below the bar: one head, at the parent's edge, and none on the stubs; the legend unchanged. | Done: EOSS's "Instruments" now draws one bar and one head at the parent |
| SK-02 | **Drawing order:** larger shapes first within a depth.<br>**Tests:** a frame around a shape, listed after it: the shape's box is drawn over the frame. | Done: `diagram_graph.drawing_order`, shared by the PNG and SVG sketches |
| SK-03 | **Labels and association classes:** `AssociationTextBox` and `MessageSignature` as decorations; `LinkAttribute` dashed.<br>**Tests:** neither label is in the legend or drawn; the association class's line is dashed. | Done |
| SK-04 | **Validation:** connections invented, in the scores, the report and the one-line summary; `validate.sample` with the sample's size as parameters; `scripts/validate_sketches.py` (the sample by key, from a file or chosen; a targeted stratum; results as JSON and Markdown).<br>**Tests:** a reader that adds a connection per sketch is scored for it; the script on the fiction. | Done (fbb5235) |
| SK-05 | **Before and after,** on the samples and the fiction:<br>- 12 sketches per stratum, and 12 targeted, with 0.13.0 (a worktree at b2037c4) and with the fixes;<br>- for gemma-4, and Qwen3-VL;<br>- in a research note, with the sketches of the six diagrams named above.<br>**Also:** 0.14.0; README; a `--no-llm` tree compared with 0.13.0's, every difference explained (sketches, SVGs, legends without the labels). A few cents. | Measured, then halted for the maintainer (`docs/research/sketch-ambiguities-2026-10-03.md`): containment trees fixed on the way (a508528); members keep their heads, which reads better than one head (94de089); Qwen3-VL reads clean trees top-down. 0.14.0, README and the `--no-llm` comparison wait on the decision |
| SK-06 | **The release check's run,** as in the design. | |
| SK-07 | **The release check's findings:** outcomes, invariants, the reading of twelve descriptions, retrieval against `out/ra/final-llm`; in the research note and here. | |

## Checkpoints

| Checkpoint | Steps | Output |
|---|---|---|
| CP1: the fixes | SK-01, SK-02, SK-03 | Sketches with trees, frames under shapes, no label shapes, dashed association-class lines |
| CP2: measured | SK-04, SK-05 | Validation before and after; 0.14.0 |
| CP3: the release check | SK-06, SK-07 | The LLM tree, retrieval, the reading |

## When to stop and ask

- **A fix doesn't help:** the before-and-after comparison shows no gain on the targeted sketches,
  or a loss on any stratum. The maintainer then decides before the paid run.
- **Before the run:** if the sketches' changes call for more new requests than the estimate (a
  count of the tree's sketches is taken first), or for more than $5.
- **Retrieval falls** significantly on the fictional questions.

## Not in this plan

- **Sequence diagrams:** their lifelines, lines and activations repeat one name. That belongs to
  the roadmap's "better module boundaries".
- **A margin for the arrows' rule** (plan VA's follow-up).
