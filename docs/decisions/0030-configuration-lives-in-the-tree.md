# ADR-0030: Configuration lives in the tree, set only through `config`

- **Status:** Accepted, 2026-10-05 (plan CF, 0.21.0; the maintainer: "Four recognized environment
  vars, all other configuration in tree, cache for the shared stuff").
- **Sources:**
  - `docs/archive/plans/configuration-2026-10-05.md`;
  - ADR-0004 and ADR-0010, which this changes; ADR-0027.

## Context

- **Three sources, with precedence between them:** about 20 flags on every run, remembered by the
  tree; `--env FILE`, a dotenv file; and eight environment variables. The maintainer, trying the
  tool: "getting set up is a bit confusing: too many configuration options independent of
  current action."
- **Nothing checked the setup** (the endpoint, the key, whether a model takes images) until a run
  failed partway.
- **Most flags were heuristics,** which ADR-0027 says should be measured defaults.

## Decision

- **Four environment variables, and no others:**
  - `OPENAI_BASE_URL` and `OPENAI_API_KEY`, the OpenAI clients' own conventions, never stored;
  - `CAMEO_INGEST_TREE`, the tree when `-o` is not given; else `./ingest_tree`;
  - `CAMEO_INGEST_CACHE`, the LLM store, per user; else `~/.cache/cameo-ingest`.
- **Everything else is the tree's,** in its `state.sqlite`, set only with `cameo-ingest config`:
  - `config set KEY VALUE` and `config unset KEY` (back to the default); `config export` and
    `config import`, the tree's own settings as JSON (0.31.0, RN-005);
  - eight settings, each reversible: `llm`, `text-model`, `vision-model`, `render`, `rag-files`,
    `rag-source`, `concurrency`, `max-calls`.
- **Runs take only what is about the action:** inputs, `--meta`, `-o`, `-v`, `--log-file`. Four
  flags stay for developers, hidden and never remembered: `--no-calibrate`, `--no-preflight`,
  `--llm-replay`, `--heartbeat`.
- **Sizes come from calibration or defaults** (ADR-0027): pixel budget, sketch sizes, modules,
  image order and part size. Timeout and retries are fixed, 120 s and 2.
- **Checks:** `config test` (each model answers; the vision model reads a drawn number) and
  `config models` (the endpoint's list).
- **A model's identity** is the endpoint and the model's id: OpenAI-compatible endpoints give no
  version hash. A tree notes the creation time the endpoint reports, and warns when it changes.
- **The LLM store is shared** by every tree, calibration answers included, so a model is
  calibrated once; a tree records the calibration it used.

## Consequences

- **One place for each setting,** and no precedence rules.
- **A breaking change:** scripts that passed settings as flags set them on the tree first. A tree
  that remembers a retired setting is told it is ignored.
- **Developer scripts** keep their own `--env` for a developer's `.env`; the tool never reads it.

## Changes

- 2026-10-08: `config -i` removed, and `config export` and `import` added (review RN, RN-005). Before: `883c382`.
