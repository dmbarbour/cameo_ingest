"""Fictional Cameo projects for testing, with questions answered by construction (plan RE-10).

`PROJECTS` maps each project's prefix to the function that builds it; see `builder.Project`.
"""

from __future__ import annotations

from . import crossing, kiosk, orchard, rivals, traffic, water

PROJECTS = {"kois": orchard.build, "abk": kiosk.build, "rwt": water.build, "fvx": crossing.build,
            "pct": traffic.build, "hal": rivals.halvorsen, "aqu": rivals.aquila}


def is_fictional(element_id: str | None) -> bool:
    """Whether an element is a fictional project's: those have questions of their own, so the
    structural and natural question sets leave them out (AR-021R2)."""
    return bool(element_id) and element_id.startswith(tuple(f"_{p}_" for p in PROJECTS))


def ACROSS() -> list[dict]:
    """Questions with answers in parts: across the three Riverbend proposals (rwt, hal, aqu), along
    derivations within a model, and over a model's type hierarchy (plan TH)."""
    return rivals.across() + rivals.within() + traffic.kinds()
