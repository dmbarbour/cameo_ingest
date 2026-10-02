"""Kestrel Orchard Irrigation System (KOIS): the first fictional project, with planted facts (plan
RE, decision 9), rebuilt with the builder (AR-021).

Every name and figure is invented ("Brine Valve K7", 340 milliseconds), so that each question has
one right answer even in an index of every sample. Its keys are those of the hand-written
original, so that its element ids (`_kois_k7`) are too.
"""

from __future__ import annotations

from .builder import Project

# Blocks: key, name, documentation, value properties (name, default).
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
     [("closeTime", 340)]),
    ("dos", "Nutrient Doser",
     "The Nutrient Doser meters the Verdant-3 nutrient blend into the irrigation water.", []),
    ("frs", "Frost Shield",
     ("The Frost Shield sprays a fine warm mist over the blossoms when the air temperature falls below 1.5 degrees "
      "Celsius."), []),
    ("rba", "Rain Barrel Array",
     "The Rain Barrel Array stores roof runoff from the packing shed in linked polyethylene tanks.",
     [("capacityLitres", 12000)]),
    ("pmp", "Pump Station",
     "The Pump Station houses two pumps, named Otter and Heron, which alternate nightly to share the wear.", []),
]
PARTS = ["ctl", "lat", "k7", "dos", "frs", "rba", "pmp"]  # composed into the system block

# Requirements: key, requirement id, name, text.
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


def build() -> Project:
    p = Project("Kestrel Orchard Irrigation", "kois")
    st = p.package("pkg_struct", "KOIS Structure")
    rq = p.package("pkg_req", "KOIS Requirements")
    bh = p.package("pkg_beh", "KOIS Behavior")

    names = {key: name for key, name, _, _ in BLOCKS}
    for key, name, doc, values in BLOCKS[1:]:
        p.block(key, name, st, doc, values=[(v, None, default) for v, default in values])
    key, name, doc, _ = BLOCKS[0]
    p.block(key, name, st, doc, parts=[(names[k].lower(), k) for k in PARTS])

    for key, rid, name, text in REQUIREMENTS:
        p.requirement(key, rid, name, text, rq)
    for block, req in SATISFY:
        p.relate("satisfy", block, req, rq)
    p.relate("deriveReqt", "r2", "r5", rq)  # the valve's closing time is derived from the leak shutdown

    p.activity("night", "Night Watering Cycle", bh, "The Night Watering Cycle runs every night at 02:00, when "
               "evaporation is lowest.", [
                   ("n0", "InitialNode", ""), ("n1", "OpaqueAction", "Read Moisture Lattice"),
                   ("n2", "OpaqueAction", "Check Frost Forecast"), ("n3", "DecisionNode", ""),
                   ("n4", "OpaqueAction", "Run Frost Shield"), ("n5", "OpaqueAction", "Open Row Valves"),
                   ("n6", "OpaqueAction", "Dose Nutrients"), ("n7", "OpaqueAction", "Close Row Valves"),
                   ("n8", "ActivityFinalNode", "")],
               [("n0", "n1"), ("n1", "n2"), ("n2", "n3"), ("n3", "n4", "frost expected"), ("n3", "n5", "no frost"),
                ("n4", "n5"), ("n5", "n6"), ("n6", "n7"), ("n7", "n8")])
    p.activity("leak", "Leak Response", bh, "The Leak Response runs whenever the mains pressure drops suddenly.", [
        ("m0", "InitialNode", ""), ("m1", "OpaqueAction", "Detect Pressure Drop"),
        ("m2", "OpaqueAction", "Close Brine Valve K7"), ("m3", "OpaqueAction", "Text the Grower"),
        ("m4", "ActivityFinalNode", "")],
        [("m0", "m1"), ("m1", "m2"), ("m2", "m3"), ("m3", "m4")])

    p.diagram("d_bdd", "KOIS Structure", "SysML Block Definition Diagram", st, ["kois", *PARTS], cols=7)
    p.diagram("d_req", "KOIS Requirements", "Requirement Diagram", rq,
              [k for k, *_ in REQUIREMENTS] + [b for b, _ in SATISFY], cols=7)
    p.behavior_diagram("d_night", "Night Watering Cycle", "night", cols=5)

    p.ask("q01", "lookup", "easy", "What is the Moisture Lattice made of?",
          "How is the wetness of the soil sensed across the orchard?", ["lat"], ["r1"], evidence="48 capacitive probes")
    p.ask("q02", "parameter", "easy", "How quickly must Brine Valve K7 close after a leak signal?",
          "How fast does the master shut-off valve have to shut when water escapes?", ["r2"], ["k7", "r5"],
          evidence="340 milliseconds")
    p.ask("q03", "lookup", "easy", "Which board does the KOIS Controller run on?",
          "What hardware does the irrigation scheduler run on?", ["ctl"], evidence="Lumen-9")
    p.ask("q04", "lookup", "easy", "Which nutrient blend does the Nutrient Doser meter?",
          "Which fertilizer mix is added to the irrigation water?", ["dos"], ["r4"], evidence="Verdant-3")
    p.ask("q05", "parameter", "easy", "At what temperature does the Frost Shield start spraying?",
          "When do the trees start getting warmed on cold nights?", ["frs"], ["r3"], evidence="1.5 degrees")
    p.ask("q06", "parameter", "easy", "How many litres does the Rain Barrel Array hold?",
          "How much harvested rain can the orchard keep in reserve?", ["rba"], ["r6"], evidence="12000")
    p.ask("q07", "lookup", "easy", "What are the pumps in the Pump Station called?",
          "What names were given to the two water pumps?", ["pmp"], evidence="Otter and Heron")
    p.ask("q08", "trace", "medium", "Which requirement is KOIS-R2 derived from?",
          "Which broader safety need does the valve's closing time come from?", ["r5", "r2"],
          evidence={"r2": "is derived from Leak Shutdown",
                    "r5": ["Valve Closing Time (KOIS-R2) is derived from this", "Valve Closing Time is derived from this"]})
    p.ask("q09", "trace", "medium", "Which block satisfies KOIS-R3, Frost Protection?",
          "Which component is responsible for keeping blossoms from freezing?", ["frs", "r3"],
          evidence={"frs": "satisfies Frost Protection", "r3": "Frost Shield satisfies this"})
    p.ask("q10", "parameter", "easy", "What soil moisture range must KOIS keep in every orchard row?",
          "How damp should the ground under the apple trees be kept?", ["r1"], ["lat"], evidence="between 18% and 26%")
    p.ask("q11", "parameter", "easy", "How long must the KOIS Controller keep its watering cycle log?",
          "For how many years is the history of each night's watering kept?", ["r7"], ["ctl"], evidence="for 3 years")
    p.ask("q12", "behaviour", "medium", "In the Night Watering Cycle, what follows Dose Nutrients?",
          "What is the last step before the nightly watering finishes?", ["night"], ["d_night"],
          evidence="Close Row Valves")
    p.ask("q13", "behaviour", "medium", "What happens in the Leak Response after a pressure drop is detected?",
          "How does the system react when the pipes lose pressure suddenly?", ["leak"], ["k7", "r5"],
          evidence="Close Brine Valve K7")
    p.ask("q14", "structure", "medium", "What parts make up the Kestrel Orchard Irrigation System?",
          "What are the main components of the orchard watering system?", ["kois"], ["d_bdd"],
          evidence="pump station : Pump Station")  # the part, not the block's own name
    return p
