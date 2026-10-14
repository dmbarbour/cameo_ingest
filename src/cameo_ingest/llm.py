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
failures, a model is switched off for the rest of the run (more with requests in flight).
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
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Any, Protocol

from .prompts import Template
from .provenance import Derivation, sha256_bytes, sha256_text, utc_now
from .sqlite_cache import SqliteCache
from .text import whole_sentences

log = logging.getLogger(__name__)

PREFLIGHT_PROMPT = "Reply with the single word OK."
MAX_CONSECUTIVE_FAILURES = 3  # a model's, then it is off for the run (BASE-006); more with concurrency (FM-04)
STORE_FILE = "llm.sqlite"
# Outcomes that leave an item without the text a later run may get: its project is built again
# (RN-006). Not "partial": an answer cut by a limit is kept, as the model's in the time allowed.
GAPS = frozenset({"failed", "skipped_budget", "skipped_disabled", "empty", "broken_off"})


TIMEOUT = 120  # seconds without a word, the first included (RN-004)
TIME_LIMIT = 600  # seconds per request in all; then what was said is all there is (RN-002)
RETRIES = 2  # retries per request: by the OpenAI client before the answer starts, by us while no word came


def model_list(spec: str | None) -> tuple[str, ...]:
    """A setting's models, "A, B": the first, then its fallbacks in order (FM-05)."""
    return tuple(dict.fromkeys(m.strip() for m in (spec or "").split(",") if m.strip()))


@dataclass
class LLMConfig:
    text_model: str | None  # the first of each kind's list
    vision_model: str | None
    base_url: str | None
    timeout: float = TIMEOUT
    retries: int = RETRIES
    max_calls: int | None = None  # no budget unless one is asked for (BASE-019)
    time_limit: float = TIME_LIMIT
    concurrency: int = 1  # requests at once; those in flight together share a fate (FM-04)
    text_fallbacks: tuple[str, ...] = ()  # asked in turn when the first model gives no usable answer (FM-05)
    vision_fallbacks: tuple[str, ...] = ()

    @classmethod
    def from_env(cls, text_model: str | None = None, vision_model: str | None = None, *,
                 max_calls: int | None = None, timeout: float | None = None,
                 time_limit: float | None = None, concurrency: int | None = None) -> LLMConfig:
        """The tree's models at $OPENAI_BASE_URL: each kind's a list, "A, B", the first asked first
        (FM-05); the vision models default to the text models."""
        text = model_list(text_model)
        vision = model_list(vision_model) or text
        return cls(text_model=text[0] if text else None, vision_model=vision[0] if vision else None,
                   base_url=os.environ.get("OPENAI_BASE_URL"), timeout=timeout or TIMEOUT, retries=RETRIES,
                   max_calls=max_calls, time_limit=time_limit or TIME_LIMIT, concurrency=concurrency or 1,
                   text_fallbacks=text[1:], vision_fallbacks=vision[1:])

    @property
    def enabled(self) -> bool:
        return bool(self.text_model or self.vision_model)

    @property
    def text_models(self) -> tuple[str, ...]:
        """The text models, in the order they are asked; none without a first."""
        return (self.text_model, *self.text_fallbacks) if self.text_model else ()

    @property
    def vision_models(self) -> tuple[str, ...]:
        return (self.vision_model, *self.vision_fallbacks) if self.vision_model else ()


@dataclass(frozen=True)
class Miss:
    """A model that gave no answer to a request: `outcome` as `run.json` counts it, and what it
    said, for the item's record when no other model answers either (FM-06)."""

    outcome: str
    detail: str = ""


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
        # its transport's, per wait: streamed, the longest wait for the next words.
        self._client = OpenAI(base_url=cfg.base_url, api_key=os.environ.get("OPENAI_API_KEY") or "unused",
                              timeout=cfg.timeout, max_retries=cfg.retries)
        self.retries, self.time_limit = cfg.retries, cfg.time_limit

    def complete(self, model: str, messages: list[dict], temperature: float) -> str:
        """The reply, whole; `Partial` when it was cut short."""
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
            except openai.APIConnectionError as e:  # a timeout among them; the SDK wraps its transport's errors
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
    """A run's requests: answers kept in the store, a budget of calls, a breaker per model that
    switches it off after consecutive failures, and a record of the outcomes."""

    def __init__(self, cfg: LLMConfig, cache_dir: Path, client: ChatClient | None,
                 max_failures: int | None = MAX_CONSECUTIVE_FAILURES):
        self.cfg = cfg
        self.client = client
        self.max_failures = max_failures  # a model's consecutive failures before it is off; None never
        self.cache_dir = cache_dir
        self.calls = 0  # requests sent to the endpoint
        self.outcomes: Counter[str] = Counter()
        self.incomplete: list[dict[str, str]] = []  # items left without generated text, or cut short (RN-002), and why
        # Models switched off for the rest of the run, each for text or for images, as "m (text)":
        # one that fails on images may still read text (FM-04).
        self.off: set[str] = set()
        self._failures: Counter[str] = Counter()  # consecutive, likewise
        self._budget_warned = False
        self._lock = threading.Lock()
        self._store: ResponseStore | None = None
        self.image_first: dict[str, bool] = {}  # each vision model's calibrated order (plan VA, FM-06); else the template's

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
        if self.cfg.vision_models:
            png = io.BytesIO()
            from PIL import Image

            Image.new("RGB", (32, 32), "white").save(png, "PNG")
            url = f"data:image/png;base64,{base64.b64encode(png.getvalue()).decode()}"
            checks += [(m, [{"role": "user", "content": [{"type": "text", "text": PREFLIGHT_PROMPT},
                                                         {"type": "image_url", "image_url": {"url": url}}]}])
                       for m in self.cfg.vision_models]
        checks += [(m, [{"role": "user", "content": PREFLIGHT_PROMPT}])
                   for m in self.cfg.text_models if m not in self.cfg.vision_models]
        for model, messages in checks:
            try:
                self.client.complete(model, messages, temperature=0)
            except Exception as e:  # anything: the point is to report it before parsing
                return f"{model}: {type(e).__name__}: {e}"
        return None

    def report(self) -> dict[str, Any]:
        """What enrichment did in this run, for run.json."""
        return {"calls": self.calls, "outcomes": dict(sorted(self.outcomes.items())),
                "disabled_after_failures": sorted(self.off), "incomplete": self.incomplete}

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

    def _complete(self, model: str, messages: list[dict], item: str, partial: bool = False,
                  kind: str = "text") -> tuple[str, str, str | None] | Miss:
        """One model's answer: (text, request hash, why it was cut short or None); or a `Miss`,
        which the caller records once it knows whether another model answered (FM-06). The store
        is looked in first (`_stored`) by the caller. `partial`: a reply cut short serves, to its
        whole sentences (RN-002)."""
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
        line = f"{model} ({kind})"  # the breaker's count (FM-04)
        with self._lock:
            if line in self.off:
                return Miss("skipped_disabled")
            if self.cfg.max_calls is not None and self.calls >= self.cfg.max_calls:
                if not self._budget_warned:
                    log.warning("LLM call budget (%d) reached; remaining items get no generated text",
                                self.cfg.max_calls)
                    self._budget_warned = True
                return Miss("skipped_budget")
            self.calls += 1
        started = time.monotonic()
        cut: Partial | None = None
        try:
            text = self.client.complete(model, messages, temperature=0.1)
        except Partial as e:
            text, cut = e.text, e
            if not (partial and whole_sentences(text)):
                return self._failed(model, item, e, line)
        except Exception as e:  # network, auth, unsupported modality...
            return self._failed(model, item, e, line)
        log.debug("LLM %s answered for %s in %.1f s%s", model, item, time.monotonic() - started,
                  f" ({cut.why})" if cut else "")
        with self._lock:
            self._failures[line] = 0
            if not text:
                return Miss("empty", f"{model}: an empty answer")  # not stored, so a re-run asks again
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

    @property
    def breaker(self) -> int | None:
        """A model's consecutive failures that switch it off: `max_failures`, and one more for each
        other request in flight, since those fail together when the endpoint does (FM-04)."""
        return None if self.max_failures is None else self.max_failures + max(1, self.cfg.concurrency) - 1

    def _failed(self, model: str, item: str, e: Exception, line: str) -> Miss:
        """A request that failed: noted, and counted towards switching its model off, for its
        kind of request (`line`)."""
        log.warning("LLM request failed (%s, %s): %s", model, item, e)
        with self._lock:
            self._failures[line] += 1
            if self.breaker is not None and self._failures[line] >= self.breaker and line not in self.off:
                self.off.add(line)
                log.error("%s switched off for the rest of this run after %d consecutive failures; the last "
                          "was: %s", line, self._failures[line], e)
        return Miss("failed", f"{model}: {type(e).__name__}: {e}")

    def ask(self, template: Template, values: dict[str, str], *, image: bytes | None = None,
            mime: str = "image/png", image_path: str | None = None, project: str = "",
            inputs: tuple[str, ...] = (), notes: dict[str, Any] | None = None,
            image_first: bool | None = None,
            accept: Callable[[str], bool] | None = None) -> tuple[str, Derivation] | None:
        """Send one request built from `template`; `inputs` are the locators of what it is
        about (the first one names the item). Returns the answer with its derivation, or
        None when the item gets no generated text.

        The template's kind of model is a list (FM-06): the first model's stored answer, or the
        next's, serves; else each model is asked in turn, until one answers with something
        `accept` takes (a caller's check that it can use the answer, such as JSON it can read).
        When none does, the first answer there was is returned, for the caller to judge."""
        chain = self.cfg.vision_models if template.image_slot else self.cfg.text_models
        if not chain:
            return None
        assert self.client is not None, "a session with a model needs a client"
        if self.client.replays:
            chain = chain[:1]  # a recording answers as it was made
        text = template.render(values)
        item = inputs[0] if inputs else ""
        tries = [(m, self._messages(template, text, m, image, mime, image_first)) for m in chain]
        logged: set[str] = set()

        def log_request(model: str, messages: list[dict]) -> None:
            if model in logged:
                return
            logged.add(model)
            try:  # the log serves quality review; a failure to write it must not cost the answer
                self.store.log_request(model, request_key(messages), template.key, project, item, values, text,
                                       sha256_bytes(image) if image is not None else None, image_path, notes or {})
            except sqlite3.DatabaseError as e:
                log.warning("cannot log LLM request: %s", e)

        def answer(model: str, got: tuple[str, str, str | None]) -> tuple[str, Derivation]:
            if model != chain[0]:
                with self._lock:
                    self.outcomes["fallback"] += 1
                log.info("%s answered for %s, after %s", model, item, ", ".join(chain[:chain.index(model)]))
            return got[0], Derivation(method="llm", model=model, prompt_sha256=got[1], template=template.key,
                                      inputs=inputs, partial=got[2])

        first: tuple[str, tuple[str, str, str | None]] | None = None  # an answer refused by `accept`
        stored: set[str] = set()
        if not self.client.replays:
            for model, messages in tries:  # what a model said before is its answer (FM-D6)
                hit = self._stored(self.cfg.base_url or "", model, request_key(messages), template.partial)
                if hit is None:
                    continue
                stored.add(model)
                log_request(model, messages)
                with self._lock:
                    self.outcomes["cached"] += 1
                got = (hit[0], request_key(messages), hit[1])
                if accept is None or accept(got[0]):
                    return answer(model, got)
                first = first or (model, got)
        misses: list[Miss] = []
        for model, messages in tries:
            if model in stored:
                continue
            log_request(model, messages)
            res = self._complete(model, messages, item, template.partial,
                                 "vision" if template.image_slot else "text")
            if isinstance(res, Miss):
                misses.append(res)
                if res.outcome == "skipped_budget":
                    break
                continue
            if accept is None or accept(res[0]):
                return answer(model, res)
            log.warning("LLM answer from %s for %s can't be used%s", model, item,
                        "" if model == chain[-1] else "; asking the next model")
            first = first or (model, res)
        if first is not None:
            return answer(*first)
        with self._lock:
            kinds = [m.outcome for m in misses]
            outcome = next((k for k in ("failed", "empty", "skipped_budget") if k in kinds), "skipped_disabled")
            self._skip(item, outcome, "; ".join(m.detail for m in misses if m.detail))
        return None

    def _messages(self, template: Template, text: str, model: str, image: bytes | None, mime: str,
                  image_first: bool | None) -> list[dict]:
        """The request for `model`: the image's place is the call's, then the model's calibrated
        one, then the template's (plan VA; per model, FM-06)."""
        if template.image_slot is None:
            return [{"role": "user", "content": text}]
        assert image is not None, f"{template.key} needs an image"
        url = f"data:{mime};base64,{base64.b64encode(image).decode()}"
        parts = [{"type": "text", "text": text}, {"type": "image_url", "image_url": {"url": url}}]
        first = next(x for x in (image_first, self.image_first.get(model), template.image_first) if x is not None)
        if first:  # by default, as Google advises for gemma (FU-015); calibrated per model (plan VA)
            parts.reverse()
        return [{"role": "user", "content": parts}]

    @contextmanager
    def only(self, model: str, kind: str) -> Iterator[None]:
        """Requests of `kind` ("text" or "vision") go to `model` alone, and the other kind's to
        none, while the block runs: a calibration measures one model, never its fallbacks (FM-10)."""
        before = self.cfg
        if kind == "text":
            self.cfg = replace(before, text_model=model, text_fallbacks=(), vision_model=None, vision_fallbacks=())
        else:
            self.cfg = replace(before, vision_model=model, vision_fallbacks=(), text_model=None, text_fallbacks=())
        try:
            yield
        finally:
            self.cfg = before
