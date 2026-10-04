# ADR-0025: Tables are computed from what the file lists; what Cameo infers is reported, not guessed

- **Status:** Accepted, 2026-10-04 (plan CT; the maintainer: "A, but with clear notes", then
  "since it's an assumption, just report honestly what it wasn't able to process").
- **Sources:**
  - `docs/archive/plans/cameo-tables-2026-10-04.md`;
  - `docs/research/cameo-tables-2026-10-04.md`;
  - `docs/research/used-objects-2026-10-03.md`;
  - `docs/design/output-and-chunks.md`.

## Context

A Cameo table is a curated view: its rows and the columns chosen for them. Cameo computes its
cells whenever it shows it, and stores only its configuration and, usually, the rows it lists.
- **Listed rows are reliable:** for 120 of 122 tables, the rows Cameo saved are exactly those the
  table lists.
- **Rows from scope are not:** 147 tables find their rows in a scope, and no rule found them as
  Cameo would. On the tables that have both, the best rule reproduced the listed rows for 20 of 64,
  and nothing in the samples can confirm a rule.

## Decision

- **A table that lists its rows is computed:**
  - its visible columns, in order, sorted as configured;
  - shown on its page, as a CSV, and in chunks.
- **Columns only Cameo can compute** (custom expressions, properties a profile derives) keep their
  header, and are named as not computed.
- **Tables that find their rows in a scope, matrices and maps** are shown without rows. Each one
  says what is missing and why, as do the catalog, the workbook and the search page. Rows aren't
  inferred, and users are given no remedy that hasn't been verified.

## Consequences

- Readers see the tables engineers made, where the file holds them, and know where it doesn't.
- Matrices remain to be computed, in a plan of their own. Scope-only tables could follow if
  evidence of how Cameo finds their rows turns up: a model that saved such a table's rows would be
  enough to test a rule.
