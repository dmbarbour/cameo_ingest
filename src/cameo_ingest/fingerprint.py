"""What a Cameo project says about itself, for finding versions of one model (plan PV-01).

- **Element ids:** Cameo keeps an element's `xmi:id` across saves, so versions of a model share
  most of theirs. They are kept as sorted 64-bit hashes (`array('Q')`, 8 bytes each).
- **The save time:** Cameo writes it at the head of `Records.properties`, as Java's
  `Date.toString` does (`#Thu Nov 02 11:39:23 PDT 2023`). Copying a file doesn't change it, as it
  does a file's own date. Without it, the latest date among the zip's entries stands in.
- **The project id** (`PROJECT-…`) and **the Cameo version:** shown for reference only. A
  project id alone can't be used: a model made from a template keeps the template's, and a
  migrated model may get a new one.
- **Each id's maker and day** (plan LN-01): most Cameo ids read
  `_<tool version>_<hex id>_<creation time, epoch ms>_<random>_<counter>`, and MagicDraw's older
  ones `eee_<epoch ms>_<random>_<counter>`. The hex id is taken for the maker (a user or an
  installation: inferred from the shape, not documented). Kept beside the hashes, in their order:
  a maker's index (`array('H')`, `NO_MAKER` for none) and the day (`array('I')`, days since 1970,
  0 for none). On the samples, 57% to 99% of a model's ids carry a maker.
"""

from __future__ import annotations

import datetime as dt
import hashlib
import re
import sys
from array import array
from typing import TYPE_CHECKING, Any

from .xmi import read_events

if TYPE_CHECKING:
    from .archive import Project

# Java's short time zone names, as they appear in Date.toString; others are kept as written.
ZONES = {"UTC": 0, "GMT": 0, "WET": 0, "BST": 1, "WEST": 1, "CET": 1, "CEST": 2, "MET": 1, "MEST": 2,
         "EET": 2, "EEST": 3, "MSK": 3, "IST": 5.5, "JST": 9, "KST": 9, "AEST": 10, "AEDT": 11, "NZST": 12,
         "NZDT": 13, "HST": -10, "AKST": -9, "AKDT": -8, "PST": -8, "PDT": -7, "MST": -7, "MDT": -6,
         "CST": -6, "CDT": -5, "EST": -5, "EDT": -4}
_JAVA_DATE = re.compile(r"^#(\w{3} \w{3} [ \d]\d \d\d:\d\d:\d\d) (\S+) (\d{4})\s*$", re.MULTILINE)
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
        when = dt.datetime.strptime(f"{m.group(1)} {m.group(3)}", "%a %b %d %H:%M:%S %Y")  # noqa: DTZ007 (zone below)
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
            for _, el in read_events(f, ("start",), entry):  # the build reports what was recovered
                for k, v in el.attrib.items():
                    if k.startswith("{http://www.omg.org/spec/XMI") and k.endswith("}id"):
                        ids.append(v)
                        break
    return ids


_VERSION = re.compile(r"\d+x?")
_HEX = re.compile(r"[0-9a-f]{4,8}")
_MS = re.compile(r"\d{12,13}")
NO_MAKER = 0xFFFF
DAY_MS = 86_400_000


def parse_id(xid: str) -> tuple[str | None, int | None]:
    """An id's maker (its hex id) and creation time (epoch ms), where its shape carries them."""
    t = xid.lstrip("_").split("_")
    if (len(t) >= 5 and _MS.fullmatch(t[-3]) and _HEX.fullmatch(t[-4]) and t[-2].isdigit() and t[-1].isdigit()
            and all(_VERSION.fullmatch(x) for x in t[:-4])):
        return t[-4], int(t[-3])
    if len(t) == 4 and _MS.fullmatch(t[1]) and t[2].isdigit() and t[3].isdigit():
        return None, int(t[1])  # eee_<ms>_<random>_<counter>: no maker
    return None, None


def _hash(xid: str) -> int:
    return int.from_bytes(hashlib.blake2b(xid.encode("utf-8"), digest_size=8).digest(), "little")


def marks(ids: list[str]) -> tuple[list[str], bytes, bytes]:
    """Each distinct id's maker and day, in `pack`'s order: the makers, then their indexes
    (`array('H')`) and the days (`array('I')`), little-endian."""
    by_hash: dict[int, tuple[str | None, int | None]] = {}
    for xid in ids:
        by_hash.setdefault(_hash(xid), parse_id(xid))
    makers = sorted({m for m, _ in by_hash.values() if m})
    index = {m: i for i, m in enumerate(makers)}
    who = array("H", (index[m] if m else NO_MAKER for _, (m, _t) in sorted(by_hash.items())))
    when = array("I", ((t // DAY_MS) if t else 0 for _, (_m, t) in sorted(by_hash.items())))
    if sys.byteorder != "little":
        who.byteswap()
        when.byteswap()
    return makers, who.tobytes(), when.tobytes()


def unpack_marks(blob_who: bytes, blob_when: bytes) -> tuple[array, array]:
    who, when = array("H"), array("I")
    who.frombytes(blob_who)
    when.frombytes(blob_when)
    if sys.byteorder != "little":
        who.byteswap()
        when.byteswap()
    return who, when


def unpack_list(blob: bytes) -> array:
    """The hashes, in their stored (sorted) order."""
    a = array("Q")
    a.frombytes(blob)
    if sys.byteorder != "little":
        a.byteswap()
    return a


def pack(ids: list[str]) -> bytes:
    """Ids as their sorted, distinct 64-bit hashes."""
    hashes = sorted({_hash(i) for i in ids})
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
    all_ids = element_ids(project)
    ids = pack(all_ids)
    makers, who, when = marks(all_ids)
    return {"saved": saved, "saved_raw": raw, "saved_from": source, "project_id": project_id,
            "exporter": _exporter(project), "elements": len(ids) // 8, "ids": ids,
            "makers": makers, "who": who, "when": when}
