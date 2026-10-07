"""Lineage cases (plan LN-02): fictional projects whose ids are rewritten in Cameo's shape,
`_2024x_2_<maker>_<epoch ms>_<random>_<counter>`, with makers and times known, so that versions,
models derived by others, rivals on a shared root, and related models can be told apart by who
made their ids and when. Kept out of `PROJECTS` and `VERSIONS`.

The cases, all in one corpus (`corpus()`), with what each pair is (`TRUTH`):
- **Kestrel, saved again later:** the orchard's maker adds a package after the first save.
- **Riverbend's tender, and two bids on it:** the customer's model (the root); Halvorsen and
  Aquila each add their own packages to a copy, in the same months; Halvorsen saves a second
  version later, with more of its own.
- **Ashgrove, copied unchanged** to another folder.
- **Two unrelated models sharing a library:** Port Calder and the Ferrous Valley crossing both
  hold the same library of signal equipment, made once by a third maker.

The bids also edit what they took from the customer, as `EDITS` says (plan SH): Aquila rewords a
requirement and renames a pump; Halvorsen satisfies a requirement with a block of its own.
"""

from __future__ import annotations

import hashlib
import io
import re
import zipfile
from dataclasses import dataclass
from xml.sax.saxutils import quoteattr

from . import crossing, kiosk, orchard, traffic, water
from .builder import Project
from .versions import ADDED_BLOCK, _add_package, _rename, ids

DAY = 86_400_000
T0 = 1735689600000  # 2025-01-01, ms

# The makers: hex ids, as Cameo's would be.
ORCHARD, CUSTOMER, HALVORSEN, AQUILA, LIBRARY, CITY, RAIL, LIBRARIAN = (
    "6a01c3e", "c0ffee1", "a1fe5e2", "b2aa101", "11b7a7e", "c17e0a9", "4a11b00", "e1b0a6d")


@dataclass
class Case:
    path: str
    mdzip: bytes
    tokens: set[str]


def _cameo(p: Project, made: dict[str, tuple[str, int]], keys: dict[str, str] | None = None) -> bytes:
    """The project's file with every id rewritten: `made` gives each fictional id's maker and
    creation time; `keys`, an id's key when another project writes the same id (a library's)."""
    pattern = re.compile(rf"_{re.escape(p.prefix)}_[A-Za-z0-9_]+")
    keys = keys or {}

    def cameo_id(token: str) -> str:
        maker, ms = made[token]
        n = int.from_bytes(hashlib.sha256(keys.get(token, token).encode()).digest()[:4], "big")
        return f"_2024x_2_{maker}_{ms}_{n % 1_000_000}_{n % 100_000}"

    src = zipfile.ZipFile(io.BytesIO(p.mdzip()))
    out = io.BytesIO()
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as z:
        for info in src.infolist():
            data = src.read(info)
            if not info.filename.startswith("BINARY-img"):
                text = pattern.sub(lambda m: cameo_id(m.group(0)) if m.group(0) in made else m.group(0),
                                   data.decode("utf-8"))
                data = text.encode("utf-8")
            z.writestr(info, data)
    return out.getvalue()


def _times(tokens: list[str], maker: str, start_day: int, days: int) -> dict[str, tuple[str, int]]:
    """Each token made by `maker`, spread over `days` days from `start_day` (days after T0)."""
    toks = sorted(tokens)
    return {t: (maker, T0 + (start_day + i * days // max(1, len(toks))) * DAY + i * 1000) for i, t in enumerate(toks)}


def _saved(day: int) -> tuple[int, int, int, int, int, int]:
    import datetime as dt
    d = dt.datetime(2025, 1, 1) + dt.timedelta(days=day)  # noqa: DTZ001 (the zip's local time, as Cameo's)
    return (d.year, d.month, d.day, 12, 0, 0)


def _reword(p: Project, key: str, text: str) -> None:
    """Change a requirement's text, as a bidder editing the customer's would."""
    head = f"base_Class='{p.id(key)}'"
    i = next(i for i, a in enumerate(p.applications) if head in a and " Text=" in a)
    p.applications[i] = re.sub(r" Text=(\"[^\"]*\"|'[^']*')", lambda m: f" Text={quoteattr(text)}", p.applications[i])
    p.texts[key] = text


REWORDED = "The works shall treat up to 60 megalitres per day, with one filter out of service."


def _library(p: Project, size: int = 16) -> None:
    """The same library package, with the same ids, in any project: keys `lib_…` map to one set of ids."""
    p.package("lib_pkg", "Signal Equipment Library", doc="Shared catalogue of approved signal equipment.")
    for i in range(1, size + 1):
        p.block(f"lib_b{i}", f"Library Signal Head {i}", "lib_pkg", "From the shared equipment library.",
                values=ADDED_BLOCK)


def _lib_id(p: Project, token: str) -> str:
    """A library token as every project writes it: without the project's prefix."""
    return "_lib_" + token.removeprefix(f"_{p.prefix}_").removeprefix("lib_")


def _edit(bid: Project, bidder: str, maker: str) -> None:
    """What each bidder changes in the customer's part (`EDITS`)."""
    if bidder == "Aquila":
        _reword(bid, "prf01", REWORDED)
        _rename(bid, "llpump", "Low-Lift Pump (Aquila)")
    else:
        bid.relate("satisfy", f"v_v_{maker}_1_1", "prf02", f"v_{maker}_1")  # its first block (`_add_package`'s key)


# The customer's items each bid changed (plan SH-02): (bid folder, the item's key in the fiction, the aspect).
EDITS = [("lineage/bids/aquila", "prf01", "text"), ("lineage/bids/aquila", "llpump", "name"),
         ("lineage/bids/halvorsen", "prf02", "relations"), ("lineage/bids/halvorsen/v2", "prf02", "relations")]


def corpus() -> list[Case]:
    cases = []

    # Kestrel, and a later save by the same maker.
    k1 = orchard.build()
    k1.folder, k1.saved = "lineage/kestrel/2025-03", _saved(60)
    base = ids(k1)
    made = _times(sorted(base), ORCHARD, 0, 55)
    cases.append(Case(k1.path, _cameo(k1, made), base))
    k2 = orchard.build()
    k2.folder, k2.saved = "lineage/kestrel/2025-07", _saved(180)
    _add_package(k2, "v_frost", "Frost Protection", 2, "Added for the second season.", [])
    _rename(k2, next(k for k in k2.parts if not k.startswith("v_")), "Pump Station (rev B)")
    later = ids(k2)
    made2 = {**made, **_times(sorted(later - base), ORCHARD, 90, 60)}
    cases.append(Case(k2.path, _cameo(k2, made2), later))

    # Riverbend's tender, the customer's root, and two bids on it in the same months.
    root = water.build()
    root.folder, root.saved = "lineage/tender", _saved(40)
    rb = ids(root)
    made_root = _times(sorted(rb), CUSTOMER, 0, 35)
    cases.append(Case(root.path, _cameo(root, made_root), rb))
    for bidder, maker, folder, packages in (("Halvorsen", HALVORSEN, "lineage/bids/halvorsen", 3),
                                            ("Aquila", AQUILA, "lineage/bids/aquila", 4)):
        bid = water.build()
        bid.folder, bid.saved = folder, _saved(120)
        for n in range(1, packages + 1):
            _add_package(bid, f"v_{maker}_{n}", f"{bidder} Design Part {n}", 3, f"{bidder}'s own design, part {n}.", [])
        _edit(bid, bidder, maker)
        own = ids(bid) - rb
        made_bid = {**made_root, **_times(sorted(own), maker, 50, 60)}
        cases.append(Case(bid.path, _cameo(bid, made_bid), ids(bid)))
        if bidder == "Halvorsen":  # and its second version, later, with more of its own
            bid2 = water.build()
            bid2.folder, bid2.saved = folder + "/v2", _saved(200)
            for n in range(1, packages + 2):
                _add_package(bid2, f"v_{maker}_{n}", f"{bidder} Design Part {n}", 3, f"{bidder}'s own design, part {n}.", [])
            _edit(bid2, bidder, maker)
            own2 = ids(bid2) - rb - own
            made_bid2 = {**made_bid, **_times(sorted(own2), maker, 140, 40)}
            cases.append(Case(bid2.path, _cameo(bid2, made_bid2), ids(bid2)))

    # Ashgrove, copied unchanged.
    for folder, day in (("lineage/kiosk", 30), ("lineage/kiosk-copy", 90)):
        a = kiosk.build()
        a.folder, a.saved = folder, _saved(day)
        ab = ids(a)
        cases.append(Case(a.path, _cameo(a, _times(sorted(ab), LIBRARY, 0, 25)), ab))

    # Two unrelated models that hold one library, made once by its own maker.
    lib_made = {}
    for build, maker, folder in ((traffic.build, CITY, "lineage/city"), (crossing.build, RAIL, "lineage/rail")):
        p = build()
        p.folder, p.saved = folder, _saved(150)
        _library(p)
        mine = ids(p)
        made_p: dict[str, tuple[str, int]] = {}
        for t in sorted(mine):
            if t.startswith(f"_{p.prefix}_lib_"):
                continue
            made_p[t] = (maker, T0 + (len(made_p) % 200) * DAY)  # over 200 days; the library came on day 150
        cases.append(Case(p.path, _cameo_library(p, made_p, lib_made), mine))
    return cases


def _cameo_library(p: Project, made: dict[str, tuple[str, int]], lib_made: dict[str, tuple[str, int]]) -> bytes:
    """As `_cameo`, the library's ids the same, whichever project holds them."""
    lib_tokens = sorted(t for t in ids(p) if t.startswith(f"_{p.prefix}_lib_"))
    for t in lib_tokens:
        lib_made.setdefault(_lib_id(p, t), (LIBRARIAN, T0 + 150 * DAY + len(lib_made) * 1000))
    return _cameo(p, {**made, **{t: lib_made[_lib_id(p, t)] for t in lib_tokens}},
                  {t: _lib_id(p, t) for t in lib_tokens})


# What each pair is, by path: (a, b, kind), with b the later or derived one where there is an order.
TRUTH = [
    ("lineage/kestrel/2025-03/Kestrel_Orchard_Irrigation.mdzip",
     "lineage/kestrel/2025-07/Kestrel_Orchard_Irrigation.mdzip", "version"),
    ("lineage/tender/Riverbend_Water_Treatment_Works.mdzip",
     "lineage/bids/halvorsen/Riverbend_Water_Treatment_Works.mdzip", "derived"),
    ("lineage/tender/Riverbend_Water_Treatment_Works.mdzip",
     "lineage/bids/aquila/Riverbend_Water_Treatment_Works.mdzip", "derived"),
    ("lineage/tender/Riverbend_Water_Treatment_Works.mdzip",
     "lineage/bids/halvorsen/v2/Riverbend_Water_Treatment_Works.mdzip", "derived"),
    ("lineage/bids/halvorsen/Riverbend_Water_Treatment_Works.mdzip",
     "lineage/bids/halvorsen/v2/Riverbend_Water_Treatment_Works.mdzip", "version"),
    ("lineage/bids/halvorsen/Riverbend_Water_Treatment_Works.mdzip",
     "lineage/bids/aquila/Riverbend_Water_Treatment_Works.mdzip", "root"),
    ("lineage/bids/halvorsen/v2/Riverbend_Water_Treatment_Works.mdzip",
     "lineage/bids/aquila/Riverbend_Water_Treatment_Works.mdzip", "root"),
    ("lineage/kiosk/Ashgrove_Library_Book_Return_Kiosk.mdzip",
     "lineage/kiosk-copy/Ashgrove_Library_Book_Return_Kiosk.mdzip", "copy"),
    ("lineage/city/Port_Calder_Traffic_Signal_System.mdzip",
     "lineage/rail/Ferrous_Valley_Level_Crossing.mdzip", "related"),
]
