# ADR-0032: Lineage of models, told by who made their ids and when

- **Status:** Accepted, 2026-10-07 (plan LN; the maintainer: "Go ahead with other checkpoints").
- **Sources:**
  - `docs/plans/lineage-2026-10-07.md`;
  - `docs/research/lineage-2026-10-07.md`;
  - TR-003 (`docs/reviews/trial-2026-10-06.md`); ADR-0020, which this changes; ADR-0031.

## Context

- **Versions and rivals look alike by shared ids:** two bids on one customer model share 77% to
  79% (Jaccard), more than ADR-0020's rule (0.5) asks of versions, while real versions after
  rework share as little as 22% to 39% (SAF from 2021 to 2024, TMT from 2019 to 2023). Joined as
  versions, rivals lose their own diagrams in subjects (ADR-0031): a diagram both hold is shown
  once, as the newest one's.
- **Cameo's ids carry a maker and a time:** `_<tool version>_<hex id>_<epoch ms>_<random>_<counter>`
  for 57% to 99% of a model's ids. That the hex id names a user or an installation is inferred
  from the shape, not documented.

## Decision

- **Each id's maker and day** are kept beside the fingerprint's hashes (`id_marks`, schema 5),
  6 bytes an id. `run` and `scan` fill them for contents fingerprinted before.
- **Each pair that shares ADR-0020's "related" share** gets a kind and its evidence
  (`lineage.py`): copy, version, derived (built on the older by others: a bid on a customer's
  model), branches, root (rivals on a shared root), related, or unknown. Time decides more than
  share: a version's own ids come after the shared part, the older's dropped ones mostly before
  it; rivals' own both come after it, by makers the other lacks. The thresholds are in
  `lineage.py` and the research note.
- **Families are chains of copies and versions.** Derived models, branches and rivals are **kin**:
  listed with their evidence by `groups`, never merged, so each keeps its own diagrams. A pair
  whose ids carry no makers (`unknown`) falls back to ADR-0020's rule.
- **The evidence is shown with every kind:** shares, makers, dates, the common folder. Nothing is
  removed or merged for the maintainer beyond what families already did.

## Consequences

- **Measured:** synthetic cases 9 of 9; real public histories (SAF, OpenSUT, NIST, TMT) 15 of 16,
  the miss read as "related", so nothing is merged wrongly.
- **Rivals are tested only on synthetic cases:** no public set of bids on one model exists. The
  maintainer's trial is their test.
- **Changing the rules later** regroups on the next run: no kind is stored.
- **Diffs** between versions and between rivals follow (roadmap, "Comparing models").
