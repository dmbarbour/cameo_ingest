"""Where the evaluation's models run, in one place (AR-017R3): DeepInfra (plan RE, decisions 7 and
8), through its OpenAI-compatible API (judges, question writers, embeddings) and its own
inference API (rerankers). Both take the key in OPENAI_API_KEY.

The ingest's LLM is configured apart (`llm.LLMConfig`, from OPENAI_BASE_URL): it serves any
compatible endpoint.
"""

from __future__ import annotations

import json
import logging
import os
import time
import urllib.error
import urllib.request
from typing import Any

from ..llm import LLMConfig

log = logging.getLogger(__name__)

OPENAI_API = "https://api.deepinfra.com/v1/openai"
INFERENCE_API = "https://api.deepinfra.com/v1/inference"
KEY_ENV = "OPENAI_API_KEY"


def chat_config(model: str, timeout: float = 120.0, retries: int = 2) -> LLMConfig:
    """A judge's or question writer's configuration: text only, no budget."""
    return LLMConfig(text_model=model, vision_model=None, base_url=OPENAI_API, timeout=timeout, retries=retries)


def openai_client(retries: int, timeout: float = 120.0):
    """The SDK's client for the OpenAI-compatible API; it retries busy (429) and failed requests."""
    from openai import OpenAI

    return OpenAI(base_url=OPENAI_API, api_key=os.environ[KEY_ENV], timeout=timeout, max_retries=retries)


def post_json(url: str, body: dict[str, Any], retries: int, timeout: float = 120.0) -> dict[str, Any]:
    """POST `body` to the inference API and read the reply. A busy endpoint (HTTP 429), a server
    error or a lost connection is retried, waiting 1, 2, 4... seconds; a bad request is not,
    since retrying won't fix it."""
    data = json.dumps(body).encode()
    headers = {"Content-Type": "application/json", "Authorization": f"Bearer {os.environ[KEY_ENV]}"}
    for attempt in range(retries + 1):
        try:
            with urllib.request.urlopen(urllib.request.Request(url, data=data, headers=headers),
                                        timeout=timeout) as resp:
                return json.load(resp)
        except urllib.error.HTTPError as e:
            detail = e.read()[:300].decode("utf-8", "replace")
            if e.code != 429 and e.code < 500 or attempt == retries:
                raise RuntimeError(f"{url}: HTTP {e.code}: {detail}") from e
            log.debug("request to %s failed (HTTP %s); retrying", url, e.code)
        except (urllib.error.URLError, TimeoutError, ConnectionError) as e:
            if attempt == retries:
                raise
            log.debug("request to %s failed (%s); retrying", url, e)
        time.sleep(2 ** attempt)
    raise AssertionError("unreachable")
