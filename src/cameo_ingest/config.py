"""A tree's settings and a project's options, typed, with their defaults in one place (AR-013).

- **Tree settings** are remembered by `state.sqlite` and applied to the whole tree on every run:
  the LLM endpoint's models and limits, and what the root files hold (`rag/`, the index across
  models, threads, line references). A run's flags override them, and are remembered in turn.
- **Project options** decide what a project's own files hold. They are hashed into the
  project's identity, so that a project made with other options is made again (FU-014).
"""

from __future__ import annotations

import json
from dataclasses import dataclass, fields, replace
from typing import Any

from .prompts import PART_CHARS
from .provenance import sha256_text

# The sketches' uncalibrated defaults: gemma-4's figures at DeepInfra, for now (the maintainer's
# decision, 2026-10-03; docs/research/gemma4-images-2026-09-30.md and
# vision-calibration-gemma4-2026-10-03.md). A run calibrates them to the configured vision model
# (plan VA); the tree's own settings win, then the calibration, then these.
#
# The pixel budget: gemma-4 fills 280 soft tokens of 48 x 48 px (645,120 px) at the image's own
# aspect ratio, sides in multiples of 48. Diagram sketches are drawn to it, and larger images
# scaled to it.
IMAGE_PIXELS = 280 * 48 * 48
# Diagrams with more shapes than the first are split into modules of the second to the third
# (plan DV).
MODULES = (25, 6, 25)
# Sketches' font size, arrowhead legs and line width, in pixels.
SKETCH = (13, 10.0, 1)
# The tree settings a model's calibration sets, unless the tree sets them itself: the vision
# model's (plan VA), then the text model's (plan TC).
CALIBRATED = ("image_pixels", "diagram_modules", "sketch_font_px", "sketch_arrow_px", "sketch_line_px", "image_first",
              "part_chars")


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
    image_first: bool | None = None  # the image before the text in vision requests; None: as calibrated
    part_chars: int | None = None  # the largest LLM input of package text; None: as calibrated (plan TC)
    calibrate: bool = True  # calibrate to the vision model (plan VA) and the text model (plan TC)
    rag_files: bool = True
    rag_source: str = "trace"  # or "id"

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

    def calibrated(self, calibration: dict[str, Any] | None) -> TreeSettings:
        """These settings, with the models' calibrations (plans VA, TC) filling those the tree
        leaves unset: explicit settings win, then the calibration, then the defaults."""
        if not calibration:
            return self
        return replace(self, **{k: v for k, v in calibration.items() if k in CALIBRATED and getattr(self, k) is None})


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
    image_first: bool = True  # the image before the text in vision requests (plan VA)
    part_chars: int = PART_CHARS[1]  # a package's parts, and a package summarized at once (plan TC)

    @classmethod
    def of(cls, settings: TreeSettings, text_model: str | None, vision_model: str | None,
           max_calls: int | None, calibration: dict[str, Any] | None = None) -> ProjectOptions:
        """A run's options, from the tree's settings, the models the LLM configuration chose, and
        the models' calibrations."""
        from .prompts import CURRENT

        settings = settings.calibrated(calibration)
        enabled = bool(text_model or vision_model)
        return cls(settings.render, text_model, vision_model, max_calls, settings.image_pixels or IMAGE_PIXELS,
                   settings.modules, tuple(sorted(t.key for t in CURRENT.values())) if enabled else (),
                   settings.sketch, settings.image_first is not False, settings.part_chars or PART_CHARS[1])

    def as_dict(self) -> dict[str, Any]:
        """As run.json records them, and as they are hashed."""
        out = {"render": self.render, "text_model": self.text_model, "vision_model": self.vision_model,
               "max_calls": self.max_calls, "image_pixels": self.image_pixels, "modules": list(self.modules),
               "templates": list(self.templates), "sketch": list(self.sketch), "image_first": self.image_first,
               "part_chars": self.part_chars}
        return out

    def hash(self) -> str:
        """Of the options that change a project's output."""
        return sha256_text(json.dumps(self.as_dict(), sort_keys=True))[:16]


# -- What `cameo-ingest config` sets (plan CF-02) ---------------------------------------------------
@dataclass(frozen=True)
class Setting:
    """A tree setting a user sets with `config`: what a user can judge (ADR-0027). Every one can be
    set and unset, back to its default, and every switch turned either way."""

    key: str  # as `config` names it
    field: str  # the TreeSettings field that holds it
    kind: str  # "switch", "text", "count" or "choice"
    about: str
    default: str  # how `config show` names the default
    choices: tuple[str, ...] = ()
    inverse: bool = False  # a switch held as its opposite (`llm on` is `no_llm` False)


SETTINGS = (
    Setting("llm", "no_llm", "switch", "use the LLM for summaries and descriptions", "on", inverse=True),
    Setting("text-model", "text_model", "text", "the model for package summaries, at $OPENAI_BASE_URL", "none"),
    Setting("vision-model", "vision_model", "text", "the model for diagram and image descriptions", "the text model"),
    Setting("render", "render", "switch", "draw diagram sketches, which the vision model reads", "on"),
    Setting("rag-files", "rag_files", "switch", "write rag/: a file per chunk, for RAG tools that read files", "on"),
    Setting("rag-source", "rag_source", "choice", "how a rag/ file names its source", "trace", ("trace", "id")),
    Setting("concurrency", "llm_concurrency", "count", "LLM requests at once", "1"),
    Setting("max-calls", "llm_max_calls", "count", "LLM requests per run, at most", "no limit"),
)
BY_KEY = {s.key: s for s in SETTINGS}
_ON, _OFF = ("on", "true", "yes", "1"), ("off", "false", "no", "0")


def parse_setting(key: str, text: str) -> Any:
    """The stored value of `config set KEY TEXT`; ValueError, saying what is allowed, otherwise."""
    s = BY_KEY.get(key)
    if s is None:
        raise ValueError(f"no setting {key!r}; the settings are {', '.join(BY_KEY)}")
    t = text.strip()
    if s.kind == "switch":
        if t.lower() not in _ON + _OFF:
            raise ValueError(f"{key} is on or off, not {text!r}")
        return (t.lower() in _ON) != s.inverse
    if s.kind == "choice":
        if t not in s.choices:
            raise ValueError(f"{key} is one of {', '.join(s.choices)}, not {text!r}")
        return t
    if s.kind == "count":
        if not t.isdigit() or int(t) < 1:
            raise ValueError(f"{key} is a whole number of 1 or more, not {text!r}")
        return int(t)
    if not t:
        raise ValueError(f"{key} needs a value; `config unset {key}` returns it to its default")
    return t


def shown(key: str, stored: dict[str, Any]) -> tuple[str, bool]:
    """A setting's value as `config show` writes it, and whether it is the tree's own (not the default)."""
    s = BY_KEY[key]
    if stored.get(s.field) is None:
        return s.default, False
    v = stored[s.field]
    if s.kind == "switch":
        return ("on" if bool(v) != s.inverse else "off"), True
    return str(v), True
