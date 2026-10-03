"""Locate Cameo projects inside the input file, whatever the wrapping.

Detection goes by content, not by file extension: a zip that contains an XMI model
entry is a project; a zip without one (e.g. a .rdzip bundle) is searched for nested
zips; a bare XML file with an XMI root (e.g. .mdxml / .xmi) is a single-entry project.
Everything is read in memory, so malicious member paths cannot escape to disk. Size
limits guard against zip bombs.
"""

from __future__ import annotations

import hashlib
import io
import logging
import re
import zipfile
import zlib
from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import PurePosixPath

log = logging.getLogger(__name__)

ZIP_MAGIC = b"PK\x03\x04"
MAX_NESTING = 4
# Zip-bomb guards, set far above anything a valid model needs (the largest sample input
# decompresses to 138 MB, and its highest member ratio is 54:1).
MAX_TOTAL_BYTES = 10 * 10**9  # decompressed bytes per input, nested archives included
MAX_RATIO = 1000  # uncompressed / compressed
RATIO_MIN_BYTES = 64 << 20  # small members may legitimately compress far better

# Well-known MagicDraw / Cameo entry names. Anything else that sniffs as XMI is
# also accepted, so unknown versions still work.
PRIMARY_MODEL_ENTRIES = (
    "com.nomagic.magicdraw.uml_model.model",
    "com.nomagic.magicdraw.uml_model.shared_model",
)
MODEL_ENTRY_PREFIX = "com.nomagic.magicdraw.uml_model."
PROJECT_EXTS = {".mdzip", ".mdzipx", ".mdxml", ".xmi", ".xml", ".uml"}


class UnsupportedInput(Exception):
    pass


# What a damaged archive member raises when read (bad CRC, corrupt deflate stream...).
_READ_ERRORS = (zipfile.BadZipFile, zlib.error, EOFError)


@dataclass
class Project:
    """One Cameo project: a set of named entries, one or more of which hold XMI."""

    name: str
    container: tuple[str, ...]  # archive members leading to this project, outermost first
    model_entries: list[str]
    entry_names: list[str]
    sha256: str = ""  # of the project's own bytes: its identity (plan RI-02)
    data_size: int = 0
    _zip: zipfile.ZipFile | None = None
    _bare: bytes | None = None
    _budget: _Budget | None = None

    @property
    def chain(self) -> tuple[str, ...]:
        """Archive members from the input file down to this project; () for the input itself."""
        return (*self.container[1:], self.name) if self.container else ()

    @property
    def display_name(self) -> str:
        return PurePosixPath(self.name).name

    @property
    def kind(self) -> str:
        return "zip" if self._zip is not None else "xmi"

    @property
    def trace_container(self) -> tuple[str, ...]:
        """Container chain for provenance: includes this project's own archive name."""
        return self.container + (self.name,) if self._zip is not None else self.container

    def open(self, entry: str):
        if self._zip is not None:
            info = self._zip.getinfo(entry)
            if self._budget is not None:
                self._budget.take(self.trace_container, info)
            return self._zip.open(info)
        assert self._bare is not None
        return io.BytesIO(self._bare)

    def read(self, entry: str) -> bytes:
        with self.open(entry) as f:
            return f.read()

    def latest_entry_time(self):
        """The latest date among the zip's entries, as written (local time, no zone); None for
        a bare XMI file."""
        import datetime as dt

        if self._zip is None:
            return None
        times = [dt.datetime(*i.date_time) for i in self._zip.infolist() if i.date_time[0] >= 1981]
        return max(times) if times else None

    def size(self, entry: str) -> int:
        if self._zip is not None:
            return self._zip.getinfo(entry).file_size
        return len(self._bare or b"")


class _Budget:
    """Decompressed bytes allowed for one input. Each archive member counts once, however
    often it is opened (layout streams are opened twice: once to sniff, once to parse)."""

    def __init__(self) -> None:
        self.remaining = MAX_TOTAL_BYTES
        self.seen: set[str] = set()

    def take(self, chain: tuple[str, ...], info: zipfile.ZipInfo) -> None:
        if info.compress_size and info.file_size > RATIO_MIN_BYTES and info.file_size / info.compress_size > MAX_RATIO:
            raise UnsupportedInput(f"member {info.filename!r} has a suspicious compression ratio "
                                   f"({info.file_size // info.compress_size}:1)")
        key = "!".join((*chain, info.filename))
        if key in self.seen:
            return
        if info.file_size > self.remaining:
            raise UnsupportedInput(f"input exceeds {MAX_TOTAL_BYTES:,} decompressed bytes (at member {key!r})")
        self.remaining -= info.file_size
        self.seen.add(key)


_START_TAG = re.compile(rb"<([A-Za-z_][\w.-]*(?::[A-Za-z_][\w.-]*)?)[\s>/]")
_COMMENT = re.compile(rb"<!--.*?-->", re.DOTALL)
_XMI_ROOTS = {"XMI", "Model", "Package"}


def first_tag(head: bytes) -> str | None:
    """Qualified name of the first element start tag in `head` (the first bytes of an
    XML document), skipping any BOM, XML declaration, comments and doctype. None if
    `head` does not look like XML."""
    head = head.lstrip(b"\xef\xbb\xbf \t\r\n")
    if not head.startswith(b"<"):
        return None
    head = _COMMENT.sub(b"", head)
    m = _START_TAG.search(head)
    return m.group(1).decode("ascii") if m else None


def sniff_xmi(head: bytes) -> bool:
    """True if the first bytes look like an XMI document (root xmi:XMI or uml:Model)."""
    tag = first_tag(head)
    return bool(tag and tag.split(":")[-1] in _XMI_ROOTS and b"xmi" in head)


def _xmi_entries(zf: zipfile.ZipFile) -> list[str]:
    """Model entries of a MagicDraw project archive.

    `com.nomagic.magicdraw.uml_model.model` holds the project's own content; library and
    profile projects keep most content in `...uml_model.shared_model` (and
    `...____sharepoints.shared_model`). Cached copies of used projects (`proxy.*`),
    code-engineering sets and option files are not the project's content. For unknown
    layouts we fall back to sniffing for an XMI root.
    """
    names = [i.filename for i in zf.infolist() if not i.is_dir()]
    found = [n for n in names if n.startswith(MODEL_ENTRY_PREFIX)]
    found.sort(key=lambda n: (n not in PRIMARY_MODEL_ENTRIES, n))
    if found:
        return found
    for info in zf.infolist():
        n = info.filename
        if info.is_dir() or info.file_size < 64 or n.startswith(("BINARY-", "proxy.")):
            continue
        try:
            with zf.open(info) as f:
                if sniff_xmi(f.read(4096)):
                    found.append(n)
        except _READ_ERRORS as e:
            log.warning("skipping unreadable member %s: %s", n, e)
    return found


def discover(data: bytes, name: str, container: tuple[str, ...] = (), depth: int = 0,
             budget: _Budget | None = None) -> Iterator[Project]:
    """Yield every project found in `data` (the bytes of a file called `name`)."""
    budget = budget or _Budget()
    if data.startswith(ZIP_MAGIC):
        try:
            zf = zipfile.ZipFile(io.BytesIO(data))
        except zipfile.BadZipFile as e:
            raise UnsupportedInput(f"{name}: corrupt zip: {e}") from e
        if any(i.flag_bits & 0x1 for i in zf.infolist()):
            raise UnsupportedInput(f"{name}: zip is encrypted")
        models = _xmi_entries(zf)
        if models:
            yield Project(
                name=name,
                container=container,
                model_entries=models,
                entry_names=[i.filename for i in zf.infolist() if not i.is_dir()],
                sha256=hashlib.sha256(data).hexdigest(),
                data_size=len(data),
                _zip=zf,
                _budget=budget,
            )
        # Always look for nested projects too: .rdzip bundles, and .mdzip files that
        # embed used projects / modules.
        if depth >= MAX_NESTING:
            return
        chain = container + (name,)
        for info in zf.infolist():
            if info.is_dir() or info.file_size < 22:
                continue
            ext = PurePosixPath(info.filename).suffix.lower()
            try:
                with zf.open(info) as f:
                    head = f.read(4)
                if head != ZIP_MAGIC and ext not in PROJECT_EXTS - {".xml"}:
                    continue
                if models and head != ZIP_MAGIC:
                    continue  # XMI members of this project were handled above
                budget.take(chain, info)
                inner = zf.read(info)
                yield from discover(inner, info.filename, chain, depth + 1, budget)
            except (UnsupportedInput, *_READ_ERRORS) as e:  # one bad member must not stop the rest
                log.warning("skipping nested member %s: %s", "!".join((*chain, info.filename)), e)
        return
    if sniff_xmi(data[:4096]):
        yield Project(name=name, container=container, model_entries=[name], entry_names=[name],
                      sha256=hashlib.sha256(data).hexdigest(), data_size=len(data), _bare=data)
        return
    if depth == 0:
        raise UnsupportedInput(f"{name}: neither a zip archive nor an XMI document (starts with {data[:16]!r})")
