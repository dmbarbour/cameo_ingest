# ADR-0001: Read XMI by its conventions, not by a metamodel

- **Status:** Accepted, 2026-09-29.
- **Sources:**
  - review BASE: BASE-001R1, R4 and R5 (`docs/archive/reviews/baseline-2026-09-29.md`);
  - `docs/design/architecture.md`.

## Context

Cameo projects use UML, SysML and any number of custom profiles (TMT_Requirement, ReqIF, UAF),
and their metamodels change between Cameo versions. A parser written against a metamodel breaks
on each new profile or version.

## Decision

`xmi.py` relies only on XMI's own conventions:
- a node with `xmi:id` is an element;
- a node with `xmi:idref` or `href` is a reference;
- a top-level node with a `base_*` attribute is a stereotype application.

Attribute values that are known ids become references in a second pass. Only bare, versioned OMG
URIs count as `uml` or `xmi` (BASE-001R1): Cameo declares its own profiles under the OMG domain.
UML and SysML meaning (`semantics.py`) is a best-effort layer on top.

## Consequences

- **Robustness:** new profiles and Cameo versions need no code changes. Stereotype tags that hold
  several ids are resolved to names (BASE-001R4).
- **Memory:** parsing streams (`iterparse`). TMT (27 MB zipped, 71,000 elements) peaks at
  about 400 MB and parses in about 3 s.
- **Best effort:** interpretation can miss a construct no sample shows; «Trace» and «Refine»
  wording is covered only by the synthetic fixture.
