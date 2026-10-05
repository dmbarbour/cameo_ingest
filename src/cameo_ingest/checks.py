"""Checks of the LLM endpoint for `cameo-ingest config test` and `config models` (plan CF-03):
the endpoint answers and lists its models, the key is accepted, the text model answers, and the
vision model reads a drawn number. Each check says what failed, and what to set."""

from __future__ import annotations

import base64
import io
import time
from dataclasses import dataclass
from typing import Any

from .llm import LLMConfig

CARD_NUMBER = "731"  # drawn on the card the vision model is asked to read


@dataclass
class Check:
    name: str
    ok: bool
    detail: str
    seconds: float = 0.0


def card_png(text: str = CARD_NUMBER) -> bytes:
    """A small white card with `text` in large black type."""
    from PIL import Image, ImageDraw, ImageFont

    img = Image.new("RGB", (288, 144), "white")
    d = ImageDraw.Draw(img)
    d.text((144, 72), text, fill="black", font=ImageFont.load_default(size=72), anchor="mm")
    out = io.BytesIO()
    img.save(out, "PNG")
    return out.getvalue()


def _timed(name: str, fn) -> Check:
    t0 = time.perf_counter()
    try:
        ok, detail = fn()
    except Exception as e:  # anything the endpoint does: the point is to say what
        ok, detail = False, f"{type(e).__name__}: {e}"
    return Check(name, ok, detail, time.perf_counter() - t0)


def run_checks(client: Any, cfg: LLMConfig) -> list[Check]:
    """Every check for the configured models; listing the models is reported, never required."""

    def listing() -> tuple[bool, str]:
        models = client.models()
        return True, f"{len(models)} models listed"

    def text() -> tuple[bool, str]:
        reply = client.complete(cfg.text_model, [{"role": "user", "content": "Reply with the single word: ready"}], 0)
        return "ready" in reply.lower(), f"answered {reply[:60]!r}"

    def vision() -> tuple[bool, str]:
        url = f"data:image/png;base64,{base64.b64encode(card_png()).decode()}"
        reply = client.complete(cfg.vision_model, [{"role": "user", "content": [
            {"type": "text", "text": "What number is written in this image? Reply with the number only."},
            {"type": "image_url", "image_url": {"url": url}}]}], 0)
        ok = CARD_NUMBER in reply
        return ok, f"read {reply[:60]!r}" + ("" if ok else f", not {CARD_NUMBER}: it may not take images")

    out = [_timed("the endpoint lists its models", listing)]
    if cfg.text_model:
        out.append(_timed(f"the text model {cfg.text_model} answers", text))
    if cfg.vision_model:
        out.append(_timed(f"the vision model {cfg.vision_model} reads an image", vision))
    return out
