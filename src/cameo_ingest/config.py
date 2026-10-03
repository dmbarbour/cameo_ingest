"""A tree's settings and a project's options, typed, with their defaults in one place (AR-013).

- **Tree settings** are remembered by `state.sqlite` and applied to the whole tree on every run:
  the LLM endpoint's models and limits, and what the root files hold (`rag/`, the index across
  models, threads, line references). A run's flags override them, and are remembered in turn.
- **Project options** decide what a project's own files hold. They are hashed into the
  project's identity, so that a project made with other options is made again (FU-014).
"""

from __future__ import annotations

import json
from dataclasses import dataclass, fields
from typing import Any

from .provenance import sha256_text

# A vision model's pixel budget: gemma-4 fills 280 soft tokens of 48 x 48 px (645,120 px) at the
# image's own aspect ratio, sides in multiples of 48 (docs/research/gemma4-images-2026-09-30.md,
# FU-015). Diagram sketches are drawn to it, and larger images scaled to it.
IMAGE_PIXELS = 280 * 48 * 48
# Diagrams with more shapes than the first are split into modules of the second to the third
# (plan DV); --diagram-modules, for tuning: the defaults should serve.
MODULES = (25, 6, 25)
# Sketches' font size, arrowhead legs and line width, in pixels: found by hand for gemma-4 (FU-012),
# calibrated for another model by `calibrate-vision` (plan VC).
SKETCH = (12, 10.0, 1)


@dataclass(frozen=True)
class TreeSettings:
    env: str | None = None  # a dotenv file, named rather than read: never secrets
    text_model: str | None = None
    vision_model: str | None = None
    no_llm: bool = False
    llm_timeout: float | None = None
    llm_retries: int | None = None
    llm_max_calls: int | None = None
    llm_concurrency: int | None = None
    cache_dir: str | None = None
    render: bool = True
    image_pixels: int | None = None
    diagram_modules: str | None = None  # "N:MIN:MAX"
    sketch_font_px: int | None = None
    sketch_arrow_px: float | None = None
    sketch_line_px: int | None = None
    rag_files: bool = True
    rag_source: str = "trace"  # or "id"
    cross_index: bool = True
    threads: bool = True
    line_refs: bool = False

    @classmethod
    def from_stored(cls, stored: dict[str, Any]) -> TreeSettings:
        """The settings a tree remembers; any it no longer knows are left out."""
        known = {f.name for f in fields(cls)}
        return cls(**{k: v for k, v in stored.items() if k in known and v is not None})

    def stored(self) -> dict[str, Any]:
        """What the tree remembers: the settings that differ from the defaults, so that a tree
        follows a default that changes with the tool."""
        return {f.name: getattr(self, f.name) for f in fields(self) if getattr(self, f.name) != f.default}

    @property
    def modules(self) -> tuple[int, int, int]:
        return parse_modules(self.diagram_modules)

    @property
    def sketch(self) -> tuple[int, float, int]:
        font, arrow, line = SKETCH
        return (self.sketch_font_px or font, float(self.sketch_arrow_px or arrow), self.sketch_line_px or line)


def parse_modules(spec: str | None) -> tuple[int, int, int]:
    """The --diagram-modules setting, 'N:MIN:MAX', as numbers; empty for the defaults. N = 0
    never splits."""
    if not spec:
        return MODULES
    try:
        large, lo, hi = (int(x) for x in spec.split(":"))
    except ValueError:
        raise ValueError(f"--diagram-modules expects N:MIN:MAX, such as 25:6:25, not {spec!r}") from None
    if large < 0 or not 1 <= lo <= hi or hi < 2:
        raise ValueError(f"--diagram-modules {spec}: needs N >= 0 and 1 <= MIN <= MAX, MAX >= 2")
    return large, lo, hi


@dataclass(frozen=True)
class ProjectOptions:
    render: bool = True
    text_model: str | None = None
    vision_model: str | None = None
    max_calls: int | None = None
    image_pixels: int = IMAGE_PIXELS
    modules: tuple[int, int, int] = MODULES
    templates: tuple[str, ...] = ()  # the prompt templates' versions, when the LLM is on
    sketch: tuple[int, float, int] = SKETCH  # font, arrowhead legs and line width, in pixels

    @classmethod
    def of(cls, settings: TreeSettings, text_model: str | None, vision_model: str | None,
           max_calls: int | None) -> ProjectOptions:
        """A run's options, from the tree's settings and the models the LLM configuration chose."""
        from .prompts import CURRENT

        enabled = bool(text_model or vision_model)
        return cls(settings.render, text_model, vision_model, max_calls, settings.image_pixels or IMAGE_PIXELS,
                   settings.modules, tuple(sorted(t.key for t in CURRENT.values())) if enabled else (),
                   settings.sketch)

    def as_dict(self) -> dict[str, Any]:
        """As run.json records them, and as they are hashed."""
        out = {"render": self.render, "text_model": self.text_model, "vision_model": self.vision_model,
               "max_calls": self.max_calls, "image_pixels": self.image_pixels, "modules": list(self.modules),
               "templates": list(self.templates)}
        if tuple(self.sketch) != SKETCH:  # only when calibrated: so that today's hashes stand (plan VC)
            out["sketch"] = list(self.sketch)
        return out

    def hash(self) -> str:
        """Of the options that change a project's output: the same as before options were typed,
        so that no project is made again for it."""
        return sha256_text(json.dumps(self.as_dict(), sort_keys=True))[:16]
