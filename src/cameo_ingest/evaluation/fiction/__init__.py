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
    derivations within a model, over a model's type hierarchy (plan TH), and over what a diagram's
    blocks show (plan IS)."""
    return rivals.across() + rivals.within() + traffic.kinds() + shown()


def shown() -> list[dict]:
    """Questions that start from a diagram (plan IS): what its blocks show in their compartments.
    One part per member shown, held by the block's own chunk (its members, and the diagrams it is
    shown in) or by the diagram's, which says what its shapes hold."""
    rows = [("s01", "abk", "d_bdd"), ("s02", "kois", "d_bdd"), ("s03", "fvx", "d_sites"), ("s04", "rwt", "d_overview")]
    out = []
    for qid, prefix, key in rows:
        p = PROJECTS[prefix]()
        diagram = p.names[key]
        parts = []
        for m in p.shown[key]:
            block, member = p.names[m.split("__")[0]], p.names[m]
            line = f"«ProxyPort» {member}" if p.kinds[m] == "Port" else f"Property {member}"
            # The block's own chunk (its heading, the member's line, the diagrams it is shown in), or
            # the diagram's line for the block ("[1] «Block» Book Return Kiosk: properties throughput").
            parts.append([[f"{block} in ", line, diagram], [f"» {block}:", member, diagram]])
        questions = (f"Which properties and ports do the blocks on the {diagram} diagram show?",
                     f"What values, parts and ports can be read off {p.name}'s {diagram} diagram?")
        for style, text in zip(("literal", "paraphrase"), questions, strict=True):
            out.append({"id": f"shown-{qid}-{style}", "rule": "parts", "fact": f"shown-{qid}", "style": style,
                        "category": "diagram-contents", "difficulty": "hard", "question": text, "answers": [],
                        "related": [], "evidence": [], "evidence_groups": parts,
                        "group_elements": [[p.id(m.split("__")[0]), p.id(m), p.id(key)] for m in p.shown[key]],
                        "project_name": p.name})
    return out
