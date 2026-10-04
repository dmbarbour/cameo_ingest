# Research: do descriptions reverse upward arrows? 2026-10-04

**Question.** On the eye charts, gemma-4 reverses 24% to 28% of arrows drawn pointing up
(`docs/research/vision-calibration-gemma4-2026-10-03.md`). Do diagram descriptions inherit this?
If so, the roadmap's arrow items (a filled head, a mid-line arrow, a margin on the arrows' rule)
would be worth a redraw of every sketch and a new description for each.

**Method.**
- **The tree:** the 0.16.1 release check's (`out/v0161/llm`), gemma-4 at DeepInfra.
- **The connections:** every sample diagram drawn whole (at most 25 shapes) was rebuilt from its
  layout. A directed connection counts as upward when its arrowhead is drawn more than 20 px above
  its tail.
- **The diagrams:** the 10 with the most upward connections, 175 connections in all.
- **The reading:**
  - three diagrams read whole: NIST's welding classification, FFDS's capability definition, and
    TMT's software hierarchy;
  - the other descriptions scanned for any sentence that states an upward connection backwards
    ("B is a kind of A", "B satisfies A", and so on); each sentence found was read.

## Results

- **Upward arrows are common.** In the 424 diagrams drawn whole that have any, there are 1,454
  upward connections against 818 downward. Generalizations and derivations point up.
- **No description states one backwards.**
  - The scan found six candidates, all false alarms. For example, "Arc Welding includes Submerged
    Arc Welding" states the generalization the right way round.
  - In the diagrams read whole, every "is a kind of" is stated the right way.
  - Where a description strays, it is in the wording, not the direction:
    - FFDS: "these functions refine specific requirements", where the model has only a plain
      dependency from the requirement to the function;
    - TMT: the sequencer is said to use interfaces it also realizes.
- **Why:** a description gets every connection, with its direction, as text beside the sketch
  (ADR-0012), and the model follows the text. Validation, which reads directions from the image
  alone, found 100% right on 12 of the tree's own sketches at 0.16.0.

## Decision

The arrow items stay deferred:
- a filled head;
- a mid-line arrow;
- a margin on the arrows' rule;
- direction in large modules.

They would cost a redraw of every sketch and a description for each, and descriptions don't show
the fault they would fix. They matter again only if images are read without their connection
lists.
