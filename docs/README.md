# Documentation

The top-level `README.md` is for users: how to run the tool and use its output. These are for
whoever maintains it.

| Where | What | Lifetime |
|---|---|---|
| `design/` | How each part works now, and why, with its constants and limits | Living: changed with the code |
| `decisions/` | Architecture decision records: one decision each, with its context and evidence | Permanent: superseded, never rewritten |
| `roadmap.md` | Open, deferred and tentative work | Living: items leave as they become plans |
| `plans/` | Plans being carried out, and the index of them | Until done, then archived |
| `reviews/` | Reviews still open | Until closed, then archived |
| `research/` | Dated notes of measurements and studies: the evidence that decisions cite | Permanent |
| `archive/` | Finished plans and closed reviews, kept whole so that their IDs can be searched | Permanent |

## Design documents

- [architecture](design/architecture.md): the pipeline, the modules and their layering, state
  and publishing, identifiers, robustness, and how a change is checked.
- [output and chunks](design/output-and-chunks.md): pages, chunks and what each carries,
  labels, `rag/`, the identifier index and threads.
- [LLM enrichment](design/llm-enrichment.md): what is asked, prompt principles, templates and
  versions, the endpoint, store and session, and measuring quality.
- [diagrams](design/diagrams.md): layout streams, the graph and its text, sketches and their
  notation, the SVG, and modules.
- [vision calibration](design/vision-calibration.md): where sizes come from, the eye charts, the
  rules, and validation on the tree's own sketches.
- [versions](design/versions.md): fingerprints, groups of versions, and removal.
- [exports](design/exports.md): the catalog, the workbook, the search page, and their scale.
- [evaluation](design/evaluation.md): how retrieval is measured, and how two trees are compared.

## Conventions

- **Names:** plans are `docs/plans/<name>-<YYYY-MM-DD>.md`; reviews are
  `docs/reviews/<name>-<YYYY-MM-DD>.md`; research notes are `docs/research/<name>-<YYYY-MM-DD>.md`.
- **Reviews:** a review states its subject and method. It numbers its findings with a searchable
  prefix (`BASE-003`), and their remediation steps `BASE-003R1`, `BASE-003R2`. A remediation that
  can be finished before the review closes is written into the review.
- **Plans:** a plan has a step prefix (`VC-01`) and checkpoints. Its status and its steps' statuses
  are kept current as work lands. Commits and comments cite plan steps and finding IDs.
- **When a plan is done, or a review closed:**
  1. what still holds goes into `design/`;
  2. each decision worth keeping becomes an ADR in `decisions/`;
  3. what is left open goes into `roadmap.md`;
  4. the document moves whole to `archive/`, and the plan index notes where its content went.
- **ADRs** are numbered in order (`decisions/NNNN-<name>.md`), dated, and cite their sources. A
  change of decision is a new ADR that supersedes the old one, whose status then names it.
