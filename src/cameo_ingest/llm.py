"""Optional LLM enrichment through any OpenAI-compatible endpoint (e.g. a local gemma).

Configuration (environment):
    OPENAI_API_KEY, OPENAI_BASE_URL   standard OpenAI client settings
    CAMEO_INGEST_TEXT_MODEL           model for summaries; LLM use is off when unset
    CAMEO_INGEST_VISION_MODEL         model for image descriptions (default: text model)
    CAMEO_INGEST_LLM_TIMEOUT          seconds per request (default 120)
    CAMEO_INGEST_LLM_MAX_CALLS        hard cap on requests per run (default 500)

Responses are cached on disk keyed by (model, prompt, image hash) so re-runs are cheap
and reproducible. Failures are logged and skipped: enrichment never breaks ingestion.
"""

from __future__ import annotations

import base64
import json
import logging
import os
import threading
from dataclasses import dataclass
from pathlib import Path

from .provenance import Derivation, sha256_bytes, sha256_text

log = logging.getLogger(__name__)


@dataclass
class LLMConfig:
    text_model: str | None
    vision_model: str | None
    base_url: str | None
    timeout: float = 120.0
    max_calls: int = 500

    @classmethod
    def from_env(cls, text_model: str | None = None, vision_model: str | None = None) -> LLMConfig:
        tm = text_model or os.environ.get("CAMEO_INGEST_TEXT_MODEL") or None
        vm = vision_model or os.environ.get("CAMEO_INGEST_VISION_MODEL") or tm
        return cls(
            text_model=tm,
            vision_model=vm,
            base_url=os.environ.get("OPENAI_BASE_URL"),
            timeout=float(os.environ.get("CAMEO_INGEST_LLM_TIMEOUT", "120")),
            max_calls=int(os.environ.get("CAMEO_INGEST_LLM_MAX_CALLS", "500")),
        )

    @property
    def enabled(self) -> bool:
        return bool(self.text_model or self.vision_model)

    def public(self) -> dict:
        # Never record the API key.
        return {"text_model": self.text_model, "vision_model": self.vision_model, "base_url": self.base_url}


class LLM:
    def __init__(self, cfg: LLMConfig, cache_dir: Path):
        self.cfg = cfg
        self.cache_dir = cache_dir
        self.calls = 0
        self._lock = threading.Lock()
        self._client = None
        if cfg.enabled:
            from openai import OpenAI

            # The client reads OPENAI_API_KEY itself; local servers often need no key.
            self._client = OpenAI(
                base_url=cfg.base_url,
                api_key=os.environ.get("OPENAI_API_KEY") or "unused",
                timeout=cfg.timeout,
                max_retries=2,
            )

    def _complete(self, model: str, messages: list[dict], key_material: str) -> str | None:
        key = sha256_text(json.dumps([model, key_material]))
        cpath = self.cache_dir / key[:2] / f"{key}.json"
        if cpath.exists():
            return json.loads(cpath.read_text())["text"]
        with self._lock:
            if self.calls >= self.cfg.max_calls:
                log.warning("LLM call budget (%d) exhausted; skipping", self.cfg.max_calls)
                return None
            self.calls += 1
        try:
            resp = self._client.chat.completions.create(model=model, messages=messages, temperature=0.1)
            text = (resp.choices[0].message.content or "").strip()
        except Exception as e:  # network, auth, unsupported modality...
            log.warning("LLM request failed (%s): %s", model, e)
            return None
        cpath.parent.mkdir(parents=True, exist_ok=True)
        cpath.write_text(json.dumps({"model": model, "text": text}))
        return text

    def summarize(self, instruction: str, content: str, inputs: tuple[str, ...] = ()) -> tuple[str, Derivation] | None:
        if not self.cfg.text_model:
            return None
        prompt = f"{instruction}\n\n---\n{content}"
        text = self._complete(self.cfg.text_model, [{"role": "user", "content": prompt}], prompt)
        if not text:
            return None
        return text, Derivation(method="llm", model=self.cfg.text_model,
                                prompt_sha256=sha256_text(prompt), inputs=inputs)

    def describe_image(self, instruction: str, image: bytes, mime: str,
                       inputs: tuple[str, ...] = ()) -> tuple[str, Derivation] | None:
        if not self.cfg.vision_model:
            return None
        url = f"data:{mime};base64,{base64.b64encode(image).decode()}"
        messages = [{"role": "user", "content": [
            {"type": "text", "text": instruction},
            {"type": "image_url", "image_url": {"url": url}},
        ]}]
        text = self._complete(self.cfg.vision_model, messages, instruction + sha256_bytes(image))
        if not text:
            return None
        return text, Derivation(method="llm", model=self.cfg.vision_model,
                                prompt_sha256=sha256_text(instruction + sha256_bytes(image)), inputs=inputs)
