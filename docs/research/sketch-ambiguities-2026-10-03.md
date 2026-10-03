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

## Reading guides (the maintainer's decision, 2026-10-03)

"A prompt informs how to read a diagram when we're clearly in a position to know." Each
request that sends a sketch now explains the drawing conventions that sketch uses, one sentence
each, chosen from its graph. The guide is part of `diagram-description` v6,
`module-description` v3 and validation's `eye-sketch` v2.

**Measured:** both samples, both models, the same sketches with and without the guide. One
sketch, TMT's "Observatory Configuration Data Types" (23 connections), got an empty answer
from Qwen3-VL with the guide, `{"shapes": [], "connections": []}`. It is left out of both
columns below. A single answer is a single sample, and with it Qwen3-VL's targeted stratum fell
from 72% found to 46%.

| | Without the guide | With it |
|---|---|---|
| gemma-4, 48 sketches: names, found, directions, invented | 98%, 75%, 97%, 37% | 96%, 80%, 95%, 26% |
| gemma-4, tree members found, the right way round (of 68) | 51, 50 | 47, 47 |
| Qwen3-VL, 46 sketches: names, found, directions, invented | 96%, 71%, 96%, 28% | 95%, 77%, 97%, 26% |
| Qwen3-VL, tree members found, the right way round (of 68) | 46, 28 | 47, 31 |

- **Both models find more connections** with the guide (gemma-4 +5 points, Qwen3-VL +6).
  gemma-4 invents a third fewer.
- **Modules gain most** for gemma-4: 72% → 81% found.
- **Qwen3-VL's top-down reading of trees** improves a little: 28 → 31 of 68 the right way
  round. The guide doesn't cure it.
- **gemma-4's tree members** dip by 3 or 4, within the noise of single answers.

The guide is adopted.

## The release check (SK-06, SK-07)

**The run** (0.14.0):
- **What:** the samples and the fiction, with gemma-4 at DeepInfra, 8 requests at once,
  from a copy of plan RA's store.
- **Calibration:** the run calibrated first, and found today's defaults. Validation warned of
  medium diagrams (62% of connections found) and modules (80%), as expected.
- **The build:** 27 projects in 56 min.
- **Requests:**
  - 2,451 new, about $1.50 to $2, below the estimate. TMT and TMT-2024x share many identical
    diagrams, asked once.
  - 3,656 answers from the store.
  - None failed. 265 diagrams were too small to describe, as in the last full build.
- **Invariants:** the tree's hold.

**The reading:** descriptions of the named diagrams and six at random, against
`out/ra/final-llm` (0.7.2).
- **Trees, read right:**
  - "Specialized Animals Inheritance" said "Dog is generalized by House Dog and Wild Dog",
    backwards; now "Dog is the parent of House Dog and Wild Dog".
  - "Duration Analysis3" called the six scenarios "generalizations of the Duration Analysis
    Context"; now the context "serves as a general type" for them.
- **A sequence diagram:** "FFDS Context Interaction" was two modules, its description in "parts"
  about "sections". The label boxes no longer count as shapes, so it is one diagram again, and
  its description follows the messages in order.
- **The rest:** about the same, with no description worse.
- **But the reading found a loss.** The 0.7.2 description said the Maintainer sends "Sig
  StartTheSystem"; the 0.14.0 one, that the Maintainer sends nothing.
  - "Sig StartTheSystem" is the signature of the message "Start System", shown in its label box.
  - With label boxes no longer shapes, nothing carried that text any more.
  - **Fixed in 0.14.1:** a label box's text joins its connection's, where the model's names
    don't say it already: "Start System (Sig StartTheSystem)", "Start Fire Propagation
    Modeling(AreaOfInterest)".
  - The 0.7.2 description had been wrong too: the Operator sends that message, not the
    Maintainer.
- **The tree:** rebuilt at 0.14.1 in 5 min, with 22 new requests. FFDS's description now has
  "the Operator sends Start System (Sig StartTheSystem)".

**Retrieval:** the 210 fictional questions, on `rag/`, as plan RA measured them: e5-large, BM25,
their fusion, and each reranked by Qwen3-Reranker-0.6B.
- **The trees:** `out/ra/final-llm` (0.7.2) against `out/sk/llm` (0.14.1). The new tree also
  holds Kestrel Orchard Irrigation, a fictional project added after plan RA: distractors for
  these questions.
- **The result:** no measure moved significantly (paired bootstrap, 4,000 rounds, 95%).
  - Hit@10 and complete@10 are unchanged for the dense, fused and reranked systems.
  - MRR@10 moved by at most ±0.007.
  - e5-large reranked has hit@10 0.97 and MRR@10 0.78 in both.
- **Why so little:** these questions ask about the models' facts, which the deterministic text
  carries. Descriptions are a small share of the chunks they compete with.

## Open

- **Decided:** the trees stay as drawn (B), with reading guides in the prompts.
- **The prompt hint,** done as reading guides (above). It helps both models, though it doesn't
  settle Qwen3-VL's reading of clean trees.
- **Follow-ups:** sequence diagrams; lines between undrawn ends.
