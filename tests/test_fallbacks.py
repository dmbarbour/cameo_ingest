"""Fallback models (plan FM): each kind's models in order, the first asked first; stored answers
looked for along the list; an answer a caller can't use goes to the next model."""

from __future__ import annotations

import json

import pytest
from fixture_model import make_mdzip
from helpers import FakeChat, cli

from cameo_ingest.config import parse_setting
from cameo_ingest.llm import EnrichmentSession, LLMConfig
from cameo_ingest.prompts import Slot, Template

PLAIN = Template("plain", 1, "a test", "{{X}}", ())
PICTURE = Template("picture", 1, "a test", "{{X}}", (Slot("IMG", "image", "a picture"),))


class Chat:
    """Answers "<model> on <item>"; `fails` maps a model to the items it times out on, or to "*"."""

    replays = False

    def __init__(self, fails=None, answers=None):
        self.fails = fails or {}
        self.answers = answers or {}
        self.asked: list[tuple[str, str]] = []

    def complete(self, model, messages, temperature):
        content = messages[0]["content"]
        item = content if isinstance(content, str) else next(p["text"] for p in content if p["type"] == "text")
        self.asked.append((model, item))
        if self.fails.get(model) in ("*", item) or item in self.fails.get(model, ()):
            raise TimeoutError("no word for 120 s")
        return self.answers.get(model, f"{model} on {item}")


def session(tmp_path, chat, text="a, b", vision=None, **kw):
    cfg = LLMConfig.from_env(text, vision, **kw)
    return EnrichmentSession(cfg, tmp_path / "store", chat)


def test_a_hold_out_is_answered_by_the_next_model_and_kept(tmp_path):
    chat = Chat({"a": {"hold-out"}})
    llm = session(tmp_path, chat)
    assert llm.ask(PLAIN, {"X": "easy"}, inputs=("easy",))[0] == "a on easy"
    text, d = llm.ask(PLAIN, {"X": "hold-out"}, inputs=("hold-out",))
    assert (text, d.model) == ("b on hold-out", "b")  # the provenance names the model that answered
    assert llm.outcomes == {"answered": 2, "fallback": 1} and llm.incomplete == []  # not a gap
    again = Chat({"a": {"hold-out"}})
    llm = session(tmp_path, again)  # a later build: the store is searched along the list first
    assert llm.ask(PLAIN, {"X": "hold-out"}, inputs=("hold-out",))[0] == "b on hold-out"
    assert again.asked == [] and llm.outcomes == {"cached": 1, "fallback": 1}  # a isn't asked again


def test_every_model_failing_leaves_a_gap_that_names_each(tmp_path):
    llm = session(tmp_path, Chat({"a": "*", "b": "*"}))
    assert llm.ask(PLAIN, {"X": "hard"}, inputs=("hard",)) is None
    assert llm.incomplete == [{"item": "hard", "outcome": "failed",
                               "detail": "a: TimeoutError: no word for 120 s; b: TimeoutError: no word for 120 s"}]
    llm = session(tmp_path, Chat({"a": "*"}), max_calls=1)  # the budget stops the list too
    assert llm.ask(PLAIN, {"X": "late"}, inputs=("late",)) is None and llm.incomplete[0]["outcome"] == "failed"
    assert llm.calls == 1


def test_an_answer_the_caller_cant_use_goes_to_the_next_model(tmp_path):
    def is_json(text):
        return text.startswith("{")

    chat = Chat(answers={"a": "Sure! Here you go.", "b": '{"ways": []}'})
    llm = session(tmp_path, chat)
    assert llm.ask(PLAIN, {"X": "ways"}, accept=is_json)[1].model == "b"
    chat = Chat(answers={"a": "Sure!", "b": "Of course."})
    llm = session(tmp_path / "2", chat)
    text, d = llm.ask(PLAIN, {"X": "ways"}, accept=is_json)  # none usable: the first, for the caller to judge
    assert (text, d.model) == ("Sure!", "a") and len(chat.asked) == 2
    chat = Chat(answers={"a": "Sure!", "b": "Of course."})
    llm = session(tmp_path / "2", chat)
    assert llm.ask(PLAIN, {"X": "ways"}, accept=is_json)[0] == "Sure!" and chat.asked == []  # both stored


def test_each_vision_model_gets_its_own_image_order(tmp_path):
    chat = Chat({"v": "*"})
    llm = session(tmp_path, chat, text="t", vision="v, w")
    llm.image_first = {"v": True, "w": False}
    seen = []
    real = chat.complete
    chat.complete = lambda m, msgs, temperature: seen.append([p["type"] for p in msgs[0]["content"]]) or real(m, msgs, 0)
    assert llm.ask(PICTURE, {"X": "a sketch"}, image=b"png")[1].model == "w"
    assert seen == [["image_url", "text"], ["text", "image_url"]]


def test_the_settings_take_lists():
    assert parse_setting("text-model", " a ,b") == "a, b"
    for bad in ("a,,b", "a, a", ","):
        with pytest.raises(ValueError, match="each once"):
            parse_setting("vision-model", bad)
    cfg = LLMConfig.from_env("a, b", None)
    assert cfg.text_models == cfg.vision_models == ("a", "b") and cfg.vision_fallbacks == ("b",)
    cfg = LLMConfig.from_env("a, b", "v")
    assert cfg.vision_models == ("v",) and cfg.text_fallbacks == ("b",)


def test_a_run_with_a_fallback(tmp_path, fake_chat, monkeypatch):
    """The images the first vision model can't read are described by the second; the provenance
    says so; the options name the fallbacks, so a change of list builds again; `config test` and
    the run's first check cover every model."""
    real = FakeChat.complete

    def complete(self, model, messages, temperature):
        if model == "m" and isinstance(messages[0]["content"], list) and "OK" not in json.dumps(messages):
            self.requests.append((model, messages))
            raise TimeoutError("no word for 120 s")
        return real(self, model, messages, temperature)

    monkeypatch.setattr(FakeChat, "complete", complete)
    src = tmp_path / "drone.mdzip"
    src.write_bytes(make_mdzip())
    out = tmp_path / "out"
    assert cli([str(src), "-o", str(out), "--text-model", "m, n", "--no-calibrate"]) == 0
    run = json.loads((out / "run.json").read_text())
    assert run["llm"]["outcomes"].get("fallback", 0) >= 2 and not run["llm"]["incomplete"]
    assert run["options"]["text_fallbacks"] == ["n"] and run["options"]["vision_fallbacks"] == [["n", True]]
    preflight = {m for m, msgs in fake_chat[0].requests if "Reply with the single word OK." in json.dumps(msgs)}
    assert preflight == {"m", "n"}
    assert run["llm"]["disabled_after_failures"] == ["m (vision)"]  # m still writes the summary
    written = "\n".join(p.read_text(encoding="utf-8", errors="ignore") for p in out.rglob("*.json*") if p.is_file())
    assert '"model": "n"' in written and '"model": "m"' in written
