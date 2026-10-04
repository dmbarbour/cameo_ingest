# Plan: Cameo's tables, computed as Cameo shows them, 2026-10-04

- **Status:** Active. CP1 done (0.17.0); CP2 stopped for the maintainer's decision (CT-06). Approved on 2026-10-04 ("Looks good, including your
  recommended choices"):
  - tables appear on their diagram page, as a CSV, and in chunks;
  - rows come from the table's own lists where it has them, else from its scope;
  - requirement tables come first, then generic and instance tables; matrices follow on, in a
    plan of their own.
- **Step prefix:** `CT`, so steps are `CT-01`, `CT-02` and so on.
- **Addresses:** the roadmap's "Recompute tables and matrices", ranked first among its larger
  items. Cameo computes a table's cells whenever it shows the table, and the file stores none.
  A table's page today shows its raw configuration and an unsorted list of its rows.

## What the samples hold

Surveyed on every `.mdzip` in `samples/`:

| Kind | Tables | Columns, mostly |
|---|---|---|
| Instance Table | 129 | name, and one per attribute (`IColumn:<feature id>`), filled from slots |
| Generic Table | 122 | name, type, documentation, Id, status, owner, stereotype tags; about 30 custom expression columns (`CUSTOM_COLUMN:`) |
| Requirement Table | 19 | `_NUMBER_`, name, Id and Text in nearly all; tags (Key, Driving, TMT ID); a few relationship columns (satisfies, DerivedFrom) |
| Matrices | 32 | No rows stored; a later plan |
| Maps and glossaries | 16 | Glossaries as tables; maps later |

**The configuration** is a stereotype's tags on the diagram (`DiagramTable`, `InstanceTable`):
- `columnIds`, minus `hideColumns`, in order;
- `sort`, as `QPROP:Element:Id^Asc`;
- `rowElementType`;
- `scope`;
- the rows: `rowElements` and `additionalElements`;
- `classifiers`, for an instance table.

**The rows:** for 120 of the 122 tables that have both, the rows saved in `usedObjects` are
exactly `rowElements` with `additionalElements`. In the other 2, the lists name one more element.
For 147 tables, only a scope and row types define the rows (CP2).

## Steps

| Step | What | Status |
|---|---|---|
| CT-01 | **A table's specification** (`cameo_tables.py`), from its diagram's stereotypes: kind, visible columns, sort, row types, scope, classifiers. **Rows:** `rowElements`, then `additionalElements`, each once, those in the model. | Done (0.17.0) |
| CT-02 | **Columns:**<br>- `_NUMBER_`;<br>- `QPROP:Element:<p>`: name, documentation, owner, type, classifier, applied stereotypes; a requirement's Id and Text; else a tag of that name on an applied stereotype (Key, Driving, status); else a model attribute or reference of that role; else a derived relationship property (satisfies, SatisfiedBy, refines, RefinedBy, verifies, VerifiedBy, TracedTo, DerivedFrom, Derived), read from the relationships;<br>- `QPROP:stereotypeTags:<<Profile::Stereotype>>.tag`;<br>- `IColumn:<feature id>`: the row's slot values for that feature.<br>`CUSTOM_COLUMN:` columns, and any column not resolved, keep their header, are marked "computed by Cameo", and are listed. Headers read as Cameo's do: "#", "Name", "Id", the tag's or feature's name. | Done (0.17.0), with multiplicity and specification; a tag column counts a tag any element of the model has; a value shown once though two stereotypes carry it |
| CT-03 | **Output:**<br>- **Page:** a Markdown table; names link to their elements; cells cut at 500 characters. It replaces "Elements shown when last saved". The configuration reads as a line: "Columns: #, Id, Name, Text. Sorted by Id. Rows: 86 requirements".<br>- **CSV:** `tables/diagram-tables/<page name>.csv`, cells whole.<br>- **Chunks:** the diagram's detail chunks hold the rows, one line each, every cell named ("Id: REQ-2-APS-0047; Name: Provide Health Status; Text: …", cells cut at 300 characters), so that a chunk cut between rows still says what each value is.<br>Diagrams aren't package sections, so no LLM request changes. | Done (0.17.0): the summary sentence and the rows replace the raw configuration and the row list |
| CT-04 | **Tests:** a requirement table in the fixture, with a sort, a tag column, a relationship column, a hidden column and a custom column. **Coverage on the samples:** the share of visible columns computed, by kind, in a research note. | Done: `tests/test_cameo_tables.py`; coverage in `docs/research/cameo-tables-2026-10-04.md`: 121 tables computed in the samples, 95% of requirement tables' visible columns, 80% of generic tables', all of instance tables' |
| CT-05 | **CP1's release check:** the tree rebuilt from the store, with no new request expected; the invariants; a reading of TMT's and OpenSUT's requirement tables against their models. 0.17.0. | Done: no request new; 139 tables computed in the tree; the invariants hold; retrieval: BM25's nDCG@10 −0.0004 (four questions slightly lower), hit@10 and MRR@10 unchanged |
| CT-06 | **Rows from scope,** where a table lists none: elements under its scope (packages, recursively) whose kind matches a row type (an OMG metaclass or stereotype, or a profile's stereotype by id or name), with subtypes when `includeSubtypesOfRowTypes` says so; for an instance table, the instances of its classifiers. **Checked** on the tables that list their rows and have a scope: rows from scope against rows listed. | Stopped: the best rule reproduces the listed rows of 20 of 64 tables that have both (the research note). Listed rows are curated, so they can't confirm a scope rule. Waiting on the maintainer |
| CT-07 | **CP2's release check,** coverage again, and the docs: the design docs, the README, an ADR. 0.17.x. | |

## Checkpoints

| Checkpoint | Steps | Delivers |
|---|---|---|
| CP1: listed rows | CT-01 to CT-05 | Requirement, generic and instance tables with listed rows (124), computed |
| CP2: rows from scope | CT-06, CT-07 | The 147 tables defined by scope |

## When to stop and ask

- **If scope rules can't reproduce listed rows** for most tables that have both: reading rows
  from scope would then be guesswork.
- **If table chunks crowd retrieval:** a table's rows repeat what its requirements' chunks hold.
  Retrieval on the fictional questions should not drop.
