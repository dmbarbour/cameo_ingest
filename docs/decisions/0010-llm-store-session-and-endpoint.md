# ADR-0010: Any OpenAI-compatible endpoint, chosen explicitly; answers kept by request

- **Status:** Accepted, 2026-09-29 to 2026-10-02.
- **Sources:**
  - BASE-005R1 to R4, BASE-006R1 and R2, BASE-019R1 to R4, BASE-020R1 to R3, BASE-022R5 and R6;
  - AR-016R1 and R2, AR-017.

## Context

- **No silent switch-off:** the LLM used to turn off silently, and a bad key showed only after
  parsing.
- **Dead endpoints:** a dead endpoint could stall a run for about 50 hours (500 calls × 360 s).
- **Paying for answers once:** answers cost money, and must not be asked for twice.

## Decision

- **Any OpenAI-compatible endpoint:**
  - `OPENAI_BASE_URL` and `OPENAI_API_KEY`;
  - models by flag, then `CAMEO_INGEST_*_MODEL`, then `OPENAI_MODEL`;
  - the vision model defaults to the text model;
  - `--env` loads a dotenv file, and variables already set win.
- **An explicit choice:** with no model and no `--no-llm`, the tool exits 2 (while the tree has
  no settings). A preflight request checks each model before work starts (exit 5).
- **The answer store:**
  - `llm.sqlite`, keyed by (endpoint, model, request sha256), one transaction per answer;
  - a damaged file is moved aside;
  - prompts carry no locators, so the same content found in another file asks nothing new.
- **Replay:**
  - `--llm-replay` answers only from a recorded store, by model and request hash; a miss fails the
    project;
  - the committed fixture holds hashes, never prompts, so third-party model content stays out of
    git.
- **The session** (`EnrichmentSession`):
  - a call budget (none by default);
  - a breaker that switches enrichment off after 3 consecutive failures;
  - outcomes in `run.json`.
- **Concurrency:** `--llm-concurrency`, default 1 for local servers. Results attach in submission
  order, so the output is byte-identical to a sequential run.

## Consequences

- **Rebuilds are cheap:** reruns, rebuilds and new versions of the tool cost only the changed
  requests.
- **One cache base:** `SqliteCache` serves the response store, the embedding cache and the
  reranker's score cache.
