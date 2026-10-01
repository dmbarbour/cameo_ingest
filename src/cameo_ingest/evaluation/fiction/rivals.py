"""Two rival proposals for the Riverbend works (plan RF, RF-04), beside the first one (`water`).

Every name and figure is invented. The maintainer evaluates models from several companies bidding
for one contract, each answering the same customer requirements in its own way, with no common
structure, and often under the same file name. So:
- **Halvorsen Engineering** copies some customer requirements, with the customer's ids in their
  Id tags, derives its own from them, and cites others only in documentation and tagged values;
- **Aquila Process Solutions** writes DOORS-style requirements of its own, which cite the customer's
  ids in their text;
- all three files are called `Riverbend_Water_Treatment_Works.mdzip`, told apart by folder only.

`across()` asks questions whose answer is spread over the three models ("which proposals address
RWT-REG-002, and how?"): each has evidence groups, one per model, all of which a full answer
needs.
"""

from __future__ import annotations

from .builder import Project

FILE = "Riverbend_Water_Treatment_Works.mdzip"


def halvorsen() -> Project:
    p = Project("Riverbend WTW Proposal - Halvorsen Engineering", "hal", FILE, folder="halvorsen")
    p.profile("HAL", "Halvorsen Profile", {"Compliance": ["meets", "evidence"]})
    cust = p.package("cust", "A Customer Requirements", doc="Copied from the Riverbend tender, schedule 4.")
    own = p.package("own", "B Halvorsen Requirements")
    des = p.package("des", "C Halvorsen Design", doc="Membrane filtration and ozone, in place of media filters and UV.")
    ops = p.package("ops", "D Operations")
    p.requirement("c001", "RWT-REG-001", "Treated Water Turbidity",
                  "Treated water turbidity shall stay below 0.3 NTU in 95% of monthly samples.", cust)
    p.requirement("c002", "RWT-REG-002", "Virus Inactivation",
                  "At least 4-log inactivation of viruses at a water temperature of 2 degrees Celsius.", cust)
    p.requirement("c007", "RWT-REG-007", "Spent Washwater Return",
                  "Spent washwater shall be returned at no more than 10% of the raw water flow.", cust)
    p.requirement("cprf01", "RWT-PRF-01", "Design Capacity", "Up to 55 megalitres per day.", cust)
    p.requirement("h010", "HAL-SYS-010", "Ozone CT",
                  "The ozone contactor shall hold a CT of at least 1.2 mg.min/L at 2 degrees Celsius.", own)
    p.requirement("h020", "HAL-SYS-020", "Membrane Integrity",
                  "Each membrane train shall pass a pressure decay test daily, losing under 0.3 kPa per minute.", own)
    p.relate("deriveReqt", "h010", "c002", own)
    p.relate("deriveReqt", "h020", "c001", own)

    p.block("daf", "Dissolved Air Flotation Unit", des,
            "Floats algae and floc to the surface with micro-bubbles, in place of settling, at 25 m/h.")
    p.block("mf", "Membrane Filtration Rack", des,
            ("Eight ultrafiltration trains, MF-1 to MF-8, of 0.02 micrometre hollow fibres from Pellucid "
             "Membranes."))
    p.apply("HAL", "Compliance", "mf", meets="RWT-REG-001, RWT-REG-004", evidence="pilot trial report HE-PT-07")
    p.block("oz", "Ozone Contactor", des,
            ("A three-cell contactor that provides the 4-log virus inactivation required by RWT-REG-002, with "
             "6 minutes of contact time at design flow."))
    p.block("cl", "Chlorine Dosing Skid", des,
            ("Doses sodium hypochlorite after the reservoir to hold a free chlorine residual of 0.6 mg/L in "
             "distribution, to meet RWT-REG-003."))
    p.block("res", "Treated Water Reservoir", des,
            ("Two cells holding 5,200 cubic metres in all, sized for RWT-PRF-03 with a margin for membrane "
             "cleaning water."))
    p.block("lagoon", "Washwater Recovery Lagoon", des,
            "Settles membrane backwash, and returns it at no more than 6% of raw flow, below the 10% allowed.")
    p.block("ctl", "Halvorsen Plant Controller", des, "A redundant pair of Corvane C-12 controllers.")
    p.block("works", "Riverbend Works (Halvorsen)", des, "The works as Halvorsen proposes to build it.",
            parts=[("flotation", "daf"), ("membranes", "mf"), ("ozone", "oz"), ("dosing", "cl"),
                   ("reservoir", "res"), ("lagoon", "lagoon"), ("controller", "ctl")])
    for source, target in (("mf", "c001"), ("oz", "h010"), ("lagoon", "c007"), ("works", "cprf01"),
                           ("mf", "h020")):
        p.relate("satisfy", source, target, des)
    p.activity("mit", "Membrane Integrity Test", ops, "Run on each train every morning before 06:00.", [
        ("i0", "InitialNode", ""), ("i1", "OpaqueAction", "Pressurise Fibres to 100 kPa"),
        ("i2", "OpaqueAction", "Hold for 10 Minutes"), ("i3", "OpaqueAction", "Measure Pressure Decay"),
        ("i4", "ActivityFinalNode", "")], [("i0", "i1"), ("i1", "i2"), ("i2", "i3"), ("i3", "i4")], test_case=True)
    p.relate("verify", "mit", "h020", ops)
    p.diagram("d_des", "Halvorsen Design", "SysML Block Definition Diagram", des,
              ["works", "daf", "mf", "oz", "cl", "res", "lagoon", "ctl"])
    p.diagram("d_req", "Halvorsen Requirements", "Requirement Diagram", own,
              ["c001", "c002", "c007", "cprf01", "h010", "h020", "mf", "oz", "lagoon", "works"])
    p.behavior_diagram("d_mit", "Membrane Integrity Test", "mit")

    p.ask("q01", "lookup", "medium", "What does the Halvorsen Ozone Contactor provide?",
          "What does the ozone stage in the Halvorsen bid do?", ["oz"], evidence="4-log virus inactivation")
    p.ask("q02", "parameter", "medium", "What chlorine residual does the Halvorsen Chlorine Dosing Skid hold?",
          "How much chlorine does Halvorsen leave in the water going to town?", ["cl"], evidence="0.6 mg/L")
    p.ask("q03", "lookup", "medium", "Whose membranes does the Halvorsen Membrane Filtration Rack use?",
          "Which supplier makes the hollow fibres in Halvorsen's filters?", ["mf"], evidence="Pellucid Membranes")
    p.ask("q04", "behaviour", "medium", "How is membrane integrity tested in the Halvorsen design?",
          "How does Halvorsen check its filters for leaks?", ["mit", "h020"],
          evidence=["Measure Pressure Decay", "pressure decay test daily"])
    p.ask("q05", "tagged-value", "hard", "Which pilot trial report backs the Halvorsen membrane compliance claim?",
          "What evidence does Halvorsen offer that its membranes will meet the turbidity limits?", ["mf"],
          evidence="HE-PT-07")
    return p


def aquila() -> Project:
    p = Project("Riverbend Proposal - Aquila Process Solutions", "aqu", FILE, folder="aquila")
    req = p.package("req", "Aquila Requirements", doc="System requirements, module AQ-SR, imported from DOORS.")
    des = p.package("des", "Aquila Design")
    for key, rid, text in (
            ("sr12", "AQ-SR-12", ("Per RWT-REG-003, the distribution residual shall be held at 0.9 mg/L by a trim "
                                 "dose at the high-lift pumps.")),
            ("sr14", "AQ-SR-14", ("To meet RWT-PRF-03, the clearwell shall be built as a single 3,900 cubic metre "
                                 "tank.")),
            ("sr15", "AQ-SR-15", ("To meet RWT-REG-002, two UV trains from Sollux shall each deliver 40 mJ/cm2, "
                                 "followed by chlorination.")),
            ("sr20", "AQ-SR-20", ("Per RWT-REG-007, washwater shall be returned at 8% of raw flow, through a "
                                 "lamella thickener."))):
        p.requirement(key, str(7000 + int(rid[-2:])), None, f"[{rid}] {text}", req)
    p.block("uv", "Sollux UV Train", des, "One of two medium-pressure UV trains.")
    p.block("cw", "Aquila Clearwell", des, "A single rectangular tank, buried, with a grass roof.")
    p.block("trim", "Trim Dosing Station", des, "Adds hypochlorite at the high-lift pumps.")
    p.block("thick", "Lamella Thickener", des, "Thickens washwater solids before the water is returned.")
    for source, target in (("uv", "sr15"), ("cw", "sr14"), ("trim", "sr12"), ("thick", "sr20")):
        p.relate("satisfy", source, target, des)
    p.diagram("d_req", "Aquila Requirements", "Requirement Diagram", req,
              ["sr12", "sr14", "sr15", "sr20", "uv", "cw", "trim", "thick"])

    p.ask("q01", "parameter", "medium", "What distribution residual does Aquila hold under AQ-SR-12?",
          "How much chlorine does Aquila keep in the water at the pumps?", ["sr12"], ["trim"], evidence="0.9 mg/L")
    p.ask("q02", "lookup", "medium", "Whose UV trains does Aquila propose?",
          "Which make of ultraviolet units is in Aquila's bid?", ["sr15"], ["uv"], evidence="from Sollux")
    return p


def across() -> list[dict]:
    """Questions whose answer is spread over the three Riverbend proposals: one evidence group per
    proposal, each a phrase (or alternatives) that its part of the answer holds, in the model's own
    chunks or in an index entry gathering them. The phrases occur nowhere else."""
    first = "the first proposal"
    rows = [
        ("x01", "Which proposals address requirement RWT-REG-002, and how?",
         "How does each bidder for the Riverbend works achieve the required virus kill?",
         [["Chlorine Contact Tank satisfies this", "satisfies RWT-REG-002", "Block Chlorine Contact Tank, satisfies it"],
          ["required by RWT-REG-002"], ["To meet RWT-REG-002, two UV trains"]]),
        ("x02", "Which proposals address requirement RWT-REG-003, the chlorine residual entering distribution?",
         "How much chlorine does each Riverbend bid leave in the water sent to town?",
         [["Distribution Entry Chlorine Analyzer satisfies this", "satisfies RWT-REG-003",
           "Block Distribution Entry Chlorine Analyzer, satisfies it"],
          ["to meet RWT-REG-003"], ["Per RWT-REG-003"]]),
        ("x03", "How much treated water storage does each proposal provide for RWT-PRF-03?",
         "How big is the treated water tank in each Riverbend bid?",
         [["4,500 cubic metres"], ["5,200 cubic metres"], ["3,900 cubic metre"]]),
        ("x04", "At what share of raw flow does each proposal return spent washwater, under RWT-REG-007?",
         "How much dirty wash water does each Riverbend bid recycle to the head of the works?",
         [["at no more than 10% of the raw flow"], ["no more than 6% of raw flow"], ["returned at 8% of raw flow"]]),
        ("x05", "Which proposals address requirement RWT-REG-001, the treated water turbidity?",
         "How does each Riverbend bid keep the treated water clear?",
         [["Dual Media Filter satisfies this", "satisfies RWT-REG-001", "Block Dual Media Filter, satisfies it"],
          ["Membrane Filtration Rack satisfies this", "Membrane Filtration Rack, satisfies it",
           "Membrane Filtration Rack, in its tag meets"]]),
    ]
    out = []
    for qid, literal, paraphrase, groups in rows:
        for style, text in (("literal", literal), ("paraphrase", paraphrase)):
            out.append({"id": f"across-{qid}-{style}", "fact": f"across-{qid}", "style": style,
                        "category": "cross-model", "difficulty": "hard", "question": text, "answers": [],
                        "related": [], "evidence": [], "evidence_groups": groups,
                        "project_name": "Riverbend proposals", "note": f"groups: {first}, Halvorsen, Aquila"})
    return out


def within() -> list[dict]:
    """Questions whose answer is spread over several elements of one model, along its derivation
    relationships: what derives from a requirement, and what satisfies or verifies that. One
    evidence group per part of the answer; a thread (plan RF-05) holds them all."""
    rows = [
        ("w01", "Which tests verify the requirements derived from SN-02, Stop Road Users?",
         "How is it checked that the level crossings really stop road users?",
         [["Warning Time Test"], ["Second Train Test"], ["Trapped Vehicle Test"]], "Ferrous Valley Level Crossing"),
        ("w02", "Which requirements derive from RWT-REG-002 in the first Riverbend proposal, and what satisfies them?",
         "What follows from the virus kill requirement in the first Riverbend design, and which equipment meets it?",
         [["UV Dose"], ["UV Reactor"]], "Riverbend Water Treatment Works"),
        ("w03", "What derives from RWT-REG-001 in Halvorsen's model, and how is it verified?",
         "How does Halvorsen turn the turbidity limit into a check it runs?",
         [["HAL-SYS-020"], ["Membrane Integrity Test"]], "Riverbend WTW Proposal - Halvorsen Engineering"),
        ("w04", "Which requirements derive from FVX-SYS-003, Barriers, and what satisfies FVX-SYS-003?",
         "What more detailed requirements come from the level crossing barriers, and what provides the barriers?",
         [["FVX-SUB-031"], ["FVX-SUB-032"], ["Barrier Machine"]], "Ferrous Valley Level Crossing"),
    ]
    out = []
    for qid, literal, paraphrase, groups, project in rows:
        for style, text in (("literal", literal), ("paraphrase", paraphrase)):
            out.append({"id": f"within-{qid}-{style}", "fact": f"within-{qid}", "style": style,
                        "category": "multi-fact", "difficulty": "hard", "question": text, "answers": [],
                        "related": [], "evidence": [], "evidence_groups": groups, "project_name": project})
    return out
