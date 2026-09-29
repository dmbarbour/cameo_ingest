"""Optional LLM enrichment through any OpenAI-compatible endpoint (e.g. a local gemma).

Configuration (environment; the CLI flags of the same meaning take precedence):
    OPENAI_API_KEY, OPENAI_BASE_URL   standard OpenAI client settings
    CAMEO_INGEST_TEXT_MODEL           model for summaries, falling back to OPENAI_MODEL
    CAMEO_INGEST_VISION_MODEL         model for image descriptions (default: text model)
    CAMEO_INGEST_LLM_TIMEOUT          seconds per request (default 120)
    CAMEO_INGEST_LLM_RETRIES          retries per request (default 2)
    CAMEO_INGEST_LLM_MAX_CALLS        optional cap on requests per run (default: none)

Responses are cached on disk keyed by (model, prompt, image hash) so re-runs are cheap
and reproducible. Failures are logged and skipped: enrichment never breaks ingestion.
"""

from __future__ import annotations

import base64
import io
import json
import logging
import os
import threading
from dataclasses import dataclass
from pathlib import Path

from .provenance import Derivation, sha256_bytes, sha256_text

log = logging.getLogger(__name__)

PREFLIGHT_PROMPT = "Reply with the single word OK."


@dataclass
class LLMConfig:
    text_model: str | None
    vision_model: str | None
    base_url: str | None
    timeout: float = 120.0
    retries: int = 2
    max_calls: int | None = None  # no budget unless one is asked for (BASE-019)

    @classmethod
    def from_env(cls, text_model: str | None = None, vision_model: str | None = None, *,
                 timeout: float | None = None, retries: int | None = None,
                 max_calls: int | None = None) -> LLMConfig:
        env = os.environ.get
        tm = text_model or env("CAMEO_INGEST_TEXT_MODEL") or env("OPENAI_MODEL") or None
        vm = vision_model or env("CAMEO_INGEST_VISION_MODEL") or tm
        mc = max_calls if max_calls is not None else env("CAMEO_INGEST_LLM_MAX_CALLS") or None
        return cls(
            text_model=tm,
            vision_model=vm,
            base_url=env("OPENAI_BASE_URL"),
            timeout=float(timeout if timeout is not None else env("CAMEO_INGEST_LLM_TIMEOUT", "120")),
            retries=int(retries if retries is not None else env("CAMEO_INGEST_LLM_RETRIES", "2")),
            max_calls=int(mc) if mc is not None else None,
        )

    @property
    def enabled(self) -> bool:
        return bool(self.text_model or self.vision_model)

    def public(self) -> dict:
        # Never record the API key.
        return {"text_model": self.text_model, "vision_model": self.vision_model, "base_url": self.base_url,
                "max_calls": self.max_calls}


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
                max_retries=cfg.retries,
            )

    def preflight(self) -> str | None:
        """Send one tiny request per configured model, bypassing the cache and the budget,
        so that a wrong endpoint, key or model name stops the run before any parsing
        (BASE-020). Returns an error message, or None when every model answered."""
        checks = []
        if self.cfg.vision_model:
            png = io.BytesIO()
            from PIL import Image

            Image.new("RGB", (32, 32), "white").save(png, "PNG")
            url = f"data:image/png;base64,{base64.b64encode(png.getvalue()).decode()}"
            checks.append((self.cfg.vision_model, [{"role": "user", "content": [
                {"type": "text", "text": PREFLIGHT_PROMPT}, {"type": "image_url", "image_url": {"url": url}}]}]))
        if self.cfg.text_model and self.cfg.text_model != self.cfg.vision_model:
            checks.append((self.cfg.text_model, [{"role": "user", "content": PREFLIGHT_PROMPT}]))
        for model, messages in checks:
            try:
                self._client.chat.completions.create(model=model, messages=messages, temperature=0)
            except Exception as e:  # anything: the point is to report it before parsing
                return f"{model}: {type(e).__name__}: {e}"
        return None

    def _complete(self, model: str, messages: list[dict], key_material: str) -> str | None:
        key = sha256_text(json.dumps([model, key_material]))
        cpath = self.cache_dir / key[:2] / f"{key}.json"
        if cpath.exists():
            return json.loads(cpath.read_text())["text"]
        with self._lock:
            if self.cfg.max_calls is not None and self.calls >= self.cfg.max_calls:
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
