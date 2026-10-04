# ADR-0008: Sections built once as data; stages pass structure, not text

- **Status:** Accepted, 2026-10-02 (plan RA).
- **Sources:**
  - AR-002R1, AR-003R2, AR-012R1 and R2, AR-014R2, AR-015R1 and R2, AR-018R1;
  - `docs/archive/reviews/architecture-2026-10-01.md`;
  - `docs/archive/plans/refactoring-2026-10-02.md`.

## Context

Chunks were made by parsing rendered page Markdown back with regular expressions. That ate `*`
operators, dropped `#` lines and stripped `>`, and every wording change on a page silently changed
how chunks split.

## Decision

- **Sections:** each section is built once as data (`sections.Section`) and rendered by role:
  - `markdown()` for pages;
  - `plain()` for chunks;
  - `text()` for LLM inputs.
- **Stages hand each other structure:**
  - `diagram_text.describe` takes `Refs(target)`, and decides whether to link by the target, not
    by how a label looks;
  - the tree's index reads per-project `index/ids.jsonl`, written from the in-memory model;
  - threads are built with their project into `index/threads.jsonl`;
  - generated chunks carry `primary_chunk` and `annotation`.
- **One way to make and check a chunk:** `chunks.make` and `chunks.problems` make and validate
  every record. A chunk id is the first 24 hex digits of the sha256 of its identifying parts. A
  project chunk's locator starts with its content hash.
- **One packer and splitter** (`plain.pack`, `parts`, `parts_with_context`). A later part restates
  its ancestors, marked "(continued)".

## Consequences

- **Per-project contract:** a project's build and the tree's rebuild meet at
  `index/chunks.jsonl`, `ids.jsonl` and `threads.jsonl`.
- **Tests:** `check_invariants` uses the same check as `chunks.make`.
