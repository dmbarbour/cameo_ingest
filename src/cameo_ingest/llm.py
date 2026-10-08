"""Optional LLM enrichment through any OpenAI-compatible endpoint (e.g. a local gemma).

Configuration: the endpoint and its key from the OpenAI clients' own variables, OPENAI_BASE_URL
and OPENAI_API_KEY; the models, the call budget, the timeout and the time limit from the tree's
settings (`cameo-ingest config`, plan CF; RN-004). Retries are fixed (`RETRIES`).

Requests are streamed (RN-002), so that the timeout is the longest wait for the next words, not
for the whole answer: an answer that takes minutes to write, word by word, doesn't time out. A
reply cut short, by the time limit, the model's output limit or a broken connection, raises
`Partial` with what was said; the session decides whether it serves.

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
from .text import whole_sentences

log = logging.getLogger(__name__)

PREFLIGHT_PROMPT = "Reply with the single word OK."
MAX_CONSECUTIVE_FAILURES = 3  # then enrichment is switched off for the run (BASE-006)
STORE_FILE = "llm.sqlite"


TIMEOUT = 120  # seconds without a word, the first included (RN-004)
TIME_LIMIT = 600  # seconds per request in all; then what was said is all there is (RN-002)
RETRIES = 2  # retries per request: by the OpenAI client before the answer starts, by us while no word came


@dataclass
class LLMConfig:
    text_model: str | None
    vision_model: str | None
    base_url: str | None
    timeout: float = TIMEOUT
    retries: int = RETRIES
    max_calls: int | None = None  # no budget unless one is asked for (BASE-019)
    time_limit: float = TIME_LIMIT

    @classmethod
    def from_env(cls, text_model: str | None = None, vision_model: str | None = None, *,
                 max_calls: int | None = None, timeout: float | None = None,
                 time_limit: float | None = None) -> LLMConfig:
        """The tree's models (the vision model defaults to the text model) at $OPENAI_BASE_URL."""
        return cls(text_model=text_model or None, vision_model=vision_model or text_model or None,
                   base_url=os.environ.get("OPENAI_BASE_URL"), timeout=timeout or TIMEOUT, retries=RETRIES,
                   max_calls=max_calls, time_limit=time_limit or TIME_LIMIT)

    @property
    def enabled(self) -> bool:
        return bool(self.text_model or self.vision_model)


class ReplayMiss(Exception):
    """Replay mode met a request that the recorded store has no answer for."""


class Partial(Exception):
    """A reply cut short (RN-002): `text`, what the model had said; `why`; `cause`: "time" (the
    time limit) or "output" (the model's output limit), which would cut it again if asked again,
    or "broken" (the connection), which might not."""

    def __init__(self, text: str, why: str, cause: str):
        super().__init__(f"{why}, after {len(text):,} characters")
        self.text, self.why, self.cause = text, why, cause


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
        -- Answers cut short by a limit (RN-002): why, and the time limit then (NULL: the model's own
        -- output limit). A later run with a longer time limit asks again.
        CREATE TABLE IF NOT EXISTS partial (
            endpoint TEXT NOT NULL,
            model TEXT NOT NULL,
            request_sha256 TEXT NOT NULL,
            why TEXT NOT NULL,
            time_limit REAL,
            PRIMARY KEY (endpoint, model, request_sha256)
        );
    """

    def adopt(self, old: Path) -> None:
        """Copy another store's answers and request log in, keeping ours where both have one: the
        columns both have, since an old store may lack some (plan CF-04)."""
        with self._lock:
            self._db.execute("ATTACH DATABASE ? AS old", (str(old),))
            try:
                for table in ("responses", "requests", "partial"):
                    main_cols = [r[1] for r in self._db.execute(f"PRAGMA main.table_info({table})")]
                    old_cols = {r[1] for r in self._db.execute(f"PRAGMA old.table_info({table})")}
                    cols = ", ".join(c for c in main_cols if c in old_cols)
                    if cols:
                        self._db.execute(f"INSERT OR IGNORE INTO main.{table} ({cols}) SELECT {cols} FROM old.{table}")
                self._db.commit()
            finally:
                self._db.execute("DETACH DATABASE old")

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

    def cut(self, endpoint: str, model: str, key: str) -> tuple[str, float | None] | None:
        """Why a stored answer was cut short, and the time limit then; None for a whole one."""
        with self._lock:
            row = self._db.execute("SELECT why, time_limit FROM partial WHERE endpoint = ? AND model = ? AND "
                                   "request_sha256 = ?", (endpoint, model, key)).fetchone()
        return (row[0], row[1]) if row else None

    def put(self, endpoint: str, model: str, key: str, text: str,
            cut: tuple[str, float | None] | None = None) -> None:
        """Keep an answer; `cut`, (why, the time limit) when it was cut short by a limit."""
        with self._lock, self._db:  # one transaction per response: a killed run never leaves half an entry
            self._db.execute("INSERT OR REPLACE INTO responses VALUES (?, ?, ?, ?, ?)",
                             (endpoint, model, key, text, utc_now()))
            self._db.execute("DELETE FROM partial WHERE endpoint = ? AND model = ? AND request_sha256 = ?",
                             (endpoint, model, key))
            if cut is not None:
                self._db.execute("INSERT INTO partial VALUES (?, ?, ?, ?, ?)", (endpoint, model, key, *cut))


class ChatClient(Protocol):
    """Answers one chat request: the text of the reply, stripped."""

    replays: bool  # answers are a recording's: the session's store, budget and breaker don't apply

    def complete(self, model: str, messages: list[dict], temperature: float) -> str: ...

    def close(self) -> None: ...


class OpenAIChat:
    """Any OpenAI-compatible endpoint, through the OpenAI SDK, streamed (RN-002). The SDK retries
    until the answer starts; a timeout before its first word is retried here."""

    replays = False

    def __init__(self, cfg: LLMConfig):
        from openai import OpenAI

        # The client reads OPENAI_API_KEY itself; local servers often need no key. Its timeout is
        # httpx's, per wait: streamed, the longest wait for the next words.
        self._client = OpenAI(base_url=cfg.base_url, api_key=os.environ.get("OPENAI_API_KEY") or "unused",
                              timeout=cfg.timeout, max_retries=cfg.retries)
        self.retries, self.time_limit = cfg.retries, cfg.time_limit

    def complete(self, model: str, messages: list[dict], temperature: float) -> str:
        """The reply, whole; `Partial` when it was cut short."""
        import httpx
        import openai

        deadline = time.monotonic() + self.time_limit
        for attempt in range(self.retries + 1):
            words: list[str] = []
            finish = None
            stream = self._client.chat.completions.create(model=model, messages=messages, temperature=temperature,
                                                          stream=True)
            try:
                with stream:
                    for chunk in stream:
                        if chunk.choices:
                            words.append(chunk.choices[0].delta.content or "")
                            finish = chunk.choices[0].finish_reason or finish
                        if time.monotonic() > deadline:
                            raise Partial("".join(words).strip(), f"cut at the time limit ({self.time_limit:g} s)",
                                          "time")
            except (openai.APIConnectionError, httpx.TransportError) as e:  # a timeout among them
                said = "".join(words).strip()
                if said:
                    raise Partial(said, f"the answer broke off ({type(e).__name__})", "broken") from e
                if attempt == self.retries or time.monotonic() > deadline:
                    raise
                log.debug("%s gave no word before %s; asking again", model, type(e).__name__)
                continue
            text = "".join(words).strip()
            if finish == "length":
                raise Partial(text, "cut at the model's output limit", "output")
            return text
        raise AssertionError("unreachable")

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
        self.incomplete: list[dict[str, str]] = []  # items left without generated text, or cut short (RN-002), and why
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

    def _complete(self, model: str, messages: list[dict], item: str,
                  partial: bool = False) -> tuple[str, str, str | None] | None:
        """(text, request hash, why it was cut short or None), or None when the item gets no
        generated text. `partial`: a reply cut short serves, to its whole sentences (RN-002)."""
        key = request_key(messages)
        assert self.client is not None, "a session with a model needs a client"
        if self.client.replays:
            try:
                text = self.client.complete(model, messages, temperature=0.1)
            except ReplayMiss as e:
                raise ReplayMiss(f"{e} for {item} (request {key[:16]})") from None
            with self._lock:
                self.outcomes["replayed"] += 1
            return text, key, None
        endpoint = self.cfg.base_url or ""
        stored = self._stored(endpoint, model, key, partial)
        if stored is not None:
            with self._lock:
                self.outcomes["cached"] += 1
            return stored[0], key, stored[1]
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
        cut: Partial | None = None
        try:
            text = self.client.complete(model, messages, temperature=0.1)
        except Partial as e:
            text, cut = e.text, e
            if not (partial and whole_sentences(text)):
                self._failed(model, item, e)
                return None
        except Exception as e:  # network, auth, unsupported modality...
            self._failed(model, item, e)
            return None
        log.debug("LLM %s answered for %s in %.1f s%s", model, item, time.monotonic() - started,
                  f" ({cut.why})" if cut else "")
        with self._lock:
            self._failures = 0
            if not text:
                self._skip(item, "empty")  # not stored, so a re-run asks again
                return None
            if cut is None:
                self.outcomes["answered"] += 1
            else:  # what a limit cut is kept, as the model's answer in the time allowed; a broken one isn't
                self._skip(item, "partial" if cut.cause != "broken" else "broken_off", cut.why)
        if cut is None or cut.cause != "broken":
            try:  # the answer is paid for: a store that can't keep it costs a re-ask later, not this project (AR-016)
                self.store.put(endpoint, model, key, text, None if cut is None else
                               (cut.why, self.cfg.time_limit if cut.cause == "time" else None))
            except sqlite3.DatabaseError as e:
                log.warning("cannot store LLM response: %s", e)
        return (text, key, None) if cut is None else (whole_sentences(text), key, cut.why)

    def _stored(self, endpoint: str, model: str, key: str, partial: bool) -> tuple[str, str | None] | None:
        """A stored answer, and why it was cut short (None: it is whole); None to ask the model:
        nothing stored, or an answer cut at a shorter time limit than this run's (RN-002)."""
        try:
            text = self.store.get(endpoint, model, key)
            cut = self.store.cut(endpoint, model, key) if text is not None else None
        except sqlite3.DatabaseError as e:  # treat as a miss (BASE-005)
            log.warning("LLM store lookup failed (%s); asking the model", e)
            return None
        if text is None or cut is None:
            return None if text is None else (text, None)
        why, limit = cut
        if limit is not None and limit < self.cfg.time_limit:  # more time now: ask again
            return None
        kept = whole_sentences(text) if partial else ""
        return (kept, why) if kept else None

    def _failed(self, model: str, item: str, e: Exception) -> None:
        """A request that failed: noted, and counted towards switching enrichment off."""
        log.warning("LLM request failed (%s, %s): %s", model, item, e)
        with self._lock:
            self._skip(item, "failed", f"{type(e).__name__}: {e}")
            self._failures += 1
            if self.max_failures is not None and self._failures >= self.max_failures and not self.disabled:
                self.disabled = True
                log.error("LLM enrichment switched off for the rest of this run after %d consecutive "
                          "failures; the last was: %s", self._failures, e)

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
        res = self._complete(model, messages, item, template.partial)
        if res is None:
            return None
        answer, key, cut = res
        return answer, Derivation(method="llm", model=model, prompt_sha256=key, template=template.key, inputs=inputs,
                                  partial=cut)
