"""Streamed requests (RN-002, RN-004): the timeout is the longest wait for the next words, a
time limit cuts a long answer, and a reply cut short says what it held."""

from __future__ import annotations

import time
from types import SimpleNamespace

import httpx
import openai
import pytest

from cameo_ingest.llm import LLMConfig, OpenAIChat, Partial


def chunk(text: str = "", finish: str | None = None) -> SimpleNamespace:
    return SimpleNamespace(choices=[SimpleNamespace(delta=SimpleNamespace(content=text), finish_reason=finish)])


class Stream:
    """A stream of chunks, each after `pause` seconds; `then` raised after them, if any."""

    def __init__(self, chunks, pause=0.0, then=None):
        self.chunks, self.pause, self.then = chunks, pause, then
        self.closed = False

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.closed = True

    def __iter__(self):
        for c in self.chunks:
            time.sleep(self.pause)
            yield c
        if self.then is not None:
            raise self.then


def timeout() -> openai.APITimeoutError:
    return openai.APITimeoutError(request=httpx.Request("POST", "https://example.invalid/v1/chat/completions"))


def client(streams, time_limit=600.0, retries=2) -> tuple[OpenAIChat, list[dict]]:
    """A client whose endpoint answers with `streams`, one per request; the requests kept."""
    chat = OpenAIChat(LLMConfig(None, "m", "https://example.invalid/v1", retries=retries, time_limit=time_limit))
    asked: list[dict] = []
    queue = list(streams)

    def create(**kw):
        asked.append(kw)
        return queue.pop(0)
    chat._client = SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=create)))
    return chat, asked


def test_a_slow_steady_answer_is_whole():
    chat, asked = client([Stream([chunk("A drone "), chunk("has a battery."), chunk("", "stop")], pause=0.01)])
    assert chat.complete("m", [{"role": "user", "content": "?"}], 0.1) == "A drone has a battery."
    assert asked[0]["stream"] is True


def test_no_word_before_a_timeout_is_asked_again():
    chat, asked = client([Stream([], then=timeout()), Stream([chunk("Fine."), chunk("", "stop")])])
    assert chat.complete("m", [], 0.1) == "Fine." and len(asked) == 2
    chat, asked = client([Stream([], then=timeout())] * 3)
    with pytest.raises(openai.APITimeoutError):
        chat.complete("m", [], 0.1)
    assert len(asked) == 3  # the first, and RETRIES more


def test_a_reply_cut_short_says_what_it_held():
    chat, asked = client([Stream([chunk("One. "), chunk("Two")], then=timeout())])
    with pytest.raises(Partial) as e:
        chat.complete("m", [], 0.1)
    assert (e.value.text, e.value.cause) == ("One. Two", "broken") and "broke off" in e.value.why
    assert len(asked) == 1  # what was said isn't thrown away by asking again

    stream = Stream([chunk(f"Sentence {i}. ") for i in range(100)], pause=0.01)
    chat, _ = client([stream], time_limit=0.1)
    with pytest.raises(Partial) as e:
        chat.complete("m", [], 0.1)
    assert e.value.cause == "time" and "time limit (0.1 s)" in e.value.why and stream.closed
    assert e.value.text.startswith("Sentence 0. Sentence 1.") and "Sentence 99" not in e.value.text

    chat, _ = client([Stream([chunk("Long and "), chunk("longer", "length")])])
    with pytest.raises(Partial) as e:
        chat.complete("m", [], 0.1)
    assert e.value.cause == "output" and "output limit" in e.value.why


class Cutting:
    """An endpoint whose every reply is cut short, as `cause` says, after two and a half sentences."""

    replays = False

    def __init__(self, cause: str):
        self.cause, self.requests = cause, 0

    def complete(self, model, messages, temperature):
        self.requests += 1
        raise Partial("A drone. It flies. It has a batt", f"cut ({self.cause})", self.cause)

    def close(self):
        pass


def session(tmp_path, client, time_limit=600.0):
    from cameo_ingest.llm import EnrichmentSession

    return EnrichmentSession(LLMConfig("m", None, "https://example.invalid/v1", time_limit=time_limit),
                             tmp_path / "store", client)


def template(partial: bool):
    from cameo_ingest.prompts import Template

    return Template(id="t", version=1, purpose="a test", text="Describe the drone.", slots=(), partial=partial)


def test_a_reply_cut_by_the_time_limit_is_kept_to_its_sentences(tmp_path):
    """Kept as the model's answer in the time allowed, its derivation saying so; asked again only
    under a longer time limit (RN-002)."""
    client = Cutting("time")
    llm = session(tmp_path, client)
    text, d = llm.ask(template(True), {})
    assert text == "A drone. It flies." and d.partial == "cut (time)"
    assert llm.outcomes["partial"] == 1 and llm.incomplete[0]["outcome"] == "partial"
    assert session(tmp_path, client).ask(template(True), {}) == (text, d) and client.requests == 1
    assert session(tmp_path, client, time_limit=900).ask(template(True), {})[0] == text and client.requests == 2
    # A template whose answer is JSON gets nothing from a reply cut short.
    assert session(tmp_path, Cutting("time")).ask(template(False), {}) is None


def test_a_broken_reply_serves_once(tmp_path):
    """Used for this run, never kept: the next run asks again (RN-002)."""
    client = Cutting("broken")
    llm = session(tmp_path, client)
    assert llm.ask(template(True), {})[0] == "A drone. It flies." and llm.outcomes["broken_off"] == 1
    session(tmp_path, client).ask(template(True), {})
    assert client.requests == 2


def test_the_settings_reach_the_client():
    """`config set timeout` and `time-limit` (RN-004)."""
    from cameo_ingest.config import TreeSettings
    from cameo_ingest.session import llm_config

    cfg = llm_config(TreeSettings(text_model="m", request_timeout=30, request_time_limit=1200))
    assert (cfg.timeout, cfg.time_limit) == (30, 1200)
    cfg = llm_config(TreeSettings(text_model="m"))
    assert (cfg.timeout, cfg.time_limit) == (120, 600)
