"""`config`: show, set or unset the tree's settings, export and import them as JSON, test the
endpoint, list its models (plan CF; RN-005)."""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

from .. import session
from ..config import BY_KEY, SETTINGS, exported, imported, parse_setting, shown, stored_settings, tree_settings
from ..state import State
from .common import open_tree


def configure(out: Path, args: argparse.Namespace) -> int:
    """`cameo-ingest config`: show, set or unset the tree's settings (plan CF-02). Setting one
    starts a tree, so that a tree can be configured before its first input."""
    action = args.action or "show"
    if action in ("test", "models"):
        return check_config(out, action, getattr(args, "filter", None))
    if action == "export":
        text = json.dumps(exported(stored_settings(out)), indent=1, ensure_ascii=False) + "\n"
        if args.file is None:
            sys.stdout.write(text)
        else:
            args.file.write_text(text, encoding="utf-8")
            print(f"wrote the settings of {out} to {args.file}")
        return 0
    if action == "import":
        return import_settings(out, args.file)
    if action == "show":
        stored = stored_settings(out)
        print(f"settings of {out}" + ("" if State.exists(out) else " (no tree yet: the defaults)"))
        width = max(len(s.key) for s in SETTINGS)
        for s in SETTINGS:
            value, own = shown(s.key, stored)
            print(f"  {s.key:<{width}}  {value:<18} {'' if own else '(default)':<10} {s.about}")
        print("endpoint: $OPENAI_BASE_URL " + ("set" if os.environ.get("OPENAI_BASE_URL") else "not set (OpenAI)")
              + "; key: $OPENAI_API_KEY " + ("set" if os.environ.get("OPENAI_API_KEY") else "not set"))
        return 0
    try:
        value = parse_setting(args.key, args.value) if action == "set" else None
    except ValueError as e:
        print(f"error: {e}", file=sys.stderr)
        return 2
    if action == "unset" and args.key not in BY_KEY:
        print(f"error: no setting {args.key!r}; the settings are {', '.join(BY_KEY)}", file=sys.stderr)
        return 2
    with open_tree(out, lock=True) as state:
        stored = state.settings()
        field = BY_KEY[args.key].field
        if action == "set":
            stored[field] = value
        else:
            stored.pop(field, None)
        state.save_settings(tree_settings(stored).stored())  # retired settings go, with a notice
        print(f"{args.key} = {shown(args.key, state.settings())[0]}")
    return 0


def import_settings(out: Path, file: Path) -> int:
    """`config import FILE` (RN-005): every setting in the file, or none when any is wrong."""
    try:
        text = sys.stdin.read() if str(file) == "-" else file.read_text(encoding="utf-8")
        changes = imported(json.loads(text))
    except (OSError, ValueError) as e:  # json's errors are ValueErrors
        print(f"error: {file}: {e}; nothing was changed", file=sys.stderr)
        return 2
    with open_tree(out, lock=True) as state:
        stored = state.settings()
        for field, value in changes.items():
            if value is None:
                stored.pop(field, None)
            else:
                stored[field] = value
        state.save_settings(tree_settings(stored).stored())
        now = state.settings()
    for s in SETTINGS:
        if s.field in changes:
            print(f"{s.key} = {shown(s.key, now)[0]}")
    return 0


def check_config(out: Path, action: str, text: str | None) -> int:
    """`config test` and `config models` (plan CF-03), on the tree's models at $OPENAI_BASE_URL."""
    from .. import checks

    settings = tree_settings(stored_settings(out), quiet=True)
    cfg = session.llm_config(settings)
    endpoint = cfg.base_url or "https://api.openai.com/v1 (OpenAI; $OPENAI_BASE_URL not set)"
    print(f"endpoint: {endpoint}; key: $OPENAI_API_KEY " + ("set" if os.environ.get("OPENAI_API_KEY") else "not set"))
    client = session.make_client(cfg)
    if action == "models":
        try:
            models = client.models()
        except Exception as e:  # what the endpoint says
            print(f"error: the endpoint lists no models: {type(e).__name__}: {e}", file=sys.stderr)
            return 5
        calibrated = set()
        if State.exists(out):
            with open_tree(out) as st:
                calibrated = {r["model"] for r in st.calibrations()}
        for model, created in models:
            if text and text.lower() not in model.lower():
                continue
            marks = [m for m, on in (("text model", model == cfg.text_model), ("vision model", model == cfg.vision_model),
                                     ("calibrated", model in calibrated)) if on]
            print(f"  {model}" + (f"  [{', '.join(marks)}]" if marks else ""))
        return 0
    if not cfg.enabled:
        print("error: no model is set: `cameo-ingest config set text-model NAME` (and vision-model, if another "
              "model reads images), or `config set llm off`", file=sys.stderr)
        return 2
    failed = False
    session.note_models(out, client, cfg)
    for c in checks.run_checks(client, cfg):
        print(f"  {'ok  ' if c.ok else 'FAIL'} {c.name}: {c.detail} ({c.seconds:.1f} s)")
        failed |= not c.ok and not c.name.startswith("the endpoint lists")
    if failed:
        print("A check failed: see OPENAI_BASE_URL, OPENAI_API_KEY, and `config set text-model` or `vision-model`.",
              file=sys.stderr)
    return 5 if failed else 0

