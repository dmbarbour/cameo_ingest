"""`cameo-ingest config -i` (plan CF-06): the tree's configuration, asked for in order and tested
before anything is saved. The endpoint and key are checked (they are the environment's, never
stored); the LLM is turned on or off; the models are offered from the endpoint's list and each is
tested; then the switches, a summary of the changes, and calibration, if wanted, once saved."""

from __future__ import annotations

import argparse
import os
from pathlib import Path
from typing import Any

from .config import BY_KEY, SETTINGS, parse_setting, shown

LISTED = 12  # models shown at once
SAME = "same"  # the vision model's answer for "the text model"


class Ended(Exception):
    """The input ended (EOF): nothing is saved."""


def ask(prompt: str, default: str = "") -> str:
    try:
        reply = input(f"{prompt}" + (f" [{default}]" if default else "") + ": ").strip()
    except EOFError:
        raise Ended from None
    return reply or default


def yes(prompt: str, default: bool) -> bool:
    while True:
        reply = ask(f"{prompt} ({'Y/n' if default else 'y/N'})").lower()
        if not reply:
            return default
        if reply in ("y", "yes", "n", "no"):
            return reply.startswith("y")
        print("  y or n")


def choose_model(what: str, models: list[str] | None, current: str | None, vision: bool = False) -> str | None:
    """A model id, typed in full, picked by number from the last list shown, or found by typing part
    of it. For the vision model, `same` (None) is the text model."""
    shortlist: list[str] = []
    if models:
        print(f"  the endpoint lists {len(models)} models: type part of a name to list those that hold it")
    else:
        print("  the endpoint lists no models: type the model's id")
    default = current or (SAME if vision else "")
    while True:
        reply = ask(f"{what}" + (f" (or {SAME}, the text model)" if vision else ""), default)
        if vision and reply.lower() == SAME:
            return None
        if reply.isdigit() and 1 <= int(reply) <= len(shortlist):
            return shortlist[int(reply) - 1]
        if not reply:
            continue
        if not models or reply in models:
            return reply
        shortlist = [m for m in models if reply.lower() in m.lower()]
        if not shortlist:
            if yes(f"  no listed model holds {reply!r}; use {reply!r} anyway", False):
                return reply
            continue
        for i, m in enumerate(shortlist[:LISTED], 1):
            print(f"  {i:>3}. {m}")
        if len(shortlist) > LISTED:
            print(f"       and {len(shortlist) - LISTED} more: type more of the name")
        shortlist = shortlist[:LISTED]
        if len(shortlist) == 1:
            default = shortlist[0]


def interview(out: Path) -> int:
    """Ask for the tree's settings, test them, show the changes, save them if wanted, and offer
    calibration. 0 when finished (saved or not), 130 when the input ends or is interrupted."""
    from . import calibrate, checks, cli, textcal
    from .config import TreeSettings
    from .state import State

    old = cli.tree_settings(cli.stored_settings(out)).stored()  # retired settings noticed, and dropped on saving
    new: dict[str, Any] = dict(old)

    def value(key: str) -> Any:
        return new.get(BY_KEY[key].field)

    def put(key: str, v: Any) -> None:
        """Set (None: unset) a setting, unless that changes nothing shown: a default stays unstored."""
        trial = {k: x for k, x in new.items() if k != BY_KEY[key].field}
        if v is not None:
            trial[BY_KEY[key].field] = v
        trial = TreeSettings.from_stored(trial).stored()
        if shown(key, trial)[0] != shown(key, new)[0]:
            new.clear()
            new.update(trial)

    try:
        print(f"Configuring {out}" + ("" if State.exists(out) else " (a new tree)") + ". Nothing is saved until "
              "the end; Enter keeps the value in [brackets].\n")
        base_url, key = os.environ.get("OPENAI_BASE_URL"), os.environ.get("OPENAI_API_KEY")
        print(f"The endpoint: {base_url or 'OpenAI (OPENAI_BASE_URL is not set)'}; its key: OPENAI_API_KEY "
              + ("is set" if key else "is NOT set"))
        cfg = cli.llm_config(cli.tree_settings(new, quiet=True))
        client = cli.make_client(cfg)
        models: list[str] | None
        try:
            models = [m for m, _ in client.models()]
            print(f"  the endpoint answers, and lists {len(models)} models")
        except Exception as e:  # what the endpoint says
            models = None
            print(f"  the endpoint lists no models: {type(e).__name__}: {e}")
        if not key or models is None:
            print("  to use another endpoint or key, export OPENAI_BASE_URL and OPENAI_API_KEY, and run "
                  "`cameo-ingest config -i` again")
        print()
        llm_on = yes("Use the LLM for package summaries and diagram descriptions",
                     not new.get("no_llm") and (bool(key) or models is not None))
        put("llm", not llm_on)
        while llm_on:
            print("\nThe text model writes package summaries.")
            put("text-model", choose_model("text model", models, value("text-model")))
            print("\nThe vision model describes diagrams and images; the text model does, unless another is named.")
            put("vision-model", choose_model("vision model", models, value("vision-model"), vision=True))
            cfg = cli.llm_config(cli.tree_settings(new, quiet=True))
            print("\nTesting the models:")
            results = checks.run_checks(cli.make_client(cfg), cfg)
            for c in results:
                print(f"  {'ok  ' if c.ok else 'FAIL'} {c.name}: {c.detail} ({c.seconds:.1f} s)")
            if all(c.ok for c in results[1:]) or not yes("A model failed its check. Choose the models again", True):
                break
        print()
        put("render", yes("Draw diagram sketches, for people and the vision model", value("render") is not False))
        put("rag-files", yes("Write rag/, a file per chunk, for RAG tools that read files", value("rag-files") is not False))
        if llm_on:
            print("LLM requests sent at once: 1 suits a local server; hosted endpoints usually take 4 to 8.")
            while True:
                try:
                    put("concurrency", parse_setting("concurrency", ask("concurrency", str(value("concurrency") or 1))))
                    break
                except ValueError as e:
                    print(f"  {e}")
        print("(Also: `config set rag-source id` for short source ids in rag/, `config set max-calls N` for a "
              "budget per run.)")

        changes = [(s.key, shown(s.key, old)[0], shown(s.key, new)[0]) for s in SETTINGS
                   if shown(s.key, old)[0] != shown(s.key, new)[0]]
        print("\nThe changes:" if changes else "\nNo changes.")
        for k, was, now in changes:
            print(f"  {k}: {was} -> {now}")
        if changes and not yes(f"Save them to {out}", True):
            print("Nothing saved.")
            return 0
        if changes or old != cli.stored_settings(out):  # retired settings go too
            state = State(out)
            try:
                state.lock()
                state.save_settings(new)
            finally:
                state.close()
            print("Saved. `cameo-ingest config show` shows them, and `config set` changes one.")
        if not llm_on:
            return 0

        cfg = cli.llm_config(cli.tree_settings(cli.stored_settings(out), quiet=True))
        cli.note_models(out, client, cfg)
        state = State(out)
        try:
            vision = cfg.vision_model if new.get("render") is not False and not calibrate.recorded(state, cfg) else None
            text = cfg.text_model if not textcal.recorded(state, cfg.base_url or "", cfg.text_model or "") else None
        finally:
            state.close()
        if not (vision or text):
            return 0
        print("\nThe first run calibrates to the models, if this tree has no calibration for them:")
        if vision:
            print(f"  the sketches, to {vision}: about 100 requests, a few minutes on a hosted model")
        if text:
            print(f"  the part size, to {text}: 30 requests")
        print("  Answers are kept in the LLM store, shared by every tree, so a model calibrated before costs "
              "no requests.")
        if not yes("Calibrate now", False):
            return 0
        dev = argparse.Namespace(llm_replay=None, no_preflight=True, heartbeat=30.0, suite="standard")
        code = 0
        if vision:
            code = cli.calibrate_vision(out, dev) or code
        if text:
            code = cli.calibrate_text(out, dev) or code
        return code
    except (Ended, KeyboardInterrupt):
        print("\nNothing more saved.")
        return 130
