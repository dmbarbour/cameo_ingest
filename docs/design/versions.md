# Design: versions of a model, and removing projects

How the tool finds versions of one model among many files, and how projects leave a tree. Decision:
ADR-0020. The README's "Versions and removal" gives the steps for a messy folder.

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

These go in `state.sqlite` (`fingerprints`), so `groups` re-reads nothing.

## Groups (`groups.py`)

Projects are compared pairwise, by the ids they share.

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
