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

## Topics across models

Plan SB CP4 (`topics.py`): every family's subjects, in its suggested view, gathered into topics
that span the collection, so that what different models hold on one thing can be found together.
A **subject** is read by its label, what it holds, and its diagrams' names and about texts; it
shows the elements its diagrams show. Topics need at least two families (`MIN_FAMILIES`).

| View | How | When it comes first |
|---|---|---|
| The LLM's (`llm`) | `TOPICS_PROPOSE`: the list of every subject (label, model, what it holds; at most 400, spread over the collection) to about the target's topics, each labelled; then `TOPICS_ASSIGN`, 30 subjects a request, a family's together | When it placed at least 95% of the subjects |
| Words (`words`) | Louvain on a graph of subjects: TF-IDF cosine, each joined to its 5 nearest, and the elements both show over the fewer either shows; **only between families**, on words in at least two families' subjects. Merged down to the target, smallest first, into the topic it is most joined to. Labelled by distinctive words of the labels and what they hold | When the tree has no LLM, the proposal failed, or it left over 5% unsorted |

- **Across, not within:** joined within a family too, a model's own words joined its subjects to
  each other, and topics came out as models, or sibling models, again (on the study tree: every
  MDK_DocGen subject in one topic, NIST's in another, the SAF models' in a third). Rival bids
  share a tender's elements, so the shared-element links join them however they word things.
- **Targets:** about the square root of half the subjects, 2 to 15, as for a family's subjects.
- **An item's topic** is its subject's (in its family's default view). Subjects a run couldn't
  place stay under "Not sorted yet".

## When they are computed

- **`run`,** after building, with its session (`subjects.update`): a family is asked for again when
  its versions or its diagrams' names, places or about texts change (`Family.signature`), or its
  ways failed or were incomplete. A complete, unchanged family costs nothing.
- **`exports.rebuild` without a session** (`remove`, `prune`, a run that stopped): an unchanged
  family keeps its record; a changed one gets the fallback until the next run.
- **A replayed run** (`--llm-replay`) counts a miss at the root as an unanswered request.
- **Topics** are asked for after the families (`topics.update`), when the subjects' labels, what
  they hold or their sizes change (`topics.signature`), or the last answer was incomplete; without
  a session, unchanged topics are kept and changed ones get words.
- **`subjects.json`:** `format`, then per family its name, tokens (newest first), signature,
  `diagrams` (key to the versions holding it), `views` and `default`, and `ways`: `found`,
  `incomplete`, `failed`, `not asked` or `too few diagrams`; then `topics`: its signature, `views`
  (each topic's `subjects` as `token/n`, a family's newest token and the subject's place in its
  default view; `unsorted`), `default`, and `ways` as a family's, or `too few models`. `run.json`
  and `status` count them.

## In the exports

- **The search page:** a `data-subjects` block (`searchpage.page_subjects`), read by
  `Engine.Subjects`:
  - a diagram is in its subject; any other item where most of the diagrams that show it are;
  - results group in the order of their best result, three shown, the rest on request;
  - an item held by several versions shows once, with the count;
  - with no search, a browse pane: models, then a view, then subjects, then their diagrams;
  - topics in a `data-topics` block (`searchpage.page_topics`): with several models shown, the
    browse pane opens on topics (each its models' subjects, each its diagrams), browsing by model
    a click away; results group by topic (each saying how many models it spans, each result its
    subject), by subject, or not at all.
- **The workbook:** a Subjects sheet, a row per model, view, subject and diagram, with the
  suggested view's subjects' topics; the Subject and Topic columns of the Requirements, Elements
  and Diagrams sheets, from the suggested views.
