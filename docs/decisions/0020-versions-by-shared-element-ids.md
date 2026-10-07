# ADR-0020: Versions found by shared element ids; the tool reports, the maintainer removes

- **Status:** Accepted, 2026-10-03 (plan PV; the maintainer: "Plan is go"); updated on 2026-10-07 (Changes,
  below).
- **Sources:**
  - `docs/archive/plans/project-versions-2026-10-03.md`;
  - `docs/design/versions.md`.

## Context

The maintainer's sources are "a complete mess of great volume": 282 Cameo files, 125 or more of
them unique, many of them versions of one model. A switch that kept the latest version on every
run was considered, and rejected as riskier: two vendors may have started from the same model (a
fork).

## Decision

- **Nothing is decided for the maintainer.** `scan`, `projects` and `groups` report; `remove` and
  `restore` act.
- **Versions are found by shared element ids:** Cameo keeps `xmi:id` across saves. Project ids
  are not used alone, since a model made from a template keeps the template's. Since 0.23.0, who
  made each side's own ids, and when, decides whether two models are versions or rivals (ADR-0032);
  this rule (Jaccard 0.5, or 80% of the smaller) serves where ids name no makers.
- **Newest by save time,** from `Records.properties`, which copying doesn't change. The zip's
  dates are a flagged fallback.
- **Removals outlive their inputs,** in a `removed` table: `run` skips a removed project even when
  it turns up again. Its LLM answers stay in the store.

## Evidence

TMT and TMT-2024x share 69,613 ids (88% Jaccard, 98% of the smaller). No other pair of samples
shares more than one id.

## Consequences

`groups` warns of possible forks, and of missing save times, and suggests a `remove` line only for
groups without warnings.

## Changes

- 2026-10-07: versions told from rivals by who made the ids and when (ADR-0032); this rule is the
  fallback. Before: `3c254db`.
