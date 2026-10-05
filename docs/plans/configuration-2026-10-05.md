# Plan: configuration through `cameo-ingest config`, 2026-10-05

- **Status:** Decided on 2026-10-05 (the maintainer's answers, below); CP1 next.
- **Step prefix:** `CF`, so steps are `CF-01`, `CF-02` and so on.
- **Addresses:** the maintainer, 2026-10-05, trying the tool:
  > "getting set up is a bit confusing: too many configuration options independent of current
  > action. I'd suggest moving most things to `cameo-ingest config`. Enable users to update
  > persistent configuration options only through this API. Support an interactive-mode
  > configuration (e.g. `cameo-ingest config -i`) that actually tests options like access to
  > openai models, and perhaps queries available models at an endpoint for guidance."

## Why

A setting can come from three places today, with precedence rules between them:
- **About 20 flags on every run command,** "remembered by the output tree": models, timeout,
  retries, call budget, concurrency, the LLM store's directory, image pixels, module sizes, part
  size, three sketch sizes, image order, calibrate, render, `rag/` and its source form.
- **`--env FILE`,** a dotenv file loaded into the environment, where variables already set win.
- **Eight environment variables:** `OPENAI_API_KEY`, `OPENAI_BASE_URL`, `OPENAI_MODEL`, and
  `CAMEO_INGEST_TEXT_MODEL`, `_VISION_MODEL`, `_LLM_MAX_CALLS`, `_LLM_TIMEOUT`, `_LLM_RETRIES`,
  `_DEST`.

Nothing checks that the endpoint answers, that a key works, or that a model takes images, until a
run fails partway. Many of the flags are heuristics that ADR-0027 says should be measured
defaults, not settings.

## Decisions (the maintainer, 2026-10-05)

> "I think we should keep most things per tree. Writing `-o` per op is still annoying, so we can
> still support `CAMEO_INGEST_TREE`, and support a default local working directory, e.g.
> `./ingest_tree/`. The API key can still be OPENAI_API_KEY, and URL as OPENAI_BASE_URL as those
> are independent conventions. […] LLM answer store per user is fine, but that should be
> adjustable by independent environment var, e.g. `CAMEO_INGEST_CACHE`, enabling us to share
> target-independent tasks like vision calibration. `--no-llm` is also per-tree. All configuration
> options should be reversible. I don't have any `.env` files that need moving."

| # | Question | Decision |
|---|---|---|
| D1 | Where configuration lives | **Per tree,** in its `state.sqlite`, changed only through `cameo-ingest config`. |
| D2 | Which tree a command works on | `-o OUT`; else `CAMEO_INGEST_TREE`; else `./ingest_tree/`. `CAMEO_INGEST_DEST` goes. |
| D3 | The endpoint and its key | `OPENAI_BASE_URL` and `OPENAI_API_KEY`, the OpenAI clients' own conventions, from the environment; never stored. |
| D4 | The LLM answer store and calibrations | **Per user,** `~/.cache/cameo-ingest/` by default, or `CAMEO_INGEST_CACHE`; shared by every tree, so that a model is calibrated once (calibration doesn't depend on the tree). A tree records the calibration it used. |
| D5 | Whether a tree uses the LLM | A tree setting (`config set llm off`), as its models are; no `--no-llm` on runs. |
| D6 | Reversibility | Every setting can be set and unset (back to its default), and every switch turned either way. |
| D7 | Moving from `.env` | Nothing: `--env` goes, with no import. |

**The model's identity** (the maintainer: "is there a good way to query for a GUID/Hash/stable
version of the remote model? Or we just treat the model as a full URL in our databases"):
OpenAI-compatible endpoints offer no version hash. `GET /models` gives an id, usually a creation
time, and an owner. Some providers publish dated snapshots (`gpt-4o-2024-08-06`) and others don't
(`google/gemma-4-31B-it`). So the identity is the endpoint and the model id, as the store and
calibrations are already keyed; a tree also records the creation time the endpoint reports, when
there is one, and warns when it changes.

## Design

- **Commands take only what is about the action:** inputs and `--meta`; `-o` when not the default
  tree; `-v` and `--log-file`. The settings flags leave the run commands.
- **`cameo-ingest config`** (on the tree chosen as in D2):
  - `config show`: each setting, its value and whether it is the default;
  - `config set KEY VALUE` and `config unset KEY` (D6);
  - `config test`: the endpoint answers, the key is accepted, each model answers a short text
    request, and the vision model reads a small drawn card;
  - `config models`: the endpoint's models, those already calibrated marked;
  - `config -i`: interactive, in order: the endpoint and key from the environment checked (and
    what to set if they are missing), the LLM on or off, the models offered from `config models`,
    a test of each, calibration if the store has none for them (its cost stated), then the
    switches, and a summary before anything is saved.
- **What stays a setting** is what a user can judge (ADR-0027): `llm` on or off, `text-model`,
  `vision-model`, `render`, `rag-files`, `rag-source`, `concurrency`, `max-calls` (per run).
  Image pixels, module sizes, part size, sketch sizes and image order come from calibration or
  defaults; timeout and retries are fixed. A tree that remembers a retired setting is told it is
  ignored.
- **A new tree** asks for its configuration once: a run with no `llm` setting stops with the
  `config` commands that set one, as BASE-020 now does with "name a model or pass --no-llm".
- **Errors point to the fix:** a refused key names `OPENAI_API_KEY`; a missing model names
  `config set text-model`.

## Steps

| Step | What | Status |
|---|---|---|
| CF-01 | **Which tree:** `-o`, `CAMEO_INGEST_TREE`, then `./ingest_tree/` (D2), for every command; `CAMEO_INGEST_DEST` retired with a notice. Tests. | |
| CF-02 | **`config show`, `set`, `unset`:** each setting described, checked and reversible (D6); `llm` on or off (D5). Tests. | |
| CF-03 | **The endpoint:** `OPENAI_BASE_URL` and `OPENAI_API_KEY` only (D3); `config test` and `config models`; the model's identity and creation time recorded. Tests with a fake endpoint; once against DeepInfra. | |
| CF-04 | **The shared store:** the LLM answers and calibrations per user (`CAMEO_INGEST_CACHE`, D4), a tree's existing store still read; the tree records the calibration it used. Tests. | |
| CF-05 | **Runs read the tree's configuration only:** the settings flags, `--env` and the other variables go; retired settings noticed. Tests. | |
| CF-06 | **`config -i`.** Tests with scripted input. | |
| CF-07 | **Developers, docs and release:** the evaluation scripts read `OPENAI_*` from the environment; the README's setup rewritten around `config -i`; ADR-0004 and ADR-0010 updated, a new ADR; a release check; 0.21.0. | |

## Checkpoints

| Checkpoint | Steps | Delivers |
|---|---|---|
| CP1: the tree and its settings | CF-01, CF-02 | `config show/set/unset`, the default tree |
| CP2: the endpoint and the store | CF-03, CF-04 | `config test/models`, a shared store |
| CP3: one source | CF-05 | Runs read the tree's configuration only |
| CP4: interactive, docs | CF-06, CF-07 | `config -i`; 0.21.0 |

## When to stop and ask

- **Before CP3,** which removes flags and variables users may have in scripts: a look at the
  README's new setup section.
- **If an endpoint lists no models,** or lists them without saying which take images, `config -i`
  falls back to asking for names and testing them; whether that is good enough goes to the
  maintainer.
