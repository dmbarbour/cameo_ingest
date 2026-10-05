# Plan: what a drawn diagram shows inside its shapes, 2026-10-05

- **Status:** Done on 2026-10-05 (0.19.0), and retired to the archive that day.
  - **Approved:** "That seems a good plan" (option A, on the diagram).
  - **Option C,** compartments in the vision legends, stays out: "it could improve feedback; on the
    other, it could overly bias the vision model". The roadmap has the maintainer's alternatives.
  - **After IS-05's measurement,** the maintainer kept it as it is, with no switch: "A … asking
    users to control them independently would be a recipe for confusion" (ADR-0027).
- **Step prefix:** `IS`, so steps are `IS-01`, `IS-02` and so on.
- **Builds on:** `docs/research/used-objects-2026-10-03.md` (BASE-013): Cameo saves a diagram's
  `usedObjects`, the elements it uses, and the tool reads them only for diagrams without a layout.

## Why

A drawn diagram shows more than its shapes:
- a block's compartments list its properties, operations and ports;
- a transition carries its trigger;
- a composite state holds its regions and substates.

The layout has views for shapes and lines, not for these. Only `usedObjects` records them. A
diagram's page and chunk say nothing of them, so "which values does the Riverbend Overview show
for its pumps?" has its answer spread over the blocks' chunks. Those chunks list every member,
whether or not the diagram shows it.

**What the samples hold:** 12,095 elements that drawn diagrams use but don't draw, in 594
diagrams.
- **Owner drawn:** for 9,397 (78%), the element's owner, or its owner's owner, is drawn on the
  diagram: all 2,408 triggers, 965 of 973 operations, and 3,531 of 4,509 properties.
- **The rest** are mostly connectors, connector ends and ports in internal block diagrams, whose
  owner is the diagram's context. It is drawn as the frame, not a shape, so they can't be checked
  this way.

## Design

- **Kept apart:** `Diagram.used` keeps `usedObjects` as saved. `shown` stays what is drawn, or
  for a diagram without a layout, its `usedObjects` (BASE-013).
- **Inside a shape:** an element the diagram uses but doesn't draw, whose owner (up to three
  levels up) is drawn as a shape on it. It is grouped under the first such shape, by kind:
  > [3] Drone: properties battery, mass; operations charge(); ports p1
- **Not checked:** the rest are counted, not listed: "Cameo lists 12 more as used; their owners
  aren't drawn here".
- **Where:** a block on the diagram's page and in its details chunk. Diagrams aren't package
  sections, and their sketches and legends don't change, so no LLM request changes.

## Steps

| Step | What | Status |
|---|---|---|
| IS-01 | `Diagram.used`; `view.inside_shapes(diagram)`: the shapes, with what each holds, and the count not checked. | Done (0.19.0): a line (a transition) holds what is inside it too, such as its trigger |
| IS-02 | **Output:** the page and the details chunk. A trigger reads by its event, an unnamed element by what describes it. | Done (0.19.0): holders by legend number and label, as the legend has them ("[1] «Block» Drone"); a transition's trigger by its event, an operation with "()"; a block in the details chunk |
| IS-03 | **Tests:** a fixture whose diagram uses a drawn block's property and operation, a drawn transition's trigger, and an element whose owner isn't drawn (counted). **The samples:** counts by kind; a reading of TMT's and the drone's. | Done: `tests/test_diagrams.py::test_what_shapes_hold`. On the drone and TMT, 241 diagrams gain the block: TMT's classes list their properties and operations, its states their do-activities and triggers |
| IS-04 | **The fiction** writes `usedObjects` as Cameo does: what is drawn, and the drawn blocks' members. **Questions** that start from a diagram ("which values does the Riverbend Overview show for its pumps?"), graded in parts, one per member shown. | Done: the fiction writes `usedObjects`; `fiction.shown()`, 4 questions, 8 with paraphrases (`questions-is.jsonl`); 254 fictional questions |
| IS-05 | **Measured** with and without, as plan TH measured hierarchies (a switch for the measurement, or two builds); the 210 standing questions too; a research note. | Measured: `docs/research/inside-shapes-2026-10-05.md`. The diagram questions gain greatly and significantly (coverage@10 from 0.03–0.25 to 0.77–1.00); the 210 lose a little, significantly (nDCG@10 −0.003 to −0.010; one paraphrase out of the top 10 for three systems). Stopped for the maintainer, as the plan says |
| IS-06 | **The release check;** docs (design, README, an ADR if a decision is made); a version. | Done: the maintainer chose to keep it, with no switch (ADR-0027). The 0.19.0 tree (`out/v019/on`): 670 diagrams say what their shapes hold; the invariants hold; no LLM request changed. Docs: design/diagrams, README |

## Checkpoints

| Checkpoint | Steps | Delivers |
|---|---|---|
| CP1: inside shapes | IS-01 to IS-03 | Pages and chunks that say what each shape holds |
| CP2: measured | IS-04 to IS-06 | Whether it helps, on questions that need it |

## When to stop and ask

- **If it doesn't help** the questions that need it: the block chunks may already serve.
- **If it hurts** the 210 standing questions.
