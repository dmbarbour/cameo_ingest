"""What the command line's commands share: opening a tree, and checking the endpoint."""

from __future__ import annotations

import logging
import sys
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

from ..llm import EnrichmentSession
from ..state import State

log = logging.getLogger("cameo_ingest")


@contextmanager
def open_tree(out: Path, lock: bool = False) -> Iterator[State]:
    """The tree's state, locked for writing if `lock`, closed after (CQ-009). A `StateError`
    (another process holds the lock, a newer schema) reaches `main`, which reports it."""
    state = State(out)
    try:
        if lock:
            state.lock()
        yield state
    finally:
        state.close()


def check_endpoint(llm: EnrichmentSession) -> bool:
    """The endpoint answers each model; False, with the error printed, when it doesn't."""
    cfg = llm.cfg
    log.info("checking LLM endpoint %s", cfg.base_url or "(OpenAI default)")
    err = llm.preflight()
    if err:
        print(f"error: LLM endpoint check failed ({cfg.base_url or 'OpenAI default endpoint'}): {err}\n"
              "Check OPENAI_BASE_URL and OPENAI_API_KEY, and the model's name (`cameo-ingest config test`).",
              file=sys.stderr)
    return not err

