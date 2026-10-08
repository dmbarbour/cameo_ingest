"""A tree's LLM: its models and budget from the tree's settings, at $OPENAI_BASE_URL, and the
shared store of answers (plan CF; review CQ-009, out of the command line).

- `llm_config`: the tree's models and call budget;
- `shared_store`: the per-user store (`config.store_dir`), with a tree's own store from before
  0.20.2 copied in once;
- `make_client`: the endpoint's client, for `config test` and `config models` (tests replace it);
- `note_models`: the creation time the endpoint gives each model, recorded and compared.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

from .config import TreeSettings, store_dir
from .llm import STORE_FILE, LLMConfig, ResponseStore
from .state import State

log = logging.getLogger(__name__)


def llm_config(settings: TreeSettings) -> LLMConfig:
    """The tree's models, call budget, timeout and time limit, at $OPENAI_BASE_URL (plan CF; RN-004)."""
    return LLMConfig.from_env(settings.text_model, settings.vision_model, max_calls=settings.llm_max_calls,
                              timeout=settings.request_timeout, time_limit=settings.request_time_limit)


def shared_store(out: Path) -> Path:
    """The LLM store's directory (`config.store_dir`), with a tree's own store from before 0.20.2
    copied into it once, so that nothing it paid for is asked again (plan CF-04)."""
    store = store_dir()
    old = out / ".cache" / STORE_FILE
    if not old.is_file() or not State.exists(out) or old.resolve() == (store / STORE_FILE).resolve():
        return store
    st = State(out)
    try:
        if st.meta("store_adopted") is None:
            shared = ResponseStore(store / STORE_FILE)
            try:
                shared.adopt(old)
            finally:
                shared.close()
            st.set_meta("store_adopted", str(store))
            log.warning("copied this tree's LLM answers (%s) into the shared store, %s", old, store)
    finally:
        st.close()
    return store


def make_client(cfg: LLMConfig) -> Any:
    """The endpoint's client, for checks (tests replace it)."""
    from .llm import OpenAIChat

    return OpenAIChat(cfg)


def note_models(out: Path, client: Any, cfg: LLMConfig) -> None:
    """Record, in the tree, the creation time the endpoint gives each configured model, and warn
    when it has changed: a model's identity is its endpoint and id, and this time is the only sign
    the endpoint gives that another model now answers to the id (plan CF-03)."""
    if not State.exists(out):
        return
    try:
        created = dict(client.models())
    except Exception:  # an endpoint that lists no models: nothing to compare
        return
    st = State(out)
    try:
        for model in dict.fromkeys(m for m in (cfg.text_model, cfg.vision_model) if m):
            key, now = f"model:{cfg.base_url or ''}|{model}", created.get(model)
            if now is None:
                continue
            before = st.meta(key)
            if before is not None and before != str(now):
                log.warning("%s at this endpoint reports another creation time (%s, was %s): it may be another "
                            "model under the same id", model, now, before)
            st.set_meta(key, str(now))
    finally:
        st.close()
