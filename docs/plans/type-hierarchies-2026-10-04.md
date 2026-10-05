# Plan: type hierarchies for search, 2026-10-04

- **Status:** Active; CP1 done (0.18.0), CP2 in progress. The maintainer asked for it on 2026-10-03 ("seems we may
  need to be drawing some generalization trees, too? … esp. for search"), and on 2026-10-04:
  "please proceed with type hierarchies for search".
- **Step prefix:** `TH`, so steps are `TH-01`, `TH-02` and so on.
- **Builds on:** the requirement threads (plan RF, ADR-0019): a chunk per tree, assembled, behind
  a tree-wide switch, cut into parts that restate their ancestors.

## Why

A question such as "what kinds of detector does the model define?" has its answer spread over
every kind's own chunk. Each chunk says "is a kind of Detector", but only one at a time. A chunk
per hierarchy holds the whole answer, in the way a thread holds a requirement's derivations, which
raised coverage in plan RF.

## What the samples hold

Surveyed on every `.mdzip` in `samples/`:
- **Generalizations:** 3,031 within projects, and 146 to a general outside the project.
- **Roots:** 201 roots of a hierarchy (a general with no general of its own in the project), 75 of
  them with 3 kinds or more.
- **Shapes:**
  - NIST_M-SysML has one hierarchy of 1,005 kinds, 10 levels deep, and 174 kinds with two or more
    generals;
  - TMT has 41, the largest a flat list of 145 kinds under one root;
  - MDK_DocGen has 90, nearly all of 2 kinds;
  - SAF_Profile's are stereotypes.
- **Generals outside the project:** TMT's analyses specialize a library's `MonteCarloAnalysis`
  (25), and SAF_Profile's stereotypes specialize SysML's `Block` (40).
- **The fictional projects** hold one small hierarchy (Ferrous Valley, 3 kinds).

## Design

- **A hierarchy per root,** of 3 kinds or more. A root is:
  - an element that has specializations and no general in the project; or
  - a general outside the project with 2 or more specializations in it, named as the project's
    cached copy names it, "(outside this project)".
- **Its lines:** each kind once, indented under its general, with its kind word (Block, Class,
  Stereotype) and the first sentence of its documentation, cut at 100 characters. A kind with
  two or more generals is shown under the first, by name, and says "also a kind of …".
- **Its chunk:** `index:hierarchy`, assembled.
  - Heading: "Hierarchy: kinds of Detector, in <project>, 9 kinds, 3 levels".
  - Cut into parts that restate their ancestors (`plain.parts_with_context`), as threads are.
- **Where:**
  - per project: `index/hierarchies.jsonl` and `HIERARCHIES.md`;
  - the tree's `chunks.jsonl` and `rag/`, behind `--hierarchies/--no-hierarchies`, tree-wide,
    on by default.

## Steps

| Step | What | Status |
|---|---|---|
| TH-01 | **Hierarchies** (`hierarchies.py`): roots, lines, multiple generals, outside generals, depth; the records of `index/hierarchies.jsonl`; `HIERARCHIES.md`. | Done (0.18.0), with alike leaves on one line ("10 kinds of this name": TMT's runs of one analysis); a kind under two roots appears in both |
| TH-02 | **Chunks** in the tree, as threads are (`exports.py`); the switch; `status` and README. | Done (0.18.0): `exports.hierarchy_chunks`, `--hierarchies` (tree-wide, on); README and design docs at TH-06 |
| TH-03 | **Tests:** a fixture with a hierarchy of 3 levels, a kind with two generals, and a general outside the project; the switch off leaves no chunk. **The samples:** counts, and NIST's large hierarchy read in parts. | Done: `tests/test_hierarchies.py`. On SAF_Profile, NIST_M-SysML and TMT: 17, 2 and 23 hierarchies, 185 chunks; NIST's 1,005 kinds in 75 parts, each restating its ancestors |
| TH-04 | **The fiction:** a type hierarchy in Port Calder (field equipment: detectors, signal heads, controllers, 3 levels, with documentation), and questions about it, graded by construction: "what kinds of …" (every kind, in parts), "what is X a kind of" (one), "which kinds of … do Y" (some). | |
| TH-05 | **Measured:** retrieval on the hierarchy questions with and without hierarchy chunks (coverage@10 and complete@10, as plan RF measured threads), and the 210 questions unchanged; a research note. | |
| TH-06 | **The release check;** docs: design, README, an ADR; a version. | |

## Checkpoints

| Checkpoint | Steps | Delivers |
|---|---|---|
| CP1: hierarchies | TH-01 to TH-03 | Hierarchy chunks in the tree |
| CP2: measured | TH-04 to TH-06 | Whether they help, on questions that need them |

## Later

The kinds that specialize a shared library type across models (`MonteCarloAnalysis` in TMT and
TMT-2024x), as the identifier index does across models.

## When to stop and ask

- **If hierarchy chunks hurt** the 210 questions significantly.
- **If they don't help** the hierarchy questions: the element chunks may already serve.
