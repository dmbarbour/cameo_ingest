# Design: LLM enrichment

What the LLM is asked, how, and how its answers are kept and judged. Decisions: ADR-0005, 0009 to
0011, 0013, 0017.

## What is asked

| Template (current) | For | Input | Words |
|---|---|---|---|
| `diagram-description@v6` | A diagram drawn whole | The sketch, the legend, the connections, a reading guide | 150 |
| `module-description@v3` | A module of a large diagram | The module's sketch, legend, connections within and with other modules, a reading guide | 120 |
| `diagram-synthesis@v2` | A large diagram as a whole | The overview sketch, the modules' descriptions, the connections between modules | 200 |
| `image-description@v2` | An embedded image | The image alone (its owner isn't linked yet) | 200 |
| `package-summary@v4` | A package of up to 12,000 characters | Its sections as plain text | 150 |
| `module-summary@v3` | A part of a large package | The part's sections | 120 |
| `package-synthesis@v3` | A large package | Its parts' summaries, through runs of at most 30 | 200 |
| `instances-summary@v2` | A package at least 80% instance specifications | A digest of its instances by classifier and slot | 150 |

- **Trivial diagrams get no request:** fewer than 3 shapes, unless 2 are connected
  (`skipped_trivial`).
- **Rounds:** requests run in rounds. Modules and parts go first; then the descriptions and
  summaries built from their answers.
- **The digest** (FU-022):
  - the counts of instances and classifiers;
  - up to 10 top-level instances (those no slot refers to);
  - per classifier, up to 40 of them: the count, 3 example names, and the features its slots set,
    with up to 3 values each.

  It is cut at 8,000 characters; the package's other sections at 4,000 (`DIGEST_CHARS`).

## Limits

Named constants in `prompts.py`, interpolated into the slot descriptions:

| Constant | Value | Means |
|---|---|---|
| `DIAGRAM_ITEMS` | 150 | Shapes and connections listed per request; more are cut, with a note |
| `SUMMARY_CHARS` | 12,000 | A package larger than this is summarized in parts |
| `PART_CHARS` | (3,000, 12,000) | A part's size |
| `OWN_CHARS` | 6,000 | A large package's own section, in its synthesis |
| `MAX_SUMMARIES` | 30 | Summaries per synthesis request; more go in runs |
| `DIGEST_CHARS` | (8,000, 4,000) | The instance digest, and the package's other sections |
| `enrich.INSTANCE_SHARE` | 0.8 | The share of instance specifications that calls for a digest |

Nothing is cut to fit a part (plan TC-01, 0.15.3). A part over 12,000 characters is repacked
(`enrich.repack`): its sections, in order, in as few requests as fit. A section longer than a part
goes in pieces (`enrich.pieces`), cut between lines (or words), each headed by its title and
"(piece i of n)", each a part of its own. Plan TC proposes calibrating the part size to the
configured text model.

## How prompts are written

The principles from the spot checks (`docs/archive/reviews/followup-2026-09-30.md`) and later
plans:
- **Ask for meaning, not a restated legend:** the legend and connections are "already recorded
  exactly" (ADR-0011).
- **Plain prose:**
  - no headings, lists, bold or code;
  - names exactly as written;
  - group only as the diagram or package itself does.
- **"When the diagram shows little, say little."**
- **Put meaning in the data:** each dependency carries its verb, and directions come from the
  model. A rule stated in the prompt alone was not enough.
- **Say when the input was cut,** with a versioned fragment.
- **Refer to modules and parts by what they do,** never by number: "sends it to M2" means nothing
  outside the page (module-description v2).
- **Tell the model how to read the image:** each sketch's request carries a reading guide, one
  sentence per drawing convention the sketch uses (ADR-0017; `prompts.GUIDE`,
  `sketch.conventions`).
- **Inputs are plain text** (`Section.text`), without link targets or trace lines. The prompt, and
  so the stored answer, depends only on the model's content, not on where it was found
  (BASE-022R6, AR-018). Diagram legends and connections are plain too, without Markdown's escapes
  (`diagram_text.PLAIN`; AR-002, 0.15.2): `T/T < Threshold`, not `T/T \< Threshold`.

Quality was lost "mostly in our input". The model invented no elements; its own faults were
invented structure and Markdown. Residual: gemma calls «DeriveReqt» links "refinements", though it
reads their direction right.

## Templates and versions

ADR-0009.
- **`Template`:**
  - `id` and `version` (the key is `id@vN`), and `purpose`;
  - `text` with `{{SLOT}}` markers;
  - `slots`, text or image, each described;
  - `image_first`, the default place of the image;
  - `fragments`, every sentence a request may add.

  `render` fills the slots in one pass, so slot values are never scanned for markers, and
  `stand_in()` shows a template as a reviewer should see it.
- **One builder per template** in `prompt_values.py`, returning `Values(values, notes, cut)`.
- **Versions:**
  - a change of text or fragments is a new version, never a number used before;
  - one version per id is in the code (an assert), and `CURRENT` and `TEMPLATES` derive from one
    tuple;
  - the keys in use are part of each project's options;
  - a test pins each one's request by hash;
  - retired versions are at tag `studies-2026-10-02`.
- **Outside `CURRENT`:** calibration (`eye-read`, `eye-arrows`) and validation (`eye-sketch`) have
  their own templates, as do the evaluation's judge and question writer.

## The endpoint, the store and the session

ADR-0010 (`llm.py`, `sqlite_cache.py`).
- **The client:** `ChatClient` is `OpenAIChat` (any OpenAI-compatible endpoint) or `ReplayChat`
  (`--llm-replay`, a miss fails the project); `connect()` makes the run's.
- **The preflight:** "Reply with the single word OK.", and the vision check sends a 32 × 32 white
  PNG. It bypasses the store and the budget, and failure exits 5.
- **The store,** `ResponseStore` in `OUT/.cache/llm.sqlite` (or `--cache-dir`):
  - answers keyed by (endpoint, model, request sha256);
  - a `requests` log of each request's template, project, item, slot values, the rendered prompt,
    image sha256 and path, and notes (such as `truncated`, or `scaled` for a shrunk image).

  The committed replay fixture drops the log, so prompts built from third-party models never reach
  git. Replay matches on model and hash only.
- **The session,** `EnrichmentSession`:
  - a call budget (`--llm-max-calls`, none by default);
  - a breaker that switches enrichment off after 3 consecutive failures;
  - outcomes (`answered`, `cached`, `replayed`, `skipped_*`, `failed`, `truncated_input`) for
    `run.json`;
  - the image's place: the call's, then the calibrated, then the template's (ADR-0015).

  A replayed answer bypasses the store, the budget and the breaker. A failed write to the store is
  logged, and the answer kept.
- **Concurrency:** `--llm-concurrency`, default 1. Results attach in submission order, so the
  output is byte-identical to a sequential run.
- **Cost for reference** (gemma-4 at DeepInfra):
  - a text request takes about 0.5 s, a vision request about 11 s;
  - the samples and fiction come to about 6,100 requests, and a full rebuild of their descriptions
    (2,451 new requests) cost about $1.50 to $2 in 56 minutes at concurrency 8.

  Counting what a change will cost: run with `--llm-max-calls 0` against a copy of the store; the
  changed requests show as `skipped_budget`.

## Measuring quality

Plan LQ (`docs/archive/plans/llm-quality-2026-09-30.md`).
- **Spot-check sets:** `cameo-ingest quality sample -o OUT [--n 30] [--seed 1] [--kind KIND]` draws
  an immutable set under `OUT/quality/<stamp>-seed<seed>/`:
  - `items.jsonl`, `templates.jsonl` and `index.html`;
  - the rating sheets `rate-items.csv` and `rate-templates.csv`, copied to
    `ratings-*-<rater>.csv`.

  Kinds take turns; within a kind, items whose input was cut make up to half.
- **Matching:** items are found by joining the tree's `generated:*` chunks to the request log on
  (model, prompt sha256). A long answer's pieces are rejoined by `annotation`. Items older than the
  log are counted as "unexplained".
- **Rubrics:**
  - items are rated faithful, errors and omissions, useful (1 to 5), format, and fault (model or
    input);
  - templates are rated clear, grounded, context, accurate, output_spec: "the quality of the
    question limits the quality of the answer".
- **Rating is local:** in the page and CSV, never uploaded.
- **Spot checks so far:** faithful rose from 11 of 14 to 12 of 13 after the follow-up review's
  fixes, and mean usefulness from 3.9 to 4.4.
- **The judge panel** (LQ-04 to LQ-06) is deferred (roadmap).
