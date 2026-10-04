# Research: what Cameo's tables hold, and how much of them we compute, 2026-10-04

**Question.** Cameo computes a table's cells whenever it shows the table, and stores none. How
much of the samples' tables can be computed from the model, as Cameo shows them? This is plan
CT (`docs/archive/plans/cameo-tables-2026-10-04.md`).

**Method.** Every table on a diagram without a layout, in every `.mdzip` in `samples/`, parsed
with the library and computed by `cameo_tables.build`.

## The configuration

A table's configuration is the tags of a stereotype on its diagram (`DiagramTable`,
`InstanceTable`; `RequirementTable` alongside):
- `columnIds`, with `hideColumns` hidden;
- `sort`, as `QPROP:Element:Id^Asc`;
- `rowElementType` and `includeSubtypesOfRowTypes`;
- `scope`;
- the rows: `rowElements` and `additionalElements`;
- `classifiers`, for an instance table;
- display settings, which we ignore (`displayMode`, `columnWidth`, `showElementNumber`).

**Rows listed and rows saved.** For 120 of the 122 tables that have both, the rows Cameo saved
(`usedObjects`, `docs/research/used-objects-2026-10-03.md`) are exactly `rowElements` with
`additionalElements`. In the other 2, TMT's "APS Requirements" and its copy in TMT-2024x, the
lists name one element more than was saved.

**Columns, by kind:**

| Column | Reads | Example |
|---|---|---|
| `_NUMBER_` | The row's number | `#` |
| `QPROP:Element:<p>` | A property, a requirement's Id or Text, a tag, an attribute or reference, or a relationship | `name`, `Id`, `Key`, `SatisfiedBy` |
| `QPROP:stereotypeTags:<<Profile::S>>.tag` | A tag of one stereotype | `<<ReqIF Properties Profile::ObjectProperties>>.TMT ID` |
| `IColumn:<feature id>` | An instance's slot for that attribute | `mass` |
| `CUSTOM_COLUMN:<name>` | An expression Cameo evaluates | `Capability Supporting` |

## Coverage

**Tables computed:** those that list their rows.

| Kind | Tables | Computed | Visible columns computed (but `#`) |
|---|---|---|---|
| Requirement Table | 19 | 18 | 76 of 80 (95%) |
| Generic Table | 122 | 60 | 135 of 169 (80%) |
| Instance Table | 129 | 42 | 316 of 316 (100%) |
| Glossary Table | 4 | 1 | 4 of 5 |

- **Tables not computed** are defined by their scope and row types alone (147), or by a
  configuration we don't read (SAF's exchange tables). Plan CT's CP2 reads scopes.
- **Columns not computed** are properties a profile derives ("Owning Block", "Signal
  attributes", "Constrained by"), custom expression columns, and two tags no element in TMT
  carries ("TMT ID", "SE Notes"). Their headers stay, and the page lists them.

## Two readings of TMT's "APS Requirements"

- **Its `Id` column holds DOORS database numbers** (5, 8, 11), and the requirement ids are in the
  text ("[REQ-2-APS-0005] APS shall…"). Cameo shows the same. The table shows the model as it is:
  elsewhere the tool reads the id from the text (`semantics.requirement`).
- **`Key` is a tag of two stereotypes** on some requirements (`ObjectProperties` and
  `TMT_Requirement`), with one value. It shows once.

## Rows from scope: not reproducible (plan CT-06)

147 tables define their rows by a scope and row types alone, and Cameo saved no rows for any of
them. A rule was tried on the 64 tables that both list their rows and have a scope:
- **The rule:** the elements under the scope, of the row types, where a row type is an OMG
  metaclass, a SysML stereotype, or a profile's stereotype named through the used project. For
  an instance table, the instances of its classifiers.
- **Three ways of walking the scope:**

  | Walking the scope | Rows equal to the listed rows | More | Fewer | Other |
  |---|---|---|---|---|
  | All contents, recursively | 20 | 24 | 3 | 17 |
  | Through packages only | 17 | 14 | 18 | 15 |
  | Direct contents only | 13 | 12 | 25 | 14 |

- **Why it fails:** a table that lists its rows is curated, with rows added and removed by hand,
  so its scope isn't a live query. The listed rows can't confirm a rule for scope-only tables,
  and nothing else in the samples can. Examples:
  - TMT's "DRD APS" lists 86 requirements, where its scope holds 91;
  - SAF's "Changelog Table" lists 7, where its scope holds 16.
- **Instance tables:** the rows' classifiers read correctly. Of the 87 scope-only instance
  tables, the rule finds instances for 9.

**Decision** (the maintainer's): rows aren't inferred. Tables defined by scope, matrices and maps
are reported as not computed, each with its reason, on their page, in the catalog, the workbook and
the search page. No remedy is suggested, since none is verified (ADR-0025).

## Release check (0.17.0)

- **The tree:** rebuilt from 0.16.1's store, with no request new; the invariants hold.
- **The tables:** 139 computed in the whole tree, the SAF bundles included.
- **Retrieval:** the 210 fictional questions, which ask nothing about tables. One measure moved:
  BM25's nDCG@10 fell by 0.0004, from four questions ranked slightly lower, with hit@10 and
  MRR@10 unchanged. The samples' table chunks are a few more distractors for keyword search.
