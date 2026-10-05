# ADR-0029: Generated text says what a package or diagram is about and for

- **Status:** Accepted, 2026-10-05 (plan GS, 0.20.0; the maintainer: "If the purpose is to
  support 'aboutness' and paraphrased searches, perhaps we shouldn't waste our budget on proper
  nouns or exact values"; "Yes, about should replace summaries").
- **Sources:**
  - `docs/plans/generated-for-search-2026-10-05.md`;
  - `docs/research/generated-for-search-2026-10-05.md`;
  - ADR-0028, which this replaces for `rag/`; ADR-0011.

## Context

- **The requests asked for names:** a package's "purpose, main elements, and how they relate",
  with the names as written; a diagram's purpose from its legend and connections. 73% of
  package-summary inputs on the samples hold no documentation at all, so the answers were
  inventories of names, which crowded out answers in retrieval. ADR-0028 left them out of `rag/`.
- **What search by meaning needs** is what the names don't say: what a thing is for, in the words
  a person would use.

## Decision

- **The requests for package summaries, part summaries, syntheses, instance digests and diagram
  descriptions** ask what the package or diagram is about and what it is for, in everyday words
  and the domain's common terms, inferring purpose where the input implies it. No element names,
  identifiers or exact values. At most 80 words.
- **With context:** a package's surroundings and the documented elements it refers to; a
  diagram's context element, and its shapes' documentation and a state's behaviors.
- **A class first,** kept in the chunk's metadata (`about_class`) as information. No class is left
  out of `rag/`: none sorted the helpful from the crowding.
- **The same text everywhere:** on the pages, in `chunks.jsonl` and in `rag/`, which leaves nothing
  out again.
- **Module and image descriptions are unchanged.** Text calibration probes with the pre-0.20 part
  request, which names what it covers and so can be scored.

## Consequences

- **Measured on the fiction** (246 questions; hybrid reranked MRR@10, against `rag/` without
  generated text): questions about where something is described 0.583 → 0.814 (significant;
  hit@10 0.75 → 1.00); list questions 0.708 → 0.823; the 226 standing questions 0.791 → 0.783
  (not significant), where the requests before cost them 0.027 (significant).
- **On the whole tree** (the release check): where-is questions 0.593 → 0.772 (significant), the
  standing questions 0.793 → 0.780 (significant), against `rag/` without generated text; against
  0.19.0's requests, better wherever significant.
- **Read on real models:** 20 of 20 package answers faithful; 19 of 20 diagram answers, one
  misreading a swimlane, several ending with a generic purpose the input doesn't state.
- **Pages** say what a package or diagram is for, where they listed its names.
