"""Provenance records attached to every emitted file, row and chunk.

A trace answers "where did this text come from?" down to the model element:

    source file (path + sha256 + caller metadata)
      -> container chain (e.g. outer.rdzip!inner.mdzip)
        -> archive entry (e.g. com.nomagic.magicdraw.uml_model.model)
          -> xmi:id + line number
            -> derivation (deterministic extraction, or LLM model + prompt hash)

`Trace.locator()` flattens this into one string suitable for a CSV column.
"""

from __future__ import annotations

import datetime as _dt
import hashlib
import uuid
from dataclasses import asdict, dataclass, field
from typing import Any

from . import __version__

TOOL = f"cameo-ingest/{__version__}"


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def sha256_text(text: str) -> str:
    return sha256_bytes(text.encode("utf-8"))


def utc_now() -> str:
    return _dt.datetime.now(_dt.UTC).isoformat(timespec="seconds")


@dataclass(frozen=True)
class SourceInfo:
    """The top-level file handed to the CLI."""

    path: str
    sha256: str
    size: int
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class Derivation:
    method: str = "extracted"  # "extracted" | "rendered" | "llm"
    tool: str = TOOL
    model: str | None = None
    prompt_sha256: str | None = None
    inputs: tuple[str, ...] = ()  # locators of the inputs an LLM saw


EXTRACTED = Derivation()


@dataclass(frozen=True)
class Trace:
    source_sha256: str
    container: tuple[str, ...] = ()  # archive members, outermost first
    entry: str | None = None  # member inside the innermost archive
    xmi_id: str | None = None
    line: int | None = None
    qualified_name: str | None = None
    derivation: Derivation = EXTRACTED

    def locator(self) -> str:
        loc = f"sha256:{self.source_sha256[:16]}"
        for part in self.container:
            loc += f"!{part}"
        if self.entry:
            loc += f"!{self.entry}"
        if self.xmi_id:
            loc += f"#{self.xmi_id}"
        if self.line:
            loc += f"@L{self.line}"
        return loc

    def with_(self, **kw: Any) -> Trace:
        d = {**self.__dict__, **kw}
        return Trace(**d)

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        d["container"] = list(self.container)
        d["derivation"]["inputs"] = list(self.derivation.inputs)
        d["locator"] = self.locator()
        return {k: v for k, v in d.items() if v not in (None, [], ())}


@dataclass
class RunInfo:
    source: SourceInfo
    run_id: str = field(default_factory=lambda: uuid.uuid4().hex)
    started: str = field(default_factory=utc_now)
    tool: str = TOOL
    llm: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)
