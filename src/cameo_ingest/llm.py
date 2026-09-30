"""Optional LLM enrichment through any OpenAI-compatible endpoint (e.g. a local gemma).

Configuration (environment; the CLI flags of the same meaning take precedence):
    OPENAI_API_KEY, OPENAI_BASE_URL   standard OpenAI client settings
    CAMEO_INGEST_TEXT_MODEL           model for summaries, falling back to OPENAI_MODEL
    CAMEO_INGEST_VISION_MODEL         model for image descriptions (default: text model)
    CAMEO_INGEST_LLM_TIMEOUT          seconds per request (default 120)
    CAMEO_INGEST_LLM_RETRIES          retries per request (default 2)
    CAMEO_INGEST_LLM_MAX_CALLS        optional cap on requests per run (default: none)

Responses are kept in an SQLite store (`llm.sqlite`), keyed by endpoint, model and a hash
of the request, so re-runs are cheap and reproducible. The same file serves as a replay
fixture: in replay mode, requests are answered only from a recorded store, matching on
model and request hash, and a request with no recorded answer is an error. Failures are
logged and skipped, so enrichment never breaks ingestion; after a few consecutive
failures, enrichment is switched off for the rest of the run.
"""

from __future__ import annotations

import base64
import io
import json
import logging
import os
import sqlite3
import threading
import time
from collections import Counter
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .provenance import Derivation, sha256_text, utc_now

log = logging.getLogger(__name__)

PREFLIGHT_PROMPT = "Reply with the single word OK."
MAX_CONSECUTIVE_FAILURES = 3  # then enrichment is switched off for the run (BASE-006)
STORE_FILE = "llm.sqlite"


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


class ReplayMiss(Exception):
    """Replay mode met a request that the recorded store has no answer for."""


def request_key(messages: list[dict]) -> str:
    """Hash of a request: the prompt text and any image (inline as a data URL)."""
    return sha256_text(json.dumps(messages, sort_keys=True, ensure_ascii=False))


class LLMStore:
    """SQLite store of LLM responses. It holds request hashes, never prompt text, so a
    store recorded on third-party models can be committed as a test fixture."""

    SCHEMA = """
        CREATE TABLE IF NOT EXISTS responses (
            endpoint TEXT NOT NULL,        -- OPENAI_BASE_URL, or '' for the client default
            model TEXT NOT NULL,
            request_sha256 TEXT NOT NULL,  -- see request_key()
            text TEXT NOT NULL,
            created TEXT NOT NULL,
            PRIMARY KEY (endpoint, model, request_sha256)
        );
        CREATE INDEX IF NOT EXISTS responses_by_request ON responses (model, request_sha256);
    """

    def __init__(self, path: Path, readonly: bool = False):
        self.path = path
        self._lock = threading.Lock()  # one connection, shared by the request threads
        if readonly:
            if not path.is_file():
                raise FileNotFoundError(f"LLM replay store {path} not found")
            self._db = sqlite3.connect(f"file:{path}?mode=ro", uri=True, check_same_thread=False)
            return
        path.parent.mkdir(parents=True, exist_ok=True)
        try:
            self._db = self._open(path)
        except sqlite3.DatabaseError as e:  # not a database, or damaged (BASE-005)
            aside = path.with_name(f"{path.name}.corrupt-{int(time.time())}")
            path.replace(aside)
            log.warning("LLM store %s is unreadable (%s); moved it to %s and started a new one", path, e, aside)
            self._db = self._open(path)

    @classmethod
    def _open(cls, path: Path) -> sqlite3.Connection:
        db = sqlite3.connect(path, timeout=30, check_same_thread=False)
        try:
            db.executescript(cls.SCHEMA)
        except sqlite3.DatabaseError:
            db.close()
            raise
        return db

    def get(self, endpoint: str | None, model: str, key: str) -> str | None:
        """The recorded answer; with endpoint None, from any endpoint (replay)."""
        with self._lock:
            if endpoint is None:
                row = self._db.execute("SELECT text FROM responses WHERE model = ? AND request_sha256 = ? LIMIT 1",
                                       (model, key)).fetchone()
            else:
                row = self._db.execute(
                    "SELECT text FROM responses WHERE endpoint = ? AND model = ? AND request_sha256 = ?",
                    (endpoint, model, key)).fetchone()
        return row[0] if row else None

    def put(self, endpoint: str, model: str, key: str, text: str) -> None:
        with self._lock, self._db:  # one transaction per response: a killed run never leaves half an entry
            self._db.execute("INSERT OR REPLACE INTO responses VALUES (?, ?, ?, ?, ?)",
                             (endpoint, model, key, text, utc_now()))


class LLM:
    def __init__(self, cfg: LLMConfig, cache_dir: Path, replay: Path | None = None):
        self.cfg = cfg
        self.cache_dir = cache_dir
        self.calls = 0  # requests sent to the endpoint
        self.outcomes: Counter[str] = Counter()
        self.incomplete: list[dict[str, str]] = []  # items left without generated text, and why
        self.disabled = False
        self._failures = 0  # consecutive
        self._budget_warned = False
        self._lock = threading.Lock()
        self._store: LLMStore | None = None
        self._replay = LLMStore(replay, readonly=True) if replay else None
        self._client = None
        if cfg.enabled and replay is None:
            from openai import OpenAI

            # The client reads OPENAI_API_KEY itself; local servers often need no key.
            self._client = OpenAI(
                base_url=cfg.base_url,
                api_key=os.environ.get("OPENAI_API_KEY") or "unused",
                timeout=cfg.timeout,
                max_retries=cfg.retries,
            )

    @property
    def store(self) -> LLMStore:
        with self._lock:
            if self._store is None:  # opened on first use, so runs without an LLM create nothing
                self._store = LLMStore(self.cache_dir / STORE_FILE)
        return self._store

    def preflight(self) -> str | None:
        """Send one tiny request per configured model, bypassing the store and the budget,
        so that a wrong endpoint, key or model name stops the run before any parsing
        (BASE-020). Returns an error message, or None when every model answered."""
        if self._replay is not None:
            return None
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

    def report(self) -> dict[str, Any]:
        """What enrichment did in this run, for run.json."""
        return {"calls": self.calls, "outcomes": dict(sorted(self.outcomes.items())),
                "disabled_after_failures": self.disabled, "incomplete": self.incomplete}

    def truncated(self, item: str, what: str) -> None:
        """Note that an item's input was cut short to fit the prompt (BASE-019)."""
        with self._lock:
            self.outcomes["truncated_input"] += 1
        log.debug("LLM input for %s truncated: %s", item, what)

    def _skip(self, item: str, outcome: str, detail: str = "") -> None:
        """Record an item left without generated text. Call with the lock held."""
        self.outcomes[outcome] += 1
        self.incomplete.append({"item": item, "outcome": outcome, **({"detail": detail} if detail else {})})

    def _complete(self, model: str, messages: list[dict], item: str) -> tuple[str, str] | None:
        """(text, request hash), or None when the item gets no generated text."""
        key = request_key(messages)
        if self._replay is not None:
            text = self._replay.get(None, model, key)
            if text is None:
                raise ReplayMiss(f"no recorded {model} response for {item} (request {key[:16]})")
            with self._lock:
                self.outcomes["replayed"] += 1
            return text, key
        endpoint = self.cfg.base_url or ""
        try:
            text = self.store.get(endpoint, model, key)
        except sqlite3.DatabaseError as e:  # treat as a miss (BASE-005)
            log.warning("LLM store lookup failed (%s); asking the model", e)
            text = None
        if text is not None:
            with self._lock:
                self.outcomes["cached"] += 1
            return text, key
        with self._lock:
            if self.disabled:
                self._skip(item, "skipped_disabled")
                return None
            if self.cfg.max_calls is not None and self.calls >= self.cfg.max_calls:
                if not self._budget_warned:
                    log.warning("LLM call budget (%d) reached; remaining items get no generated text",
                                self.cfg.max_calls)
                    self._budget_warned = True
                self._skip(item, "skipped_budget")
                return None
            self.calls += 1
        started = time.monotonic()
        try:
            resp = self._client.chat.completions.create(model=model, messages=messages, temperature=0.1)
            text = (resp.choices[0].message.content or "").strip()
        except Exception as e:  # network, auth, unsupported modality...
            log.warning("LLM request failed (%s, %s): %s", model, item, e)
            with self._lock:
                self._skip(item, "failed", f"{type(e).__name__}: {e}")
                self._failures += 1
                if self._failures >= MAX_CONSECUTIVE_FAILURES and not self.disabled:
                    self.disabled = True
                    log.error("LLM enrichment switched off for the rest of this run after %d consecutive "
                              "failures; the last was: %s", self._failures, e)
            return None
        log.debug("LLM %s answered for %s in %.1f s", model, item, time.monotonic() - started)
        with self._lock:
            self._failures = 0
            if not text:
                self._skip(item, "empty")  # not stored, so a re-run asks again
                return None
            self.outcomes["answered"] += 1
        self.store.put(endpoint, model, key, text)
        return text, key

    def summarize(self, instruction: str, content: str, inputs: tuple[str, ...] = ()) -> tuple[str, Derivation] | None:
        if not self.cfg.text_model:
            return None
        prompt = f"{instruction}\n\n---\n{content}"
        res = self._complete(self.cfg.text_model, [{"role": "user", "content": prompt}], inputs[0] if inputs else "")
        if res is None:
            return None
        text, key = res
        return text, Derivation(method="llm", model=self.cfg.text_model, prompt_sha256=key, inputs=inputs)

    def describe_image(self, instruction: str, image: bytes, mime: str,
                       inputs: tuple[str, ...] = ()) -> tuple[str, Derivation] | None:
        if not self.cfg.vision_model:
            return None
        url = f"data:{mime};base64,{base64.b64encode(image).decode()}"
        messages = [{"role": "user", "content": [
            {"type": "text", "text": instruction},
            {"type": "image_url", "image_url": {"url": url}},
        ]}]
        res = self._complete(self.cfg.vision_model, messages, inputs[0] if inputs else "")
        if res is None:
            return None
        text, key = res
        return text, Derivation(method="llm", model=self.cfg.vision_model, prompt_sha256=key, inputs=inputs)
