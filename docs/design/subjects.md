# Design: subjects for discovery

How a model's diagrams are split into subjects, for browsing and for grouping search results
(`subjects.py`). Decision: ADR-0031. Plan SB (`docs/plans/subjects-2026-10-06.md`) and
`docs/research/subjects-2026-10-07.md` hold the study.

## Families and items

- **A family** is a set of versions of one model, by ADR-0020's groups (`groups.find` on the
  fingerprints), or one model alone. The newest version names it.
- **Its items** are its diagrams, each once: the newest version's copy, listing every version that
  holds it. For each, from the projects' catalogs: its package path, its owner (when that isn't a
  package: many diagrams are named only "Attributes"), its about text, the elements it shows, and
  where those sit (their owners' paths).
- **A family under `MIN_ITEMS` (8) diagrams** isn't split: its packages are its one view.
- **Targets:** about the square root of half the diagrams, 2 to 15 subjects (`target`).

## Views

| View | How | When it comes first |
|---|---|---|
| The LLM's ways (`ways-1` to `ways-3`) | `SUBJECTS_PROPOSE`: an outline (packages three deep with diagram counts, 60 example diagrams) to about three ways, each a principle and labelled subjects; then `SUBJECTS_ASSIGN`, 30 diagrams a request, batches cut by package | When every way assigned at least 95% of the diagrams |
| Shared elements (`shared`) | Louvain on a graph of diagrams: an edge per element two diagrams show, weighted by the log of how rare it is; half that for an owner they share; half for a relationship between what they show. Merged down to the target, groups under 3 always; a diagram that shows nothing goes by its package. Labelled by distinctive words, leaving out those in over 30% of the about texts | When the tree has no LLM, the proposal failed, or a way left over 5% unsorted |
| Packages (`packages`) | The package tree, cut at the depth whose number of groups is nearest the target | For a family too small to split |

- **Unsorted diagrams** stay under "Not sorted yet". Placing them by their shared-element group's
  majority matched the LLM's own choice only 49% of the time.
- **Reproducible:** the graph is built and merged in sorted order, and its nodes are numbered
  before Louvain, since networkx gathers nodes in sets whose order for strings depends on
  Python's hash seed.

## When they are computed

- **`run`,** after building, with its session (`subjects.update`): a family is asked for again when
  its versions or its diagrams' names, places or about texts change (`Family.signature`), or its
  ways failed or were incomplete. A complete, unchanged family costs nothing.
- **`exports.rebuild` without a session** (`remove`, `prune`, a run that stopped): an unchanged
  family keeps its record; a changed one gets the fallback until the next run.
- **A replayed run** (`--llm-replay`) counts a miss at the root as an unanswered request.
- **`subjects.json`:** `format`, then per family its name, tokens (newest first), signature,
  `diagrams` (key to the versions holding it), `views` and `default`, and `ways`: `found`,
  `incomplete`, `failed`, `not asked` or `too few diagrams`. `run.json` and `status` count them.

## In the exports

- **The search page:** a `data-subjects` block (`searchpage.page_subjects`), read by
  `Engine.Subjects`:
  - a diagram is in its subject; any other item where most of the diagrams that show it are;
  - results group in the order of their best result, three shown, the rest on request;
  - an item held by several versions shows once, with the count;
  - with no search, a browse pane: models, then a view, then subjects, then their diagrams.
- **The workbook:** a Subjects sheet, a row per model, view, subject and diagram; the Diagrams
  sheet's Subject column, from the suggested view.
