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
    derivations within a model, over a model's type hierarchy (plan TH), over what a diagram's
    blocks show (plan IS), and lists of what a package holds (plan RM). Questions about where
    something is described (`where`, plan GS) are graded by element, and kept apart."""
    return rivals.across() + rivals.within() + traffic.kinds() + shown() + lists()


def where() -> list[dict]:
    """Questions about where something is described (plan GS-04): what search by meaning is for.
    Graded by element: a window of the behavior or package that answers, or of its diagram,
    answers; one of what sits beside it relates. The literal question uses the model's words;
    the paraphrase, a person's."""
    rows = [
        ("w01", "abk", ["return", "d_return"], ["bh", "modes"],
         "Where does the Ashgrove kiosk model describe the steps of returning an item?",
         "Where can I read what the library's after-hours drop box does with each book it takes in?"),
        ("w02", "rwt", ["bwseq", "d_bw"], ["fsm", "d_fsm"],
         "Which part of the Riverbend model sets out how a filter is backwashed?",
         "Where is the procedure for washing out a dirty filter at the water works?"),
        ("w03", "fvx", ["faultresp", "d_fault"], ["seq", "d_seq"],
         "Which part of the Ferrous Valley model covers the response to a barrier fault?",
         "Where is it written what the level crossing does when a gate gets stuck?"),
        ("w04", "pct", ["eq", "d_eq"], ["sys"],
         "Which part of the Port Calder model catalogues the approved field equipment?",
         "Where would I find which kinds of traffic-light hardware the city allows?"),
        ("w05", "pct", ["cor_hr", "d_cor_hr"], ["net", "d_network"],
         "Which part of the Port Calder model covers the signalised intersections along Harbour Road?",
         "Where are the traffic lights on the road leading out from the harbour described?"),
        ("w06", "rwt", ["modes", "d_modes"], ["chem"],
         "Which part of the Riverbend model describes the works' operating modes?",
         "Where does it say how the treatment plant is run differently in a cold season or after heavy rain?"),
    ]
    out = []
    for qid, prefix, answers, related, literal, paraphrase in rows:
        p = PROJECTS[prefix]()
        for style, text in (("literal", literal), ("paraphrase", paraphrase)):
            out.append({"id": f"where-{qid}-{style}", "rule": "element", "fact": f"where-{qid}", "style": style,
                        "category": "where", "difficulty": "medium", "question": text,
                        "answers": [p.id(k) for k in answers], "related": [p.id(k) for k in related],
                        "evidence": [], "prefix": f"_{prefix}_", "project_name": p.name})
    return out


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


def lists() -> list[dict]:
    """Questions that ask for a list, what ledgers are for (plan RM-03): a package's requirements
    with what satisfies each, its needs, its instruments, its diagrams. One part per item, held by
    the item's own chunk, or by a chunk that lists it with what the question asks of it."""
    out = []

    def ask(qid: str, prefix: str, literal: str, paraphrase: str, parts: list, elements: list) -> None:
        for style, text in (("literal", literal), ("paraphrase", paraphrase)):
            out.append({"id": f"list-{qid}-{style}", "rule": "parts", "fact": f"list-{qid}", "style": style,
                        "category": "list", "difficulty": "hard" if len(parts) > 6 else "medium", "question": text,
                        "answers": [], "related": [], "evidence": [], "evidence_groups": parts,
                        "group_elements": elements, "project_name": PROJECTS[prefix]().name})

    p = PROJECTS["abk"]()
    reqs = [k for k in p.owned("rq") if k in p.rids]
    satisfies = {t: s for rel, (s, t) in p.ends.items() if rel.startswith("satisfy__")}
    # A requirement and what satisfies it: the requirement's chunk, the block's, or a ledger's line.
    ask("l01", "abk", f"Which requirements does the {p.name} model state, and what satisfies each?",
        "What must the library's returns kiosk do, and which of its parts sees to each?",
        [[[p.rids[r], p.names[satisfies[r]]]] if r in satisfies else [[p.rids[r], p.names[r]]] for r in reqs],
        [[p.id(r)] + ([p.id(satisfies[r])] if r in satisfies else []) for r in reqs])

    p = PROJECTS["fvx"]()
    needs = [k for k in p.owned("needs") if k in p.rids]
    # By id and the start of its text: requirements derived from a need name it, but don't quote it.
    ask("l02", "fvx", f"List the stakeholder needs recorded in the {p.name} model.",
        "What did the people consulted about the Ferrous Valley crossing ask of it?",
        [[[p.rids[k], p.texts[k][:40]]] for k in needs], [[p.id(k)] for k in needs])
    diagrams = [k for k in p.diagram_owners if p.package_of(k) == "common"]
    # By name and kind: the diagram's own heading, or a ledger's line (the package's text says
    # "variants" too).
    ask("l04", "fvx", f"Which diagrams does the {p.name} model's {p.names['common']} package hold?",
        "What views of the Ferrous Valley crossing's shared design have been drawn?",
        [[[p.names[k], p.diagram_owners[k][1], p.names["common"]]] for k in diagrams], [[p.id(k)] for k in diagrams])

    p = PROJECTS["rwt"]()
    blocks = [k for k in p.owned("inst") if p.kinds[k] == "Class"]
    ask("l03", "rwt", f"Which instruments does the {p.name} model list in its {p.names['inst']} package?",
        "What measuring devices are installed around the Riverbend treatment works?",
        [[[p.names[k], p.names["inst"]]] for k in blocks], [[p.id(k)] for k in blocks])
    return out

