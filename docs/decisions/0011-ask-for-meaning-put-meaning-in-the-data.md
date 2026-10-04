# ADR-0011: Ask for meaning; put meaning in the data

- **Status:** Accepted, 2026-09-30.
- **Sources:**
  - FU-004R1, FU-009R1, FU-013, FU-021R1, FU-010R1;
  - AR-018R1;
  - `docs/archive/reviews/followup-2026-09-30.md`.

## Context

Spot checks found that quality was lost "mostly in our input". The model invented no elements;
its own faults were invented structure and Markdown. A rule stated in the prompt (that
«DeriveReqt» reads backwards) was not enough: gemma still read it backwards twice.

## Decision

- **Ask for meaning,** in one request: what the diagram or package tells a reader, not the legend
  restated. A second, structural request was rejected, since the page already has the structure.
- **Plain prose:**
  - no headings, lists, bold or code;
  - names exactly as written;
  - grouping only as the diagram itself groups;
  - "when the diagram shows little, say little".
- **Put meaning in the data:**
  - each dependency carries its verb ("is derived from", "satisfies"), from one table in
    `semantics.RELATIONS`;
  - directions come from the model's relationships.
- **Inputs are plain text** (`Section.text`), without link targets, which cost about 110
  characters of path for a 15-character label (AR-018).
- **Cuts are announced:** an input cut to fit says so.
- **Trivial diagrams get no request:** fewer than 3 shapes, unless 2 are connected.

## Evidence

- **Format:** acceptable answers rose from 5 of 14 to 13 of 13.
- **Usefulness:** diagram usefulness rose from 3.6 to 4.25.
- **Plain inputs:** inputs cut to fit fell from 88 to 12, and requests from 6,994 to 6,122.

## Consequences

Plan SK qualified "rules don't work": reading guides, which say what a sketch's marks mean, help
measurably (ADR-0017). Verbs stay in the data.
