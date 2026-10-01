"""Fictional Cameo projects for testing, with questions answered by construction (plan RE-10).

`PROJECTS` maps each project's prefix to the function that builds it; see `builder.Project`.
"""

from __future__ import annotations

from . import crossing, kiosk, rivals, traffic, water

PROJECTS = {"abk": kiosk.build, "rwt": water.build, "fvx": crossing.build, "pct": traffic.build,
            "hal": rivals.halvorsen, "aqu": rivals.aquila}
def ACROSS() -> list[dict]:
    """Questions with answers in parts: across the three Riverbend proposals (rwt, hal, aqu), and
    along derivations within a model."""
    return rivals.across() + rivals.within()
