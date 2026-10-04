# Research: what a diagram's `usedObjects` hold, 2026-10-03

**Question.** The roadmap noted that "Elements shown" (BASE-013) was filled from `xmi:idref`
only, which Cameo may not use in a diagram's `usedObjects`. Is the list empty where it matters,
and what would `usedObjects` add?

**Method.**
- **Survey:** every `.mdzip` in `samples/` (14 files, 3,341 diagrams), parsed with the library
  (`pipeline.parse_project`, `load_layouts`).
- **Measured:** each diagram's `usedObjects`, against the elements its layout draws.

## How Cameo writes them

- **The form:** always `<usedObjects href='#id'/>` inside `diagramContents`, never `xmi:idref`.
  There are 63,485 of them in the samples.
- **Before this fix:** the XMI's list was always empty. A drawn diagram's list came from its
  layout alone, and a diagram without a layout listed nothing.

## Diagrams without a layout: tables

- **The count:** 321 diagrams have no layout. 122 of them have `usedObjects`: 3,850 elements in
  all.
- **What they are:** almost all tables. In TMT they are Generic Tables (926 elements),
  Instance Tables (455) and Requirement Tables (250). Matrices and relation maps have none.
- **What they hold:** the table's rows as last saved. TMT's "APS Requirements" lists its 86
  requirements, and "Actions and Constraints" its 204 actions.
- **So:** the file stores a table's configuration *and* its rows when last saved. Only the
  cells are computed, and they come from the rows' own properties, which the model holds.

## Drawn diagrams: what is shown inside shapes

- **Used but not drawn:** 12,095 elements, in 594 of the drawn diagrams. They are mostly:
  - properties, operations and ports listed in compartments;
  - triggers on transitions;
  - connector ends, regions and states inside other shapes.
- **Drawn but not used:** 2,920 elements.
- **So:** `usedObjects` and the layout disagree both ways. The layout is what the sketch, the
  graph and the pages describe, so it stays the source for drawn diagrams.

## Result (BASE-013, finished)

- **The change:**
  - `xmi.py` reads `usedObjects`' `href='#id'`;
  - a drawn diagram lists what it draws;
  - a diagram without a layout lists its `usedObjects`.
- **What changes:**
  - a table's page lists "Elements shown when last saved", its rows;
  - each listed element's "Shown in diagrams" names the table. In TMT, 2,213 element chunks have
    that line, up from 1,853.
- **LLM requests:** 44 of about 3,300 change in TMT, NIST_M-SysML, SAF_FFDS and MDK_DocGen.
  They are package summaries whose pages now carry those lists.
- **Open:**
  - recomputing tables' cells (roadmap);
  - whether a drawn diagram should also name what it shows inside shapes.
