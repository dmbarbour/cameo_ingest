"""Optional LLM enrichment through any OpenAI-compatible endpoint (e.g. a local gemma).

Configuration: the endpoint and its key from the OpenAI clients' own variables, OPENAI_BASE_URL
and OPENAI_API_KEY; the models and the call budget from the tree's settings (`cameo-ingest
config`, plan CF). Timeout and retries are fixed (`TIMEOUT`, `RETRIES`).

Three pieces (AR-016R1): a `ChatClient` answers a request, from an endpoint (`OpenAIChat`) or
from a recorded store (`ReplayChat`); a `ResponseStore` keeps answers and what each request
asked; an `EnrichmentSession` holds a run's policy (the store, a budget, a breaker, the outcomes)
and builds requests from templates (`ask`).

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
from typing import Any, Protocol

from .prompts import Template
from .provenance import Derivation, sha256_bytes, sha256_text, utc_now
from .sqlite_cache import SqliteCache

log = logging.getLogger(__name__)

PREFLIGHT_PROMPT = "Reply with the single word OK."
MAX_CONSECUTIVE_FAILURES = 3  # then enrichment is switched off for the run (BASE-006)
STORE_FILE = "llm.sqlite"


TIMEOUT = 120.0  # seconds per request
RETRIES = 2  # retries per request, by the OpenAI client


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
                 max_calls: int | None = None) -> LLMConfig:
        """The tree's models (the vision model defaults to the text model) at $OPENAI_BASE_URL."""
        return cls(text_model=text_model or None, vision_model=vision_model or text_model or None,
                   base_url=os.environ.get("OPENAI_BASE_URL"), timeout=TIMEOUT, retries=RETRIES, max_calls=max_calls)

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


class ResponseStore(SqliteCache):
    """SQLite store of LLM responses. It holds request hashes, never prompt text, so a
    store recorded on third-party models can be committed as a test fixture."""

    WHAT = "LLM store"
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
        -- What each request asked, for quality review (plan LQ-02). Local only: it holds model
        -- content, so scripts/record_llm_fixture.py drops it from the committed fixture.
        CREATE TABLE IF NOT EXISTS requests (
            model TEXT NOT NULL,
            request_sha256 TEXT NOT NULL,
            template TEXT NOT NULL,            -- e.g. diagram-description@v1 (see prompts.py)
            project TEXT NOT NULL,             -- content token of the project, sha256:<hex>
            item TEXT NOT NULL,                -- locator of what the request is about
            slots TEXT NOT NULL,               -- JSON: the text of each text slot
            prompt TEXT NOT NULL,              -- the rendered request text
            image_sha256 TEXT, image_path TEXT,  -- the attached image; path relative to the project
            notes TEXT NOT NULL DEFAULT '{}',  -- JSON, e.g. what was cut to fit
            seen TEXT NOT NULL,
            PRIMARY KEY (model, request_sha256)
        );
    """

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

    def log_request(self, model: str, key: str, template: str, project: str, item: str, slots: dict[str, str],
                    prompt: str, image_sha256: str | None, image_path: str | None, notes: dict[str, Any]) -> None:
        with self._lock, self._db:
            self._db.execute("INSERT OR REPLACE INTO requests VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                             (model, key, template, project, item, json.dumps(slots, ensure_ascii=False), prompt,
                              image_sha256, image_path, json.dumps(notes, ensure_ascii=False), utc_now()))

    def request(self, model: str, key: str) -> dict[str, Any] | None:
        """What a request asked, from the request log."""
        with self._lock:
            cur = self._db.execute("SELECT * FROM requests WHERE model = ? AND request_sha256 = ?", (model, key))
            row = cur.fetchone()
            return dict(zip([c[0] for c in cur.description], row, strict=True)) if row else None

    def put(self, endpoint: str, model: str, key: str, text: str) -> None:
        with self._lock, self._db:  # one transaction per response: a killed run never leaves half an entry
            self._db.execute("INSERT OR REPLACE INTO responses VALUES (?, ?, ?, ?, ?)",
                             (endpoint, model, key, text, utc_now()))


class ChatClient(Protocol):
    """Answers one chat request: the text of the reply, stripped."""

    replays: bool  # answers are a recording's: the session's store, budget and breaker don't apply

    def complete(self, model: str, messages: list[dict], temperature: float) -> str: ...

    def close(self) -> None: ...


class OpenAIChat:
    """Any OpenAI-compatible endpoint, through the OpenAI SDK, which retries."""

    replays = False

    def __init__(self, cfg: LLMConfig):
        from openai import OpenAI

        # The client reads OPENAI_API_KEY itself; local servers often need no key.
        self._client = OpenAI(base_url=cfg.base_url, api_key=os.environ.get("OPENAI_API_KEY") or "unused",
                              timeout=cfg.timeout, max_retries=cfg.retries)

    def complete(self, model: str, messages: list[dict], temperature: float) -> str:
        resp = self._client.chat.completions.create(model=model, messages=messages, temperature=temperature)
        return (resp.choices[0].message.content or "").strip()

    def models(self) -> list[tuple[str, int | None]]:
        """The endpoint's models (`GET /models`): each id, with its creation time when the endpoint
        gives one (plan CF-03). Endpoints give no version; the id and this time are all there is."""
        return sorted((m.id, getattr(m, "created", None)) for m in self._client.models.list())

    def close(self) -> None:
        """Close the connection pool, so that requests still in flight fail at once."""
        self._client.close()


class ReplayChat:
    """Answers only from a recorded store, matching on model and request hash."""

    replays = True

    def __init__(self, path: Path):
        self.store = ResponseStore(path, readonly=True)

    def complete(self, model: str, messages: list[dict], temperature: float) -> str:
        text = self.store.get(None, model, request_key(messages))
        if text is None:
            raise ReplayMiss(f"no recorded {model} response")
        return text

    def close(self) -> None:
        pass


def connect(cfg: LLMConfig, replay: Path | None = None) -> ChatClient | None:
    """A run's client: a recorded store's with `replay`, else the endpoint's; None when no
    model is configured."""
    if replay is not None:
        return ReplayChat(replay)
    return OpenAIChat(cfg) if cfg.enabled else None


class EnrichmentSession:
    """A run's requests: answers kept in the store, a budget of calls, a breaker that switches
    enrichment off after consecutive failures, and a record of the outcomes."""

    def __init__(self, cfg: LLMConfig, cache_dir: Path, client: ChatClient | None,
                 max_failures: int | None = MAX_CONSECUTIVE_FAILURES):
        self.cfg = cfg
        self.client = client
        self.max_failures = max_failures  # consecutive failures before switching off; None never does
        self.cache_dir = cache_dir
        self.calls = 0  # requests sent to the endpoint
        self.outcomes: Counter[str] = Counter()
        self.incomplete: list[dict[str, str]] = []  # items left without generated text, and why
        self.disabled = False
        self._failures = 0  # consecutive
        self._budget_warned = False
        self._lock = threading.Lock()
        self._store: ResponseStore | None = None
        self.image_first: bool | None = None  # the vision model's order (plan VA); None: each template's

    def close(self) -> None:
        """Stop requests in flight (used when a run is interrupted)."""
        if self.client is not None:
            self.client.close()

    @property
    def store(self) -> ResponseStore:
        with self._lock:
            if self._store is None:  # opened on first use, so runs without an LLM create nothing
                self._store = ResponseStore(self.cache_dir / STORE_FILE)
        return self._store

    def preflight(self) -> str | None:
        """Send one tiny request per configured model, bypassing the store and the budget,
        so that a wrong endpoint, key or model name stops the run before any parsing
        (BASE-020). Returns an error message, or None when every model answered."""
        if self.client is None or self.client.replays:
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
                self.client.complete(model, messages, temperature=0)
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

    def skip(self, item: str, outcome: str, detail: str = "") -> None:
        """Record that an item was deliberately left without generated text."""
        with self._lock:
            self._skip(item, outcome, detail)

    def _skip(self, item: str, outcome: str, detail: str = "") -> None:
        """Record an item left without generated text. Call with the lock held."""
        self.outcomes[outcome] += 1
        self.incomplete.append({"item": item, "outcome": outcome, **({"detail": detail} if detail else {})})

    def _complete(self, model: str, messages: list[dict], item: str) -> tuple[str, str] | None:
        """(text, request hash), or None when the item gets no generated text."""
        key = request_key(messages)
        assert self.client is not None, "a session with a model needs a client"
        if self.client.replays:
            try:
                text = self.client.complete(model, messages, temperature=0.1)
            except ReplayMiss as e:
                raise ReplayMiss(f"{e} for {item} (request {key[:16]})") from None
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
            text = self.client.complete(model, messages, temperature=0.1)
        except Exception as e:  # network, auth, unsupported modality...
            log.warning("LLM request failed (%s, %s): %s", model, item, e)
            with self._lock:
                self._skip(item, "failed", f"{type(e).__name__}: {e}")
                self._failures += 1
                if self.max_failures is not None and self._failures >= self.max_failures and not self.disabled:
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
        try:  # the answer is paid for: a store that can't keep it costs a re-ask later, not this project (AR-016)
            self.store.put(endpoint, model, key, text)
        except sqlite3.DatabaseError as e:
            log.warning("cannot store LLM response: %s", e)
        return text, key

    def ask(self, template: Template, values: dict[str, str], *, image: bytes | None = None,
            mime: str = "image/png", image_path: str | None = None, project: str = "",
            inputs: tuple[str, ...] = (), notes: dict[str, Any] | None = None,
            image_first: bool | None = None) -> tuple[str, Derivation] | None:
        """Send one request built from `template`; `inputs` are the locators of what it is
        about (the first one names the item). Returns the answer with its derivation, or
        None when the item gets no generated text."""
        model = self.cfg.vision_model if template.image_slot else self.cfg.text_model
        if not model:
            return None
        text = template.render(values)
        if template.image_slot is None:
            messages: list[dict] = [{"role": "user", "content": text}]
        else:
            assert image is not None, f"{template.key} needs an image"
            url = f"data:{mime};base64,{base64.b64encode(image).decode()}"
            parts = [{"type": "text", "text": text}, {"type": "image_url", "image_url": {"url": url}}]
            first = next(x for x in (image_first, self.image_first, template.image_first) if x is not None)
            if first:  # by default, as Google advises for gemma (FU-015); calibrated per model (plan VA)
                parts.reverse()
            messages = [{"role": "user", "content": parts}]
        key = request_key(messages)
        item = inputs[0] if inputs else ""
        try:  # the log serves quality review; a failure to write it must not cost the answer
            self.store.log_request(model, key, template.key, project, item, values, text,
                                   sha256_bytes(image) if image is not None else None, image_path, notes or {})
        except sqlite3.DatabaseError as e:
            log.warning("cannot log LLM request: %s", e)
        res = self._complete(model, messages, item)
        if res is None:
            return None
        answer, key = res
        return answer, Derivation(method="llm", model=model, prompt_sha256=key, template=template.key, inputs=inputs)
