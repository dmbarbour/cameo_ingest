"""Locate Cameo projects inside the input file, whatever the wrapping.

Detection goes by content, not by file extension: a zip that contains an XMI model
entry is a project; a zip without one (e.g. a .rdzip bundle) is searched for nested
zips; a bare XML file with an XMI root (e.g. .mdxml / .xmi) is a single-entry project.
Everything is read in memory, so malicious member paths cannot escape to disk. Size
limits guard against zip bombs.
"""

from __future__ import annotations

import io
import logging
import re
import zipfile
from collections.abc import Iterator
from dataclasses import dataclass, field
from pathlib import PurePosixPath

log = logging.getLogger(__name__)

ZIP_MAGIC = b"PK\x03\x04"
MAX_NESTING = 4
MAX_MEMBER_BYTES = 4 << 30  # 4 GiB uncompressed per member
MAX_RATIO = 400  # uncompressed / compressed, beyond which we suspect a zip bomb

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


@dataclass
class Project:
    """One Cameo project: a set of named entries, one or more of which hold XMI."""

    name: str
    container: tuple[str, ...]  # archive members leading to this project, outermost first
    model_entries: list[str]
    entry_names: list[str]
    _zip: zipfile.ZipFile | None = None
    _bare: bytes | None = None
    notes: list[str] = field(default_factory=list)

    @property
    def trace_container(self) -> tuple[str, ...]:
        """Container chain for provenance: includes this project's own archive name."""
        return self.container + (self.name,) if self._zip is not None else self.container

    def open(self, entry: str):
        if self._zip is not None:
            info = self._zip.getinfo(entry)
            _check_member(info)
            return self._zip.open(info)
        assert self._bare is not None
        return io.BytesIO(self._bare)

    def read(self, entry: str) -> bytes:
        with self.open(entry) as f:
            return f.read()

    def size(self, entry: str) -> int:
        if self._zip is not None:
            return self._zip.getinfo(entry).file_size
        return len(self._bare or b"")


def _check_member(info: zipfile.ZipInfo) -> None:
    if info.file_size > MAX_MEMBER_BYTES:
        raise UnsupportedInput(f"member {info.filename!r} too large ({info.file_size} bytes)")
    if info.compress_size and info.file_size / info.compress_size > MAX_RATIO and info.file_size > 64 << 20:
        raise UnsupportedInput(f"member {info.filename!r} has a suspicious compression ratio")


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
        with zf.open(info) as f:
            if sniff_xmi(f.read(4096)):
                found.append(n)
    return found


def discover(data: bytes, name: str, container: tuple[str, ...] = (), depth: int = 0) -> Iterator[Project]:
    """Yield every project found in `data` (the bytes of a file called `name`)."""
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
                _zip=zf,
            )
        # Always look for nested projects too: .rdzip bundles, and .mdzip files that
        # embed used projects / modules.
        if depth >= MAX_NESTING:
            return
        for info in zf.infolist():
            if info.is_dir() or info.file_size < 22:
                continue
            ext = PurePosixPath(info.filename).suffix.lower()
            with zf.open(info) as f:
                head = f.read(4)
            if head != ZIP_MAGIC and ext not in PROJECT_EXTS - {".xml"}:
                continue
            if models and head != ZIP_MAGIC:
                continue  # XMI members of this project were handled above
            _check_member(info)
            inner = zf.read(info)
            try:
                yield from discover(inner, info.filename, container + (name,), depth + 1)
            except UnsupportedInput as e:
                log.warning("skipping nested member: %s", e)
        return
    if sniff_xmi(data[:4096]):
        yield Project(name=name, container=container, model_entries=[name], entry_names=[name], _bare=data)
        return
    if depth == 0:
        raise UnsupportedInput(f"{name}: neither a zip archive nor an XMI document (starts with {data[:16]!r})")
