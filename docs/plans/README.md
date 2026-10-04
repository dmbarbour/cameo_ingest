# Plans

Plans being carried out live here, as `docs/plans/<name>-<YYYY-MM-DD>.md`. Future work that isn't a
plan yet is in `docs/roadmap.md`. When a plan is done, its content goes to `docs/design/`,
`docs/decisions/` and `docs/roadmap.md`, and the plan moves whole to `docs/archive/plans/`
(conventions in `docs/README.md`).

## Active

| Plan | Prefix | Status |
|---|---|---|
| [Inputs cut by us, and calibrating to the configured text model](text-calibration-2026-10-04.md) | TC | CP1 in progress |

## Archived

All retired on 2026-10-03.

| Plan | Prefix | Done | Its content now |
|---|---|---|---|
| [Resumable, content-addressed ingest](../archive/plans/resumable-ingest-2026-09-29.md) | RI | 2026-09-29 | ADR-0002, 0003, 0004; design/architecture |
| [Measuring LLM enrichment quality](../archive/plans/llm-quality-2026-09-30.md) | LQ | LQ-01 to LQ-03, 2026-09-30; the judge panel deferred | ADR-0009; design/llm-enrichment; roadmap |
| [Modular views of large diagrams and packages](../archive/plans/diagram-views-2026-09-30.md) | DV | 2026-09-30 | ADR-0013; design/diagrams, design/llm-enrichment; roadmap |
| [Retrieval evaluation](../archive/plans/retrieval-evaluation-2026-09-30.md) | RE | Its decisions in force; a spot check and some measures left | ADR-0006, 0007, 0022; design/evaluation; roadmap |
| [Related facts brought together](../archive/plans/related-facts-2026-10-01.md) | RF | 2026-10-01; facet lists deferred | ADR-0007, 0019; design/output-and-chunks; roadmap |
| [Refactoring after the architecture review](../archive/plans/refactoring-2026-10-02.md) | RA | 2026-10-02 (0.7.2) | ADR-0008, 0009, 0023; design/architecture |
| [Searching the corpus without tools](../archive/plans/keyword-export-2026-10-02.md) | KX | CP1 to CP4 (0.8.0 to 0.8.3); the maintainer's trial pending | ADR-0021; design/exports; roadmap |
| [Labels for references outside a project](../archive/plans/used-project-labels-2026-10-02.md) | UL | 2026-10-02 (0.9.0) | design/output-and-chunks; roadmap |
| [Versions of a model, and removing projects](../archive/plans/project-versions-2026-10-03.md) | PV | 2026-10-03 (0.10.0) | ADR-0020; design/versions |
| [Calibrating sketches to the vision model](../archive/plans/vision-calibration-2026-10-03.md) | VC | 2026-10-03 (0.12.0) | ADR-0014, 0015; design/vision-calibration |
| [Calibrating to the configured vision model, and validating](../archive/plans/vision-autocalibration-2026-10-03.md) | VA | 2026-10-03 (0.13.0) | ADR-0015, 0016; design/vision-calibration; roadmap |
| [Sketches that read as drawn, and a release check](../archive/plans/sketch-ambiguities-2026-10-03.md) | SK | 2026-10-03 (0.14.1) | ADR-0017, 0018; design/diagrams, design/vision-calibration; roadmap |

## Reviews

All closed and archived in `docs/archive/reviews/`:

| Review | Prefix | Its content now |
|---|---|---|
| [Baseline](../archive/reviews/baseline-2026-09-29.md), closed 2026-09-30 | BASE | ADR-0001 to 0005, 0010; design/architecture, design/output-and-chunks |
| [Follow-up](../archive/reviews/followup-2026-09-30.md), closed 2026-09-30 | FU | ADR-0011, 0012; design/llm-enrichment, design/diagrams |
| [Architecture](../archive/reviews/architecture-2026-10-01.md), closed 2026-10-02 | AR | ADR-0008, 0009, 0023; design/architecture; AR-002's escapes fixed in 0.15.2 |
