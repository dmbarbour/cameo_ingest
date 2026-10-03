"""What a Cameo project says about itself, for finding versions of one model (plan PV-01).

- **Element ids:** Cameo keeps an element's `xmi:id` across saves, so versions of a model share
  most of theirs. They are kept as sorted 64-bit hashes (`array('Q')`, 8 bytes each).
- **The save time:** Cameo writes it at the head of `Records.properties`, as Java's
  `Date.toString` does (`#Thu Nov 02 11:39:23 PDT 2023`). Copying a file doesn't change it, as it
  does a file's own date. Without it, the latest date among the zip's entries stands in.
- **The project id** (`PROJECT-…`) and **the Cameo version:** shown for reference only. A
  project id alone can't be used: a model made from a template keeps the template's, and a
  migrated model may get a new one.
"""

from __future__ import annotations

import datetime as dt
import hashlib
import re
import sys
from array import array
from typing import TYPE_CHECKING, Any

from lxml import etree

if TYPE_CHECKING:
    from .archive import Project

# Java's short time zone names, as they appear in Date.toString; others are kept as written.
ZONES = {"UTC": 0, "GMT": 0, "WET": 0, "BST": 1, "WEST": 1, "CET": 1, "CEST": 2, "MET": 1, "MEST": 2,
         "EET": 2, "EEST": 3, "MSK": 3, "IST": 5.5, "JST": 9, "KST": 9, "AEST": 10, "AEDT": 11, "NZST": 12,
         "NZDT": 13, "HST": -10, "AKST": -9, "AKDT": -8, "PST": -8, "PDT": -7, "MST": -7, "MDT": -6,
         "CST": -6, "CDT": -5, "EST": -5, "EDT": -4}
_JAVA_DATE = re.compile(r"^#(\w{3} \w{3} [ \d]\d \d\d:\d\d:\d\d) (\S+) (\d{4})\s*$", re.M)
_PROJECT_ID = re.compile(rb'\bid="(PROJECT-[^"]+)"')
_PROPERTIES = ("Records.properties", "Binaries.properties")
METAMODEL = "com.nomagic.ci.metamodel.project"


def parse_java_date(text: str) -> tuple[str | None, str | None]:
    """(ISO 8601, as written) from a properties file's head; ISO with an offset when the zone is
    known, else without one."""
    m = _JAVA_DATE.search(text)
    if not m:
        return None, None
    raw = f"{m.group(1)} {m.group(2)} {m.group(3)}"
    try:
        when = dt.datetime.strptime(f"{m.group(1)} {m.group(3)}", "%a %b %d %H:%M:%S %Y")
    except ValueError:
        return None, raw
    hours = ZONES.get(m.group(2))
    if hours is not None:
        when = when.replace(tzinfo=dt.timezone(dt.timedelta(hours=hours)))
    return when.isoformat(), raw


def element_ids(project: Project) -> list[str]:
    """Every `xmi:id` in the project's model entries."""
    ids: list[str] = []
    for entry in project.model_entries:
        with project.open(entry) as f:
            for _, el in etree.iterparse(f, events=("start",), huge_tree=True, resolve_entities=False,
                                         no_network=True, load_dtd=False, remove_comments=True, remove_pis=True):
                for k, v in el.attrib.items():
                    if k.startswith("{http://www.omg.org/spec/XMI") and k.endswith("}id"):
                        ids.append(v)
                        break
    return ids


def pack(ids: list[str]) -> bytes:
    """Ids as their sorted, distinct 64-bit hashes."""
    hashes = sorted({int.from_bytes(hashlib.blake2b(i.encode("utf-8"), digest_size=8).digest(), "little")
                     for i in ids})
    a = array("Q", hashes)
    if sys.byteorder != "little":
        a.byteswap()
    return a.tobytes()


def unpack(blob: bytes) -> set[int]:
    a = array("Q")
    a.frombytes(blob)
    if sys.byteorder != "little":
        a.byteswap()
    return set(a)


def _exporter(project: Project) -> str | None:
    """"MagicDraw UML 2024x", from the model's xmi:Documentation (its head only)."""
    for entry in project.model_entries:
        with project.open(entry) as f:
            head = f.read(4096).decode("utf-8", "replace")
        tool = re.search(r"<xmi:exporter>([^<]*)</xmi:exporter>", head)
        version = re.search(r"<xmi:exporterVersion>([^<]*)</xmi:exporterVersion>", head)
        if tool or version:
            return " ".join(x.group(1).strip() for x in (tool, version) if x)
    return None


def fingerprint(project: Project) -> dict[str, Any]:
    names = set(project.entry_names)
    saved = raw = source = None
    for entry in _PROPERTIES:
        if entry in names:
            with project.open(entry) as f:
                saved, raw = parse_java_date(f.read(512).decode("latin-1"))
            if raw:
                source = "records"
                break
    if raw is None and (latest := project.latest_entry_time()) is not None:
        saved, raw, source = latest.isoformat(), latest.isoformat(sep=" "), "zip"
    project_id = None
    if METAMODEL in names:
        with project.open(METAMODEL) as f:
            m = _PROJECT_ID.search(f.read(2048))
        project_id = m.group(1).decode("ascii", "replace") if m else None
    ids = pack(element_ids(project))
    return {"saved": saved, "saved_raw": raw, "saved_from": source, "project_id": project_id,
            "exporter": _exporter(project), "elements": len(ids) // 8, "ids": ids}
