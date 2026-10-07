# Design: versions of a model, and removing projects

How the tool finds versions of one model among many files, and how projects leave a tree. Decisions:
ADR-0020, ADR-0032. The README's "Versions and removal" gives the steps for a messy folder.

## What a project says about itself (`fingerprint.py`)

Read during the scan, and by `scan` alone, which builds nothing and needs no LLM settings:
- **The save time:** a Java `Date.toString` read from the first 512 bytes of `Records.properties`
  (or else `Binaries.properties`). Copying a file doesn't change it.
  - A `ZONES` table maps about 30 Java zone abbreviations.
  - An unknown zone is kept as written, without an offset.
  - Without a save time, the latest date among the zip's entries stands in, flagged.
- **The project id,** from `com.nomagic.ci.metamodel.project`. It is not used alone: TMT and
  TMT-2024x have different ones, and a model made from a template keeps the template's.
- **The exporter,** from `xmi:Documentation`.
- **The element ids,** read with `iterparse`: about a second for 100,000 ids. They are kept as
  sorted, distinct 64-bit blake2b hashes, packed as a little-endian `array('Q')` blob (8 bytes an
  id, not compressed).

- **Each id's maker and day** (plan LN-01): `_<tool version>_<hex id>_<epoch ms>_<random>_<counter>`
  ids give a maker (the hex id) and a day; MagicDraw's older `eee_<epoch ms>_…` a day. Kept in
  `id_marks`, in the hashes' order: the maker's index (`array('H')`) and the day (`array('I')`).

These go in `state.sqlite` (`fingerprints`, `id_marks`), so `groups` re-reads nothing. `run` and
`scan` fill what a tree from an older version lacks.

## Lineage (`lineage.py`)

Each pair sharing at least 20% of the smaller model's ids (and 20) gets a kind, from who made
each side's own ids (those the other lacks), and when, against the shared part's latest day
(its 95th percentile) and the other's save time:

| Kind | When | Family |
|---|---|---|
| copy | neither side has more than 0.1% (or 2) of its own | same |
| version | the newer's own made after the shared part (60%), the older's own mostly before; at least 15% of the newer's own by the older's makers. Or the newer has nothing of its own and keeps half the older (Jaccard) | same |
| derived | the same, with under 15% by the older's makers: built on it by others | kin |
| root | each side has much of its own (3%, 20), mostly made after the shared part, by makers the other lacks: rivals | kin |
| branches | the same, by makers both share (60%) | kin |
| related | much of each side's own predates the shared part: a library | listed |
| unknown | under 30% of the deciding side's own carry a maker: ADR-0020's rule decides | by the rule |

Every kind comes with a sentence of evidence, shown by `groups`. Measured: synthetic 9 of 9, real
histories 15 of 16 (`docs/research/lineage-2026-10-07.md`).

## Groups (`groups.py`)

Projects are compared pairwise, by the ids they share; with lineage, families are the chains
of copies and versions, and kin are listed apart ("Built on one another, kept apart"). Without
it, or for an `unknown` pair, ADR-0020's rule:

| Link | Rule | Constants |
|---|---|---|
| Likely versions | Jaccard index ≥ 0.5, or ≥ 80% of the smaller model's ids with at least 50 shared | `VERSION_JACCARD`, `VERSION_COVER`, `VERSION_MIN` |
| Related | ≥ 20% of the smaller model's ids, at least 20 shared: listed, not grouped | `RELATED_COVER`, `RELATED_MIN` |

- **Groups** are the connected components of likely-version links (union-find), so a model that
  grew over many versions chains through them.
- **Ordering:** within a group, members run newest first. A Cameo save time ranks above a zip date,
  and a zip date above no time. Times are compared in UTC when the zone is known.
- **Possible fork:** a member with 10% or more of its ids missing from the newest is flagged
  (`FORK`): "a fork, or much deleted since". The rule is one-sided, where the plan described it as
  mutual.
- **The suggested `remove` line** leaves out every group with a warning (a fork, no save time, zip
  dates); those groups' older members are listed apart. Tokens are shown as 12 hex digits.

## Removal

- **`remove -o OUT TOKEN… [--dry-run]`:**
  - a token is `sha256:…`, or at least 8 hex digits, and must be unique;
  - it deletes the project's row, its output and work directories, and rebuilds the root files;
  - it records the removal in `removed`, a table not tied to `contents`, so that the removal
    outlives the input and `prune`, and `run` skips the project even if it turns up in another
    file.
- **The LLM answers stay in the store,** so `restore` (which deletes the `removed` row) costs only
  the build.
- **Listings:** `project_status` shows `removed`, which `status` and `INDEX.md` use. `groups
  --include-removed` compares removed projects too.

## Evidence (the samples, 2026-10-02)

- **TMT and TMT-2024x** share 69,613 ids: 88% Jaccard, 98% of the smaller model. No other pair
  shares more than one id.
- **The scan and fingerprints** of 27 projects took 11 s at about 300 MB.

**Untested on the maintainer's corpus:**
- save times may be missing or contradictory;
- some Cameo versions may not keep ids across saves.
