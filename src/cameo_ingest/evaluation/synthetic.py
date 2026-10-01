"""A synthetic Cameo project with planted facts, and questions whose answers are known by
construction (plan RE, the maintainer's suggestion of 2026-09-30).

The Kestrel Orchard Irrigation System (KOIS) is invented, with names and figures that appear
nowhere else ("Brine Valve K7", 340 milliseconds), so that each question has one right answer
even in an index of every sample. Each fact is asked twice:
- **literal:** with the model's own names, which keyword search can match;
- **paraphrase:** without them, so that only the meaning can find the answer.

`make_mdzip()` builds the project in the same XMI and layout format as Cameo (see
tests/fixture_model.py); `QUESTIONS` lists the questions, with the ids of the elements that
answer them (`answers`) and of those that help (`related`).
"""

from __future__ import annotations

import io
import zipfile
from xml.sax.saxutils import quoteattr

NAME = "Kestrel Orchard Irrigation"

# Blocks: id, name, documentation, value properties (name, type, default).
BLOCKS = [
    ("kois", "Kestrel Orchard Irrigation System",
     ("The Kestrel Orchard Irrigation System waters a 40-hectare apple orchard in rows, at night, from stored "
     "rainwater."), []),
    ("ctl", "KOIS Controller",
     ("The KOIS Controller runs on a solar-charged Lumen-9 board mounted on the pump house roof, and schedules "
     "every watering cycle."), []),
    ("lat", "Moisture Lattice",
     ("The Moisture Lattice is a grid of 48 capacitive probes buried 30 cm deep in a hexagonal pattern under the "
     "orchard rows."), []),
    ("k7", "Brine Valve K7",
     "Brine Valve K7 is the master shut-off valve between the pump station and the orchard mains.",
     [("closeTime", "Real", "340")]),
    ("dos", "Nutrient Doser",
     "The Nutrient Doser meters the Verdant-3 nutrient blend into the irrigation water.", []),
    ("frs", "Frost Shield",
     ("The Frost Shield sprays a fine warm mist over the blossoms when the air temperature falls below 1.5 degrees "
     "Celsius."), []),
    ("rba", "Rain Barrel Array",
     "The Rain Barrel Array stores roof runoff from the packing shed in linked polyethylene tanks.",
     [("capacityLitres", "Integer", "12000")]),
    ("pmp", "Pump Station",
     "The Pump Station houses two pumps, named Otter and Heron, which alternate nightly to share the wear.", []),
]
PARTS = ["ctl", "lat", "k7", "dos", "frs", "rba", "pmp"]  # composed into the system block

# Requirements: id, requirement id, name, text.
REQUIREMENTS = [
    ("r1", "KOIS-R1", "Soil Moisture Band",
     "The system shall keep soil moisture between 18% and 26% in every orchard row."),
    ("r2", "KOIS-R2", "Valve Closing Time",
     "Brine Valve K7 shall close within 340 milliseconds of a leak signal."),
    ("r3", "KOIS-R3", "Frost Protection",
     "The system shall protect the blossoms from frost down to minus 4 degrees Celsius."),
    ("r4", "KOIS-R4", "Nutrient Ratio",
     "The Nutrient Doser shall not exceed 1 part nutrient blend per 400 parts water."),
    ("r5", "KOIS-R5", "Leak Shutdown",
     "The system shall stop all water flow within 1 second of detecting a leak."),
    ("r6", "KOIS-R6", "Rainwater Storage",
     "The system shall store at least 10,000 litres of rainwater."),
    ("r7", "KOIS-R7", "Cycle Log Retention",
     "The KOIS Controller shall keep a log of every watering cycle for 3 years."),
]
SATISFY = [("lat", "r1"), ("k7", "r2"), ("frs", "r3"), ("dos", "r4"), ("rba", "r6"), ("ctl", "r7")]
DERIVE = [("r2", "r5")]  # (derived, source): the valve's closing time is derived from the leak shutdown

# Activities: id, name, documentation, nodes (id, kind, name), edges (source, target, name).
ACTIVITIES = [
    ("night", "Night Watering Cycle",
     "The Night Watering Cycle runs every night at 02:00, when evaporation is lowest.",
     [("n0", "InitialNode", ""), ("n1", "OpaqueAction", "Read Moisture Lattice"),
      ("n2", "OpaqueAction", "Check Frost Forecast"), ("n3", "DecisionNode", ""),
      ("n4", "OpaqueAction", "Run Frost Shield"), ("n5", "OpaqueAction", "Open Row Valves"),
      ("n6", "OpaqueAction", "Dose Nutrients"), ("n7", "OpaqueAction", "Close Row Valves"),
      ("n8", "ActivityFinalNode", "")],
     [("n0", "n1", ""), ("n1", "n2", ""), ("n2", "n3", ""), ("n3", "n4", "frost expected"),
      ("n3", "n5", "no frost"), ("n4", "n5", ""), ("n5", "n6", ""), ("n6", "n7", ""), ("n7", "n8", "")]),
    ("leak", "Leak Response",
     "The Leak Response runs whenever the mains pressure drops suddenly.",
     [("m0", "InitialNode", ""), ("m1", "OpaqueAction", "Detect Pressure Drop"),
      ("m2", "OpaqueAction", "Close Brine Valve K7"), ("m3", "OpaqueAction", "Text the Grower"),
      ("m4", "ActivityFinalNode", "")],
     [("m0", "m1", ""), ("m1", "m2", ""), ("m2", "m3", ""), ("m3", "m4", "")]),
]

# Questions: id, category, literal question, paraphrase, answers, related, and the evidence: a
# phrase (or alternatives) that the chunks of the answering elements must contain (tested), so
# that the answer key can't drift from the model. Any chunk of the project holding it also
# answers the question (a ledger or summary quoting the fact, say).
_QUESTIONS = [
    ("q01", "lookup", "What is the Moisture Lattice made of?",
     "How is the wetness of the soil sensed across the orchard?", ["lat"], ["r1"], "48 capacitive probes"),
    ("q02", "parameter", "How quickly must Brine Valve K7 close after a leak signal?",
     "How fast does the master shut-off valve have to shut when water escapes?", ["r2"], ["k7", "r5"], "340 milliseconds"),
    ("q03", "lookup", "Which board does the KOIS Controller run on?",
     "What hardware does the irrigation scheduler run on?", ["ctl"], [], "Lumen-9"),
    ("q04", "lookup", "Which nutrient blend does the Nutrient Doser meter?",
     "Which fertilizer mix is added to the irrigation water?", ["dos"], ["r4"], "Verdant-3"),
    ("q05", "parameter", "At what temperature does the Frost Shield start spraying?",
     "When do the trees start getting warmed on cold nights?", ["frs"], ["r3"], "1.5 degrees"),
    ("q06", "parameter", "How many litres does the Rain Barrel Array hold?",
     "How much harvested rain can the orchard keep in reserve?", ["rba"], ["r6"], "12000"),
    ("q07", "lookup", "What are the pumps in the Pump Station called?",
     "What names were given to the two water pumps?", ["pmp"], [], "Otter and Heron"),
    ("q08", "trace", "Which requirement is KOIS-R2 derived from?",
     "Which broader safety need does the valve's closing time come from?", ["r5", "r2"], [],
     ["is derived from [Leak Shutdown]", "derived from Leak Shutdown", "derived from the Leak Shutdown"]),
    ("q09", "trace", "Which block satisfies KOIS-R3, Frost Protection?",
     "Which component is responsible for keeping blossoms from freezing?", ["frs", "r3"], [],
     ["[Frost Shield] satisfies this", "satisfies [Frost Protection]", "Frost Shield satisfies"]),
    ("q10", "parameter", "What soil moisture range must KOIS keep in every orchard row?",
     "How damp should the ground under the apple trees be kept?", ["r1"], ["lat"], "between 18% and 26%"),
    ("q11", "parameter", "How long must the KOIS Controller keep its watering cycle log?",
     "For how many years is the history of each night's watering kept?", ["r7"], ["ctl"], "for 3 years"),
    ("q12", "behaviour", "In the Night Watering Cycle, what follows Dose Nutrients?",
     "What is the last step before the nightly watering finishes?", ["night"], ["d_night"], "Close Row Valves"),
    ("q13", "behaviour", "What happens in the Leak Response after a pressure drop is detected?",
     "How does the system react when the pipes lose pressure suddenly?", ["leak"], ["k7", "r5"], "Close Brine Valve K7"),
    ("q14", "structure", "What parts make up the Kestrel Orchard Irrigation System?",
     "What are the main components of the orchard watering system?", ["kois"], ["d_bdd"], "Pump Station"),
]


def holds(evidence: list[str], text: str) -> bool:
    """Whether `text` holds the planted fact: one of the evidence phrases, in any case."""
    low = text.lower()
    return any(e.lower() in low for e in evidence)


def _id(key: str) -> str:
    return f"_kois_{key}"


QUESTIONS = [
    {"id": f"{qid}-{style}", "fact": qid, "style": style, "category": cat, "question": text,
     "answers": [_id(a) for a in answers], "related": [_id(r) for r in related],
     "evidence": [evidence] if isinstance(evidence, str) else evidence}
    for qid, cat, literal, paraphrase, answers, related, evidence in _QUESTIONS
    for style, text in (("literal", literal), ("paraphrase", paraphrase))
]


def _doc(owner: str, text: str) -> str:
    return (f"<ownedComment xmi:type='uml:Comment' xmi:id='{_id(owner)}_doc' body={quoteattr(text)}>"
            f"<annotatedElement xmi:idref='{_id(owner)}'/></ownedComment>")


def _diagram(key: str, name: str, kind: str, stream: str) -> str:
    return (f"<xmi:Extension extender='MagicDraw UML 2024x'><modelExtension>"
            f"<ownedDiagram xmi:type='uml:Diagram' xmi:id='{_id(key)}' name={quoteattr(name)}>"
            "<xmi:Extension extender='MagicDraw UML 2024x'><diagramRepresentation>"
            "<diagram:DiagramRepresentationObject xmlns:diagram='http://www.nomagic.com/ns/magicdraw/core/diagram/1.0' "
            f"type={quoteattr(kind)} umlType='Class Diagram'>"
            f"<diagramContents><binaryObject streamContentID='{stream}'/></diagramContents>"
            "</diagram:DiagramRepresentationObject></diagramRepresentation></xmi:Extension>"
            "</ownedDiagram></modelExtension></xmi:Extension>")


def model_xmi() -> str:
    blocks = []
    for key, name, doc, values in BLOCKS:
        attrs = [_doc(key, doc)]
        for vname, vtype, default in values:
            lit = "LiteralReal" if vtype == "Real" else "LiteralInteger"
            attrs.append(f"<ownedAttribute xmi:type='uml:Property' xmi:id='{_id(key)}_{vname}' name='{vname}'>"
                         f"<defaultValue xmi:type='uml:{lit}' xmi:id='{_id(key)}_{vname}_v' value='{default}'/>"
                         "</ownedAttribute>")
        if key == "kois":
            for part in PARTS:
                attrs.append(f"<ownedAttribute xmi:type='uml:Property' xmi:id='{_id('part_' + part)}' "
                             f"name={quoteattr({b[0]: b[1] for b in BLOCKS}[part].lower())} "
                             f"aggregation='composite' type='{_id(part)}' association='{_id('as_' + part)}'/>")
        blocks.append(f"<packagedElement xmi:type='uml:Class' xmi:id='{_id(key)}' name={quoteattr(name)}>"
                      + "".join(attrs) + "</packagedElement>")
    for part in PARTS:
        blocks.append(f"<packagedElement xmi:type='uml:Association' xmi:id='{_id('as_' + part)}'>"
                      f"<memberEnd xmi:idref='{_id('part_' + part)}'/><memberEnd xmi:idref='{_id('end_' + part)}'/>"
                      f"<ownedEnd xmi:type='uml:Property' xmi:id='{_id('end_' + part)}' type='{_id('kois')}' "
                      f"association='{_id('as_' + part)}'/></packagedElement>")
    reqs = [f"<packagedElement xmi:type='uml:Class' xmi:id='{_id(key)}' name={quoteattr(name)}/>"
            for key, _, name, _ in REQUIREMENTS]
    rels = [f"<packagedElement xmi:type='uml:Abstraction' xmi:id='{_id(f'sat_{b}_{r}')}' client='{_id(b)}' "
            f"supplier='{_id(r)}'/>" for b, r in SATISFY]
    rels += [f"<packagedElement xmi:type='uml:Abstraction' xmi:id='{_id(f'der_{d}_{s}')}' client='{_id(d)}' "
             f"supplier='{_id(s)}'/>" for d, s in DERIVE]
    acts = []
    for key, name, doc, nodes, edges in ACTIVITIES:
        parts = [_doc(key, doc)]
        parts += [f"<node xmi:type='uml:{kind}' xmi:id='{_id(n)}'" + (f" name={quoteattr(nm)}" if nm else "") + "/>"
                  for n, kind, nm in nodes]
        parts += [f"<edge xmi:type='uml:ControlFlow' xmi:id='{_id(f'e_{s}_{t}')}' source='{_id(s)}' target='{_id(t)}'"
                  + (f" name={quoteattr(nm)}" if nm else "") + "/>" for s, t, nm in edges]
        acts.append(f"<packagedElement xmi:type='uml:Activity' xmi:id='{_id(key)}' name={quoteattr(name)}>"
                    + "".join(parts) + "</packagedElement>")
    stereotypes = [f"<sysml:Block xmi:id='{_id(key)}_st' base_Class='{_id(key)}'/>" for key, *_ in BLOCKS]
    stereotypes += [f"<sysml:Requirement xmi:id='{_id(key)}_st' base_Class='{_id(key)}' Id={quoteattr(rid)} "
                    f"Text={quoteattr(text)}/>" for key, rid, _, text in REQUIREMENTS]
    stereotypes += [f"<sysml:Satisfy xmi:id='{_id(f'sat_{b}_{r}')}_st' base_Abstraction='{_id(f'sat_{b}_{r}')}'/>"
                    for b, r in SATISFY]
    stereotypes += [f"<sysml:DeriveReqt xmi:id='{_id(f'der_{d}_{s}')}_st' base_Abstraction='{_id(f'der_{d}_{s}')}'/>"
                    for d, s in DERIVE]
    return f"""<?xml version='1.0' encoding='UTF-8'?>
<xmi:XMI xmlns:xmi='http://www.omg.org/spec/XMI/20131001' xmlns:uml='http://www.omg.org/spec/UML/20131001'
  xmlns:sysml='http://www.omg.org/spec/SysML/20181001/SysML'>
 <xmi:Documentation><xmi:exporter>MagicDraw UML</xmi:exporter><xmi:exporterVersion>2024x</xmi:exporterVersion></xmi:Documentation>
 <uml:Model xmi:type='uml:Model' xmi:id='{_id("model")}' name={quoteattr(NAME)}>
  <packagedElement xmi:type='uml:Package' xmi:id='{_id("pkg_struct")}' name='KOIS Structure'>
   {"".join(blocks)}
   {_diagram("d_bdd", "KOIS Structure", "SysML Block Definition Diagram", "BINARY-bdd")}
  </packagedElement>
  <packagedElement xmi:type='uml:Package' xmi:id='{_id("pkg_req")}' name='KOIS Requirements'>
   {"".join(reqs)}{"".join(rels)}
   {_diagram("d_req", "KOIS Requirements", "Requirement Diagram", "BINARY-req")}
  </packagedElement>
  <packagedElement xmi:type='uml:Package' xmi:id='{_id("pkg_beh")}' name='KOIS Behavior'>
   {"".join(acts)}
   {_diagram("d_night", "Night Watering Cycle", "SysML Activity Diagram", "BINARY-night")}
  </packagedElement>
 </uml:Model>
 {"".join(stereotypes)}
</xmi:XMI>
"""


def _layout(shapes: list[tuple[str, str, str, tuple[int, int]]], paths: list[tuple[str, str, str, str]]) -> str:
    """Shapes: view id, class, element id, (column, row). Paths: class, element id, source view,
    target view. Cameo stores a path's target as its first end."""
    at = {}
    out = ["<?xml version='1.0' encoding='UTF-8' standalone='no'?>", "<mdOwnedViews>"]
    for vid, cls, el, (col, row) in shapes:
        x, y = 20 + col * 220, 20 + row * 120
        at[vid] = (x + 80, y + 30)
        out.append(f" <mdElement elementClass='{cls}' xmi:id='{vid}'><elementID xmi:idref='{el}'/>"
                   f"<geometry>{x}, {y}, 160, 60</geometry></mdElement>")
    for i, (cls, el, src, tgt) in enumerate(paths):
        (x1, y1), (x2, y2) = at[tgt], at[src]
        out.append(f" <mdElement elementClass='{cls}' xmi:id='p{i}'><elementID xmi:idref='{el}'/>"
                   f"<linkFirstEndID xmi:idref='{tgt}'/><linkSecondEndID xmi:idref='{src}'/>"
                   f"<geometry>{x1}, {y1}; {x2}, {y2}; </geometry></mdElement>")
    return "\n".join(out + ["</mdOwnedViews>", ""])


def layouts() -> dict[str, str]:
    bdd = _layout([("v_kois", "Class", _id("kois"), (3, 0))]
                  + [(f"v_{p}", "Class", _id(p), (i, 2)) for i, p in enumerate(PARTS)],
                  [("Association", _id("as_" + p), "v_kois", f"v_{p}") for p in PARTS])
    req = _layout([(f"v_{k}", "Class", _id(k), (i, 0)) for i, (k, *_) in enumerate(REQUIREMENTS)]
                  + [(f"v_{b}", "Class", _id(b), (i, 2)) for i, (b, _) in enumerate(SATISFY)],
                  [("Abstraction", _id(f"sat_{b}_{r}"), f"v_{b}", f"v_{r}") for b, r in SATISFY]
                  + [("Abstraction", _id(f"der_{d}_{s}"), f"v_{d}", f"v_{s}") for d, s in DERIVE])
    _, _, _, nodes, edges = ACTIVITIES[0]
    cls = {"InitialNode": "PseudoNode", "ActivityFinalNode": "PseudoNode", "DecisionNode": "Decision",
           "OpaqueAction": "OpaqueAction"}
    night = _layout([(f"v_{n}", cls[kind], _id(n), (i % 5, i // 5)) for i, (n, kind, _) in enumerate(nodes)],
                    [("ControlFlow", _id(f"e_{s}_{t}"), f"v_{s}", f"v_{t}") for s, t, _ in edges])
    return {"BINARY-bdd": bdd, "BINARY-req": req, "BINARY-night": night}


def make_mdzip() -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        def entry(name: str) -> zipfile.ZipInfo:  # fixed times: the same bytes, so the same project token
            return zipfile.ZipInfo(name, date_time=(2026, 1, 1, 0, 0, 0))
        z.writestr(entry("com.nomagic.magicdraw.uml_model.model"), model_xmi())
        for stream, text in layouts().items():
            z.writestr(entry(stream), text)
        z.writestr(entry("Records.properties"), "#Compatibility entry\n")
    return buf.getvalue()
