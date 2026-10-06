# Plan: configuration through `cameo-ingest config`, 2026-10-05

- **Status:** In progress: CP1 (0.20.2), CP2 (0.20.3) and CP3 (0.21.0) done; CP4 next. The
  maintainer approved the new setup before CP3: "Four recognized environment vars, all other
  configuration in tree, cache for the shared stuff."
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
| CF-01 | **Which tree:** `-o`, `CAMEO_INGEST_TREE`, then `./ingest_tree/` (D2), for every command; `CAMEO_INGEST_DEST` retired with a notice. Tests. | Done (0.20.2): `cli.tree_of`; tests strip the tree variables; `tests/test_cli.py::test_which_tree` |
| CF-02 | **`config show`, `set`, `unset`:** each setting described, checked and reversible (D6); `llm` on or off (D5). Tests. | Done (0.20.2): `config.SETTINGS` (llm, text-model, vision-model, render, rag-files, rag-source, concurrency, max-calls), `cli.configure`; setting one starts a tree; `tests/test_cli.py::test_config` |
| CF-03 | **The endpoint:** `OPENAI_BASE_URL` and `OPENAI_API_KEY` only (D3); `config test` and `config models`; the model's identity and creation time recorded. Tests with a fake endpoint; once against DeepInfra. | Done: `checks.run_checks` (the vision model reads a drawn 731), `OpenAIChat.models`, `cli.check_config`, `note_models` (the creation time per endpoint and model in the tree's `meta`, a warning when it changes); against DeepInfra, gemma-4 passes both, and Qwen3-235B as the vision model fails ("does not accept image input"); `tests/test_cli.py::test_config_test_and_models` |
| CF-04 | **The shared store:** the LLM answers and calibrations per user (`CAMEO_INGEST_CACHE`, D4), a tree's existing store still read; the tree records the calibration it used. Tests. | Done: `config.store_dir`; a tree's own store copied in once (`cli.shared_store`); calibration answers shared through the store; each test has its own store; `tests/test_llm.py::test_a_trees_own_store_joins_the_shared_store` |
| CF-05 | **Runs read the tree's configuration only:** the settings flags, `--env` and the other variables go; retired settings noticed. Tests. | Done (0.21.0, the breaking change, so CP4 is 0.21.1): `cli.tree_settings` (retired settings ignored with a notice, by runs and by `config set`); timeout and retries fixed (`llm.TIMEOUT`, `RETRIES`); `--no-calibrate`, `--no-preflight`, `--llm-replay`, `--heartbeat` kept for developers, hidden and not remembered; the tests set settings with `config set` (`tests/helpers.py::cli`); the live tests and `scripts/record_llm_fixture.py` take their model from their own `OPENAI_MODEL`; the README's configuration rewritten, `.env.example` for developers only |
| CF-06 | **`config -i`.** Tests with scripted input. | |
| CF-07 | **Developers, docs and release:** the evaluation scripts read `OPENAI_*` from the environment; the README's setup around `config -i`; the design docs; ADR-0004 and ADR-0010 updated, a new ADR; a release check; 0.21.1. | |

## Checkpoints

| Checkpoint | Steps | Delivers |
|---|---|---|
| CP1: the tree and its settings | CF-01, CF-02 | `config show/set/unset`, the default tree |
| CP2: the endpoint and the store | CF-03, CF-04 | `config test/models`, a shared store |
| CP3: one source | CF-05 | Runs read the tree's configuration only |
| CP4: interactive, docs | CF-06, CF-07 | `config -i`; 0.21.1 |

## The setup after CP3 (a draft of the README's, for the maintainer's look)

> **Setting up.** The LLM endpoint and its key are the OpenAI clients' own variables; everything
> else is the tree's, set with `cameo-ingest config`.
>
> ```
> export OPENAI_BASE_URL=https://api.deepinfra.com/v1/openai   # any OpenAI-compatible endpoint; unset for OpenAI
> export OPENAI_API_KEY=...
> cd my-work
> cameo-ingest config -i            # choose and test the models, calibrate: saved in ./ingest_tree
> cameo-ingest path/to/models/      # ingest into ./ingest_tree
> cameo-ingest status
> ```
>
> - **Another tree:** `-o DIR` on any command, or `export CAMEO_INGEST_TREE=DIR`.
> - **Without the LLM:** `cameo-ingest config set llm off` (and `on` again).
> - **The settings:** `config show`; `config set KEY VALUE`; `config unset KEY`, back to the
>   default. `llm`, `text-model`, `vision-model`, `render`, `rag-files`, `rag-source`,
>   `concurrency`, `max-calls`.
> - **Checks:** `config test` (the endpoint, the key, each model; the vision model reads a drawn
>   number); `config models [TEXT]`.
> - **The LLM store:** answers and calibrations, shared by every tree, in `~/.cache/cameo-ingest`, or
>   `$CAMEO_INGEST_CACHE`.
>
> These four variables are all there is: `OPENAI_BASE_URL`, `OPENAI_API_KEY`,
> `CAMEO_INGEST_TREE`, `CAMEO_INGEST_CACHE`. Since 0.21.0, `--env`, the model and LLM flags,
> `OPENAI_MODEL` and the other `CAMEO_INGEST_*` variables are gone; a tree that remembers one of
> its old settings is told it is ignored.

## When to stop and ask

- **Before CP3,** which removes flags and variables users may have in scripts: a look at the
  README's new setup section.
- **If an endpoint lists no models,** or lists them without saying which take images, `config -i`
  falls back to asking for names and testing them; whether that is good enough goes to the
  maintainer.
