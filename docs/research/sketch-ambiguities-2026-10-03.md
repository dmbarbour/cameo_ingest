# Research: sketches that read as drawn, before and after plan SK, 2026-10-03

**Question.** Plan SK fixed four faults in the sketches that plan VA's validation pointed to:
- generalization trees drawn as floating stubs;
- frames drawn over the shapes inside them;
- connection labels drawn as numbered shapes;
- association-class lines drawn as connections.

Do the vision models read the fixed sketches better?

**Method.**
- `scripts/validate_sketches.py`:
  - one sample of the samples' and the fiction's diagrams, chosen by key;
  - drawn and asked once with 0.13.0 (a worktree at cb69dad) and once with plan SK's code;
  - both runs scored alike, by this version's measures.
- **The general sample:** 48 sketches: 12 small diagrams, 12 medium, 12 modules of large ones,
  and 12 whole diagrams with one of the faults.
- **The tree sample:** 24 whole diagrams with a tree, from ten projects.
- **The models:** gemma-4 at the default sizes; Qwen3-VL at its calibrated sizes (2 px lines,
  modules of 36, its own general sample). Single answers at temperature 0.1.
- **Tree members:** found and read the right way round, counted on the trees whose members all
  point at the base shape (16 diagrams, 68 members). The shapes' numbers are mapped between the
  versions.
- **Cost:** a few cents.

## What the comparison found on the way

- **Containment trees.** Cameo draws more than generalizations as trees: a package's contents,
  for one, from the package. The first drawing put a generalization's triangle at the base of
  every tree, wrongly saying "kind of". Now:
  - a tree has a head at its base only when every member points there, in the members' style;
  - its bars are dashed for dependency-like kinds;
  - a containment tree has no head at all.
- **One head or several.** Two ways of drawing a tree were measured on gemma-4:
  - (A) the UML style: one head at the parent, none on the stubs;
  - (B) the bars and the parent's head, with each stub keeping its own head.

  | gemma-4, 68 tree members | Before | A | B |
  |---|---|---|---|
  | Found, either way round | 41 | 44 | 51 |
  | Found the right way round | 41 | 39 | 50 |

  With A, gemma-4 found a few more members but read fewer the right way round. B does better
  on both, and is what plan SK now draws.

## Results

**gemma-4,** general sample (48 sketches):

| Sample | Before: found, directions right, invented | After |
|---|---|---|
| Small | 94%, 92%, 19% | 94%, 92%, 35% |
| Medium | 78%, 97%, 32% | 78%, 100%, 33% |
| Modules | 73%, 100%, 32% | 72%, 96%, 40% |
| Targeted | 61%, 88%, 41% | 64%, 100%, 41% |
| All | 75%, 96%, 32% | 75%, 97%, 37% |

The small diagrams' invented connections come from one sketch, a TMT collaborator view whose
picture is mostly dashed lines between things that aren't drawn as shapes. Its two drawings
differ only in which of two boxes is on top. gemma-4 listed 5 connections for one and 14 for
the other: the noise of single answers, on a confusing picture.

**gemma-4,** tree sample: connections found 73% → 79%, directions right 96% → 97%; tree
members as in the table above (41 → 51 found, 41 → 50 right).

**Qwen3-VL:**

| Sample | Before: found, directions right | After |
|---|---|---|
| General, all 48 | 69%, 84% | 70%, 82% |
| General, targeted | 66%, 46% | 72%, 48% |
| Tree sample, 24 | 69%, 91% | 78%, 75% |
| Tree members, 68 | 34 found, 33 right | 46 found, 28 right |

- **Finding members:** the trees help Qwen3-VL find which children belong to which parent:
  12 more members.
- **Directions:** it reverses more. Most of the loss is one diagram, MDK_DocGen's "Specialized
  Animals Inheritance":
  - after: a clean, textbook hierarchy of two trees, two levels each. Qwen3-VL found all 12
    generalizations and listed every one from parent to child, against the triangles;
  - before, with only the stubs and their heads, it read all 12 the right way round;
  - with a clean tree, it reads top-down, like an organization chart.

  Gains elsewhere: EOSS's "Instruments" 0 → 5 right, OpenSUT's block diagram 1 → 4, TMT's
  duration analyses 1 → 3.

**Other things these samples show:**
- **Sequence diagrams:** their messages join activations, while models name the lifelines.
  Every message counts as missed and as invented: about a third of the invented connections
  in the targeted samples. They are left to the roadmap's "better module boundaries".
- **Messy layouts:** in TMT's "Duration Analysis" diagrams, the tree's bar runs along the edge
  of an unrelated shape, and both models read the children as joined to it. No drawing rule
  fixes that layout.
- **Lines between undrawn ends:** some diagrams draw connections whose ends aren't shapes in
  the sketch (the collaborator view above). They invite invented connections.

## What this means

- **The sketches are now correct** where they were wrong: trees reach their parent, frames lie
  under their contents, labels aren't shapes, and association classes hang by dashed lines.
  The SVG sketches for people gain the same.
- **gemma-4,** the configured model, reads the fixed sketches as well or better on every
  measure but one: invented connections. The change there is the noise of one confusing
  diagram. On trees it gains clearly: 41 → 50 members found the right way round.
- **Qwen3-VL** finds more of the trees' members, but reads clean trees top-down, against
  their arrowheads.
- **Directions reach the descriptions as text in any case.** What the picture must show is
  which shapes are joined, and there both models gain.

## Open

- **For the maintainer:** keep the trees as drawn (B), knowing that a model like Qwen3-VL may
  read clean trees top-down? Or draw the trees only for the model that reads them better,
  which calibration would then have to measure (a further card family)?
- **A hint in the prompts,** such as "in a tree, each triangle marks the parent", might settle
  Qwen3-VL's reading. The descriptions are asked again at the release check anyway, so a
  template change now would cost nothing extra there.
- **Follow-ups:** sequence diagrams; lines between undrawn ends.
