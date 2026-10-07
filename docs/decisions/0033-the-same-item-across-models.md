# ADR-0033: The same item across models, and comparing two models, in the exports

- **Status:** Accepted, 2026-10-07 (plan SH; the maintainer's answers, below).
- **Sources:**
  - `docs/archive/plans/shared-items-2026-10-07.md`;
  - TR-004 (`docs/reviews/trial-2026-10-06.md`); ADR-0021, ADR-0032.

## Context

The maintainer, on TR-004: "The same requirement/diagram/etc. (same name, etc.) can exist in many
models... it might be useful to have some means to easily locate the other models it's shared
with... Ultimately, TR-004 sort of touches on how we'd present similarities and differences
between models (within a lineage or between rivals), make them easier to discover and analyze
without opening up every model in Cameo."

## Decision

- **Matches, strongest first,** each shown with its basis (`shared.find`), constants adjusted from
  trials ("The matching heuristics look right. We can make that bit tunable based on future trial
  feedback"):
  - the same element id;
  - the same requirement Id, each the only one so identified in its model;
  - the same type, kind and name, each the only one so named, between models lineage relates.
- **A difference is what people deliberately edit** (the maintainer: "the things that matter are
  the things that humans deliberately edit"): name, requirement Id, text, stereotypes and tagged
  values, relationships (by the other end's id, else its label), members, what a diagram shows,
  package. Not what tools record (stamps, authors, layout). The catalog now holds tagged values.
- **Computed by `export`,** two passes over the catalogs; no root file.
- **In the search page:** an item's "Also in" (each copy a link, how its model stands, the basis,
  what differs); one row for an element held by several models; and **Compare**, two models chosen,
  computed in the page from the items' matches: changed, only in either, the same, by kind.
- **In the workbook:** an Also in column, and a Shared sheet of copies elsewhere and copies that
  differ.
- **No pages per pair in the tree, nor for a RAG:** "per related pair is an unbounded explosion in
  general" (the maintainer).

## Consequences

- **Measured on the study tree:** 50,890 links by element, 32 by requirement Id, 16 by name (all
  real: TMT items re-made between versions); the synthetic bids' edits found exactly.
- **Cost:** the workbook 7.4 MB from 7.1, the page 10.0 MB from 9.6, on the samples and fiction.
- **Comparing has no file cost:** the page compares from the matches it carries.
