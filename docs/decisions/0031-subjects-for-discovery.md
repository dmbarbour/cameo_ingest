# ADR-0031: Subjects for discovery: the LLM proposes ways, shared elements are the fallback

- **Status:** Accepted, 2026-10-07 (plan SB; the maintainer: "Yes, write the ADR and start CP3"); updated on
  2026-10-07 (Changes, below).
- **Sources:**
  - `docs/plans/subjects-2026-10-06.md`, its steps SB-01 to SB-06;
  - `docs/research/subjects-2026-10-07.md`;
  - TR-002 (`docs/reviews/trial-2026-10-06.md`); ADR-0020 (versions), ADR-0027, ADR-0029.

## Context

- **Searches return hundreds of diagrams for one subject.** The maintainer asked for discovery
  of diverse things, "the opposite of 'closest match' searches, i.e. building a list of
  mostly-independent cliques", and suggested that an AI propose a few viable splits.
- **A panel of three AI judges** compared eight ways of splitting 12 models (the maintainer's
  models can't be shared):
  - the package tree, communities of diagrams by shared elements, and word clusters group about
    equally well, and none of them better than another;
  - the LLM's groups hold together no better, but it names subjects that people can use: its
    proposed ways win label fit by +0.28 to +0.33 and every paired preference;
  - its three ways per model (by engineering activity, by part of the system, by kind of
    concern) can't be told apart.
- **The LLM is unreliable:** timeouts, and trees built without it (the maintainer).

## Decision

- **Version families first:** a corpus is grouped into versions of a model (chains of copies and
  versions, ADR-0032; rivals on a shared root stay apart);
  in a family, a diagram held by several versions is one item, listed with its versions.
- **With the LLM, its ways:** for each family, the tree's text model proposes about three ways to
  organize its diagrams, each on its own principle, with labelled subjects; then it assigns each
  diagram to a subject of each way, in batches cut by package.
- **The fallback, per family:** communities of diagrams by the elements they share, labelled by
  their distinctive words. It serves when the tree has no LLM, or the family's proposal fails.
- **A way partly assigned** keeps its unanswered diagrams under "Not sorted yet", never a guess
  (placing them by their community's majority matched the LLM's own choice 49% of the time).
  The next run retries them, since failures aren't stored. While more than 5% are unsorted, the
  fallback is the family's default view.
- **The package tree** is always a view, as fact.
- **Views, not settings** (ADR-0027): every tree computes the same splits. The search page offers
  them as views of a family, the default first.
- **Computed by `run`, at the root,** after the projects are built, since families span projects:
  `subjects.json`, read by the exports.

## Consequences

- **The LLM's cost:** a proposal per family, and about one request per 10 diagrams for the three
  ways' assignments (TMT: about 140). Stored answers make reruns free. A family's proposal is
  asked again when its diagrams change.
- **The judges measured labels and coherence, not usefulness.** Whether the subjects feel natural
  on real models is for the maintainer's trial.
- **A model without diagrams** has no subjects. Elements are placed by the diagrams that show
  them.

## Changes

- 2026-10-07: families from lineage (ADR-0032), so that rival bids keep their own diagrams. Before: `9536e4d`.
