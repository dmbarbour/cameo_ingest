# Plan: the same item in several models, and how it differs, 2026-10-07

- **Status:** Done, 2026-10-07 (0.26.0, 0.27.0; ADR-0033).
- **Step prefix:** `SH`, so steps are `SH-01`, `SH-02` and so on.
- **Addresses:** TR-004 (`docs/reviews/trial-2026-10-06.md`) and the roadmap's "Diffs, between
  versions and between rivals", which this plan takes up. The maintainer, 2026-10-07:
  > "The same requirement/diagram/etc. (same name, etc.) can exist in many models, e.g. due to
  > shared lineage, or various other reasons. Instead of presenting this requirement as belonging
  > to a single model, it might be useful to have some means to easily locate the other models
  > it's shared with. Of course, 'same' is scoped and contextual, there may be other elements
  > linked to or from the requirement that have diverged between models. Ultimately, TR-004 sort
  > of touches on how we'd present similarities and differences between models (within a lineage
  > or between rivals), make them easier to discover and analyze without opening up every model
  > in Cameo."

## Decisions (the maintainer, 2026-10-07)

> "The matching heuristics look right. We can make that bit tunable based on future trial
> feedback. When comparing two models, the things that matter are the things that humans
> deliberately edit."

- **D1, matching:** the three bases (element id; requirement Id; kind and name between related
  models), as constants, adjusted from trial feedback, not settings (ADR-0027).
- **D2, what a difference is:** what people deliberately edit: names, text and documentation,
  requirement Ids, stereotypes and tagged values, relationships, what an element owns (parts,
  ports, values), what a diagram shows, and where an item sits. Not what tools record: save and
  modification stamps, authors in diagram info, layout coordinates, the ids Cameo makes for
  connector ends and literals, used projects' cached copies.
- **D3, where it is computed:** the exports read every project's catalog already, so they compute
  the matches (`shared.py`), two passes over the catalogs; a root file waits for CP3's pages,
  if they need one.

## Why

An item is shown as one model's, though it may be in many: a requirement in each version of a
model, the customer's requirements in each bid on them, a library block in every model that uses
it. A reader finds one copy, and can't see the others, or what differs between them, without
opening every model.

## What we know

- **"The same" has degrees,** each a match basis shown with the match:
  - **the same element** (the same `xmi:id`): versions, a model and the bids built on it, a used
    project or library. Lineage (ADR-0032) says how the models are related;
  - **the same requirement Id** in different elements: a bidder copying the customer's
    requirements into its own model, a DOORS import (the identifier index, `CROSSREF.md`, already
    finds ids held by two elements or more);
  - **the same kind and name, in related models only:** a name alone is weak (on the study tree,
    187 items share a type, kind and name across model families, many of them diagrams named
    "Attributes"), so it counts only between models that lineage relates.
- **On the study tree** (samples, fiction, synthetic versions): across families, 1 element id and
  12 requirement Ids are shared; within families, all of a version's ids. Rivals on a shared root
  share theirs (the synthetic bids, 77% to 79% Jaccard).
- **What can differ** for one item, from the catalogs (`index/catalog.jsonl`): its name, its text
  (documentation, requirement text), its stereotypes, its relationships (kind, direction, the other
  end by id or by name), a diagram's shapes, and where it sits (its package path).

## Design

- **A shared-item index,** computed by the exports (D3): for each
  item held by two models or more, the models, the match basis, and for each model a digest of each
  aspect (name, text, stereotypes, relationships, shapes, place), so that "the same" and "changed"
  are told without reading the projects again. Aspects are D2's, as far as the catalog holds them.
- **Differences** between two copies, by aspect: what was added, removed or changed. Relationships
  are compared by their other end's id where both models hold it, else by its name, so that a
  relationship to a renamed or re-made element in a bid still lines up.
- **In the search page,** standing alone:
  - an item's view gains **"Also in"**: each other model that holds it, its match basis, and what
    differs there ("the same", or "text changed; satisfied by X here, by Y there"), each a link;
  - results show a shared item once with "in 5 models" (versions are already shown once).
- **In the workbook,** standing alone: an **"Also in"** column (the count and the models) on the
  item sheets, and a **Shared** sheet: a row per shared item and model, with the match basis and
  what differs, to filter and sort.
- **Comparing two models** (the roadmap's diffs): for a pair that lineage relates (a version and
  the next, a bid and the customer's model, two rival bids), what one added, removed and changed
  against the other, by kind: a page in the tree, and a sheet or view in the exports.

## Steps

| Step | What | Status |
|---|---|---|
| SH-01 | **The index:** the matches by element id, by requirement Id, and by kind and name between related models; each copy's aspect digests; `shared.json`. Measured on the study tree and the synthetic bids: how many items, by basis, and how many of the name matches are noise. Tests. | Done: `shared.find` (in 8 s on the study tree, two passes over its catalogs); catalogs carry tagged values (`tagged`, not DiagramInfo's). Study tree: 50,890 links by element (TMT's versions and the fiction's), 1,046 differing; 32 by requirement Id (Riverbend's rivals), all differing; 16 by name, all real: TMT items re-made with new ids between versions. No noise seen. `tests/test_shared.py` |
| SH-02 | **Differences:** for each shared item, what differs between its copies, by aspect; relationships lined up by id, else by name. Tests on the synthetic bids (built with known changes). | Done: `shared.differences`; the lineage corpus's bids now edit what they took (`EDITS`: a reworded requirement, a renamed pump, a satisfy added), and exactly those are found. Most frequent on the study tree: names 512, packages 424 (shown from where the paths part), relationships 362, text 148 |
| SH-03 | **The search page:** "Also in", with differences and links; shared items once in results. Node and browser tests. | Done (0.26.0): items carry `al`; the item view's Also in (each model a link, how it stands to this one, the basis, what differs); `Engine.collapseShared` (one element held by several models, once); seen in Chrome on the synthetic bids. `tests/js/chooser.js`, `tests/test_searchpage.py` |
| SH-04 | **The workbook:** the "Also in" column, and the Shared sheet. Tests. | Done (0.26.0): Also in on Requirements, Elements, Diagrams; the Shared sheet (copies elsewhere, and copies that differ). Study tree: 1,096 rows, the workbook 7.4 MB (from 7.1), the page 10.0 MB (from 9.6). A fix found there: summaries carry their item's key and aren't items. `tests/test_catalog.py` |
| SH-05 | **Comparing two models:** a page in the tree for each related pair, and the exports' view of it. | Done (0.27.0), in the search page only (the maintainer: "let's focus on the search page here... 'per related pair' is an unbounded explosion in general"): Compare, two models chosen in the chooser; `Engine.compareModels`; on the synthetic bids, the tender against Aquila: 2 changed (the pump renamed, the requirement reworded), 56 only in the bid, 248 the same |
| SH-06 | **Docs and release:** an ADR, design/exports, README. | Done (0.27.0): ADR-0033; the roadmap's diffs item taken up |

## Checkpoints

| Checkpoint | Steps | Delivers |
|---|---|---|
| CP1: the index | SH-01, SH-02 | What is shared, and how it differs, measured |
| CP2: in the exports | SH-03, SH-04 | "Also in" in the page and the workbook; a release |
| CP3: comparing models | SH-05, SH-06 | Diffs between related models |

## Questions for the maintainer

- **Q1, the match bases:** answered, D1.
- **Q2, which differences:** answered, D2.

## When to stop and ask

- **Name matches are mostly noise,** even between related models: report, and keep only the ids.
- **The index grows past 10% of a tree's size:** report, with a coarser digest.
