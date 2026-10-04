# ADR-0006: Plain-text chunks for retrieval; pages stay Markdown

- **Status:** Accepted, 2026-10-01 (RE-08, 0.5.0). The Markdown chunk style was retired on 2026-10-02
  (the maintainer's decision 1, AR-004R4; 0.6.0).
- **Sources:**
  - plan RE's decisions 11 and 12 (`docs/archive/plans/retrieval-evaluation-2026-09-30.md`);
  - `docs/research/chunk-styles-2026-10-01.md`;
  - `docs/research/chunk-inventory-2026-09-30.md`.

## Context

In Markdown chunks, 23% of characters were link targets, 14% qualified names and 8% trace lines.
The retrieval stack embeds whatever text it is given, in 512-token windows.

## Decision

- **Chunks are plain text.** Pages remain Markdown for people.
- **Meaning before structure:**
  - an element's chunk leads with what it is and does;
  - structural detail follows, in the same chunk when everything fits;
  - otherwise it goes in a `<kind>:details` chunk inside `chunks.jsonl`.
- **One style only.** A tree that stored the Markdown style warns and goes on with plain chunks.

## Evidence

- **Plain chunks were never significantly worse than Markdown.**
- **The natural questions:** e5-large's MRR rose from 0.61 to 0.70, and bge-large's from 0.67 to
  0.75.
- **BM25** found requirements by id 20 times in 20, against 6 in 20.
- **Half the tokens to embed:** 8.1 M against 17.2 M.
- **Details:** kept in a separate file outside the index, questions about members, ports and
  tagged values were lost (e5-large top 10 fell from 0.92 to 0.81).

## Consequences

One chunk path (`chunks.make`, `plain.pack`), with no branching by style (ADR-0008).
