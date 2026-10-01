"""Riverbend Water Treatment Works: a medium project (about 800 XMI ids), questions from easy
to hard.

Every name and figure is invented. Besides documentation and requirement text, facts sit in:
- tagged values of a custom profile (an instrument's alarm limit, a tank's delivery interval);
- near-duplicates: six filter effluent turbidimeters and a combined one, with different limits;
- requirements imported from DOORS (unnamed, their id in their text);
- instances: operating modes and the filter register, whose values differ by a figure or two;
- a state machine's guards, an activity's guards, a constraint block, allocations to PLCs.
"""

from __future__ import annotations

from .builder import Project

FILTERS = [  # name, commissioned, anthracite depth (mm), sand depth (mm), area (m²), note
    ("F1", 1998, 600, 300, 42, None), ("F2", 1998, 600, 300, 42, None), ("F3", 2004, 600, 300, 42, None),
    ("F4", 2004, 900, 250, 42, "Rebuilt in 2019 after media loss, with deeper anthracite."),
    ("F5", 2011, 600, 300, 48, None), ("F6", 2011, 600, 300, 48, None),
]
MODES = [  # name, alum, polymer, chlorine (mg/L), flow (ML/d), filters in service, doc
    ("Summer Mode", 28, 0.15, 1.8, 48, 6, "Warm, low-turbidity river water from June to September."),
    ("Winter Mode", 42, 0.25, 1.2, 32, 5, "Cold water slows coagulation; one filter is rested for maintenance."),
    ("Storm Mode", 65, 0.4, 2.2, 30, 6, "Raw water turbidity above 250 NTU after heavy rain on the upper catchment."),
]


def build() -> Project:
    p = Project("Riverbend Water Treatment Works", "rwt")
    p.profile("RWT", "Riverbend Profile", {
        "Instrument": ["tagNumber", "range", "alarmHigh", "alarmLow", "vendor"],
        "ChemicalTank": ["chemical", "capacity", "deliveryFrequency", "bundVolume"],
        "Equipment": ["tagNumber", "dutyStandby", "vendor"],
    })
    ctx = p.package("ctx", "00 Context", doc="The works as a whole, and the river it draws from.")
    req = p.package("req", "01 Requirements")
    reg = p.package("reg", "Regulatory", req, doc="Imported from the DOORS module RWT-REG, baseline 7.")
    prf = p.package("prf", "Performance", req)
    saf = p.package("saf", "Safety", req)
    proc = p.package("proc", "02 Process Train", doc="Unit processes, in the order the water passes through them.")
    chem = p.package("chem", "03 Chemicals")
    inst = p.package("inst", "04 Instrumentation")
    ctl = p.package("ctl", "05 Control System")
    beh = p.package("beh", "06 Behavior")
    modes = p.package("modes", "07 Operating Modes",
                      doc="Seasonal settings, chosen by the shift supervisor from the SCADA mode page.")
    reg_f = p.package("filters_reg", "08 Filter Register", doc="One entry per filter, as built and as rebuilt.")
    ver = p.package("ver", "09 Verification")

    # Value types.
    vt = {}
    for key, name, unit in (("mgl", "milligrams per litre", "mg/L"), ("ntu", "nephelometric turbidity units", "NTU"),
                            ("mld", "megalitres per day", "ML/d"), ("m3", "cubic metres", "m³"),
                            ("mm", "millimetres", "mm"), ("m", "metres", "m"), ("h", "hours", "h"),
                            ("min", "minutes", "min"), ("m2", "square metres", "m²"),
                            ("mjcm2", "millijoules per square centimetre", "mJ/cm²"), ("yr", "years", "year")):
        vt[key] = p.value_type(f"vt_{key}", name, ctx, unit=unit)

    # -- process train ---------------------------------------------------------------------------
    p.block("water", "Water", proc, "Water at any stage of treatment.")
    p.block("sludge", "Sludge", proc, "Settled solids drawn off the lamella settlers.")
    p.block("llpump", "Low-Lift Pump", proc, "A vertical turbine pump rated at 230 litres per second.",
            values=[("ratedFlow", None, "230 L/s")])
    p.block("intake", "Intake", proc,
            ("The Intake draws raw water from the Tamsin River at Hollow Ford, through band screens with 6 mm "
             "openings, into the Low-Lift Pump Station."),
            ports=[("raw out", None)])
    p.block("llps", "Low-Lift Pump Station", proc,
            "Lifts screened river water 14 metres to the rapid mix chamber. Two pumps run, one stands by.",
            parts=[("LL-1", "llpump"), ("LL-2", "llpump"), ("LL-3", "llpump")],
            ports=[("raw in", None), ("raw out", None)])
    p.block("rapidmix", "Rapid Mix Chamber", proc,
            "A 30-second flash mixer where alum and polymer are dosed into the raw water.",
            ports=[("raw in", None), ("dosed out", None)])
    p.block("floc", "Flocculation Basins", proc,
            ("Three basins in series, with paddles slowing from 6 to 4 to 2 revolutions per minute, so that floc "
             "grows without breaking."),
            ports=[("dosed in", None), ("floc out", None)])
    p.block("lamella", "Lamella Settlers", proc,
            ("Inclined-plate settlers with plates at 55 degrees. Sludge is drawn off by scrapers every "
             "40 minutes."),
            values=[("plateAngle", None, "55 degrees"), ("desludgeInterval", vt["min"], 40)],
            ports=[("floc in", None), ("settled out", None), ("sludge out", None)])
    p.block("filter", "Dual Media Filter", proc,
            ("A gravity filter with anthracite over sand. The works has six, F1 to F6; see the Filter Register "
             "for each one's media."),
            values=[("headLossLimit", vt["m"], 2.4), ("maxRunTime", vt["h"], 72),
                    ("turbidityLimit", vt["ntu"], 0.15), ("commissioned", None, None),
                    ("anthraciteDepth", vt["mm"], None), ("sandDepth", vt["mm"], None), ("area", vt["m2"], None)],
            ports=[("settled in", None), ("filtered out", None), ("washwater out", None)])
    p.block("backwash", "Backwash System", proc,
            ("Cleans one filter at a time. Backwash pump BW-1 is duty and BW-2 standby; air scour blower AS-1 "
             "lifts the media before the water wash."),
            values=[("airScourRate", None, "55 m3/m2/h")])
    p.block("uv", "UV Reactor", proc,
            "One of two Lumora UV-600 reactors treating filtered water before chlorination.",
            values=[("lamps", None, 24)], ports=[("filtered in", None), ("uv out", None)])
    p.block("cct", "Chlorine Contact Tank", proc,
            ("A serpentine tank that holds chlorinated water long enough to disinfect it. Baffles give it a "
             "baffling factor of 0.7."),
            values=[("volume", vt["m3"], 1800), ("bafflingFactor", None, 0.7)],
            ports=[("uv in", None), ("treated out", None)])
    p.block("clearwell", "Clearwell", proc,
            "Covered storage that holds 4,500 cubic metres of treated water ahead of the high-lift pumps.",
            values=[("volume", vt["m3"], 4500)], ports=[("treated in", None), ("treated out", None)])
    p.block("hlpump", "High-Lift Pump", proc, "A split-case pump rated at 190 litres per second at 62 m head.")
    p.block("hlps", "High-Lift Pump Station", proc,
            "Pumps treated water into the Riverbend trunk main. Three duty pumps and one standby.",
            parts=[("HL-1", "hlpump"), ("HL-2", "hlpump"), ("HL-3", "hlpump"), ("HL-4", "hlpump")],
            ports=[("treated in", None)])
    p.block("thickener", "Sludge Thickener", proc,
            "A picket-fence thickener that concentrates settler sludge to 4% solids before it is tankered away.",
            ports=[("sludge in", None)])
    p.block("wrt", "Washwater Recovery Tank", proc,
            ("Holds spent backwash water so that it can settle and be returned to the head of the works, slowly, "
             "at no more than 10% of the raw flow."), ports=[("washwater in", None)])
    p.block("works", "Riverbend Water Treatment Works", ctx,
            ("The Riverbend Water Treatment Works supplies the town of Riverbend and four villages from the Tamsin "
             "River, treating up to 55 megalitres a day."),
            values=[("capacity", vt["mld"], 55)],
            parts=[("intake", "intake"), ("low lift", "llps"), ("rapid mix", "rapidmix"), ("flocculation", "floc"),
                   ("settlers", "lamella"), ("filters", "filter", "6..6"), ("backwash", "backwash"),
                   ("uv", "uv", "2..2"), ("contact tank", "cct"), ("clearwell", "clearwell"),
                   ("high lift", "hlps"), ("thickener", "thickener"), ("recovery", "wrt")])
    for a, b, item in (("intake", "low lift", "water"), ("low lift", "rapid mix", "water"),
                       ("rapid mix", "flocculation", "water"), ("flocculation", "settlers", "water"),
                       ("settlers", "filters", "water"), ("filters", "uv", "water"),
                       ("uv", "contact tank", "water"), ("contact tank", "clearwell", "water"),
                       ("clearwell", "high lift", "water"), ("settlers", "thickener", "sludge"),
                       ("filters", "recovery", "water")):
        ports = {("intake", "low lift"): ("raw out", "raw in"), ("low lift", "rapid mix"): ("raw out", "raw in"),
                 ("rapid mix", "flocculation"): ("dosed out", "dosed in"),
                 ("flocculation", "settlers"): ("floc out", "floc in"),
                 ("settlers", "filters"): ("settled out", "settled in"),
                 ("filters", "uv"): ("filtered out", "filtered in"), ("uv", "contact tank"): ("uv out", "uv in"),
                 ("contact tank", "clearwell"): ("treated out", "treated in"),
                 ("clearwell", "high lift"): ("treated out", "treated in"),
                 ("settlers", "thickener"): ("sludge out", "sludge in"),
                 ("filters", "recovery"): ("washwater out", "washwater in")}[(a, b)]
        p.connector("works", None, (a, ports[0]), (b, ports[1]), items=[item])

    # -- chemicals -------------------------------------------------------------------------------
    for key, name, doc, chemical, capacity, delivery, bund in (
            ("alum", "Alum Feed System", "Doses liquid aluminium sulfate (48%) into the rapid mix chamber.",
             "aluminium sulfate 48%", "60 m3", "every 14 days", "66 m3"),
            ("poly", "Polymer Feed System", "Doses the cationic polymer Floctra C-21 as a coagulant aid.",
             "Floctra C-21", "8 m3", "every 30 days", "9 m3"),
            ("hypo", "Hypochlorite Store", "Stores and doses sodium hypochlorite (12.5%) for disinfection.",
             "sodium hypochlorite 12.5%", "40 m3", "every 9 days", "44 m3"),
            ("fluor", "Fluoride Feed System", "Doses fluorosilicic acid to hold fluoride at 0.7 mg/L.",
             "fluorosilicic acid", "12 m3", "every 45 days", "13 m3"),
            ("lime", "Lime Feed System", "Doses hydrated lime slurry to bring treated water to pH 7.6.",
             "hydrated lime", "25 t silo", "every 21 days", None)):
        p.block(key, name, chem, doc)
        p.apply("RWT", "ChemicalTank", key, chemical=chemical, capacity=capacity, deliveryFrequency=delivery,
                bundVolume=bund)

    # -- instrumentation -------------------------------------------------------------------------
    instruments = [  # key, name, doc, tag, range, high, low, vendor
        ("ait101", "Raw Water Turbidimeter", "Measures the turbidity of the river water at the intake.",
         "AIT-101", "0-1000 NTU", "250 NTU", None, "Calder Optics"),
        ("ait201", "Settled Water Turbidimeter", "Measures turbidity leaving the lamella settlers.",
         "AIT-201", "0-100 NTU", "2.0 NTU", None, "Calder Optics"),
        ("ait310", "Combined Filter Effluent Turbidimeter", "Measures the blended outlet of all six filters.",
         "AIT-310", "0-10 NTU", "0.3 NTU", None, "Calder Optics"),
        ("ait401", "Post-Contact Chlorine Analyzer",
         "Measures free chlorine at the outlet of the Chlorine Contact Tank; the dosing loop holds 0.8 to 1.6 mg/L.",
         "AIT-401", "0-5 mg/L", "2.5 mg/L", "0.8 mg/L", "Wexley Instruments"),
        ("ait402", "Distribution Entry Chlorine Analyzer",
         "Measures free chlorine where treated water leaves for the trunk main.",
         "AIT-402", "0-5 mg/L", "2.0 mg/L", "0.5 mg/L", "Wexley Instruments"),
        ("ait501", "Treated Water pH Analyzer", "Measures pH after lime dosing.",
         "AIT-501", "0-14 pH", "8.5 pH", "7.0 pH", "Wexley Instruments"),
        ("fit101", "Raw Water Flow Meter", "An electromagnetic flow meter on the low-lift rising main.",
         "FIT-101", "0-800 L/s", None, None, "Halloran Flow"),
        ("fit601", "Treated Water Flow Meter", "An electromagnetic flow meter on the trunk main.",
         "FIT-601", "0-800 L/s", None, None, "Halloran Flow"),
        ("lit701", "Clearwell Level Transmitter", "A radar level transmitter over the clearwell.",
         "LIT-701", "0-6 m", "5.6 m", "1.2 m", "Halloran Flow"),
    ]
    for i in range(1, 7):
        instruments.append((f"ait30{i}", f"Filter F{i} Effluent Turbidimeter",
                            f"Measures the turbidity of filtered water leaving filter F{i}.",
                            f"AIT-30{i}", "0-10 NTU", "0.15 NTU", None, "Calder Optics"))
    for key, name, doc, tag, rng, high, low, vendor in instruments:
        p.block(key, name, inst, doc)
        p.apply("RWT", "Instrument", key, tagNumber=tag, range=rng, alarmHigh=high, alarmLow=low, vendor=vendor)

    # -- control system --------------------------------------------------------------------------
    p.block("scada", "RiverWatch SCADA", ctl,
            "The supervisory system: two redundant servers, the operator stations in the control room, and the "
            "mode page from which the shift supervisor selects the operating mode.")
    p.block("historian", "RiverWatch Historian", ctl,
            "Stores every measurement at one-minute resolution, and keeps it for 7 years.",
            values=[("retention", vt["yr"], 7)])
    plcs = [("plc100", "PLC-100 Intake"), ("plc200", "PLC-200 Clarification"), ("plc300", "PLC-300 Filtration"),
            ("plc400", "PLC-400 Disinfection"), ("plc500", "PLC-500 Pumping")]
    for key, name in plcs:
        p.block(key, name, ctl, f"A {name.split()[1].lower()} area controller, a Strand S-9 PLC on the plant ring.")
    for source, plc in (("ait101", "plc100"), ("fit101", "plc100"), ("ait201", "plc200"), ("ait310", "plc300"),
                        ("ait301", "plc300"), ("ait302", "plc300"), ("ait303", "plc300"), ("ait304", "plc300"),
                        ("ait305", "plc300"), ("ait306", "plc300"), ("ait401", "plc400"), ("ait402", "plc500"),
                        ("ait501", "plc500"), ("fit601", "plc500"), ("lit701", "plc500")):
        p.relate("allocate", source, plc, ctl)

    # -- requirements ----------------------------------------------------------------------------
    regs = [
        ("reg001", "RWT-REG-001", ("The turbidity of treated water shall not exceed 0.3 NTU in 95% of the samples "
                                  "taken each month, and shall never exceed 1 NTU.")),
        ("reg002", "RWT-REG-002", ("The works shall achieve at least 4-log inactivation of viruses, demonstrated by "
                                  "CT, at the coldest expected water temperature of 2 degrees Celsius.")),
        ("reg003", "RWT-REG-003", ("The free chlorine residual of water entering distribution shall be no less than "
                                  "0.5 mg/L.")),
        ("reg004", "RWT-REG-004", "The effluent turbidity of each filter shall be recorded every 15 minutes."),
        ("reg005", "RWT-REG-005", ("Fluoride in treated water shall be held at 0.7 mg/L and shall never exceed "
                                  "1.5 mg/L.")),
        ("reg006", "RWT-REG-006", "Records of treatment performance shall be kept for 7 years."),
        ("reg007", "RWT-REG-007", ("Spent backwash water shall not be returned to the head of the works at more than "
                                  "10% of the raw water flow.")),
    ]
    for key, rid, text in regs:  # as imported from DOORS: no name, the id in the text, a database number as Id
        p.requirement(key, str(16000 + int(rid[-3:])), None, f"[{rid}] {text}", reg)
    p.requirement("prf01", "RWT-PRF-01", "Design Capacity", "The works shall treat up to 55 megalitres per day.", prf)
    p.requirement("prf02", "RWT-PRF-02", "Filter Run Length",
                  "Each filter shall run for at least 36 hours between backwashes at design flow.", prf)
    p.requirement("prf03", "RWT-PRF-03", "Clearwell Storage",
                  "The clearwell shall hold at least 4 hours of treated water at average day demand.", prf)
    p.requirement("prf04", "RWT-PRF-04", "UV Dose",
                  "The UV reactors shall deliver a dose of at least 40 mJ/cm2 at the end of lamp life.", prf)
    p.requirement("saf01", "RWT-SAF-01", "Hypochlorite Leak Detection",
                  "Leak detection in the hypochlorite store shall stop the dosing pumps within 10 seconds.", saf)
    p.requirement("saf02", "RWT-SAF-02", "Clearwell Entry",
                  "No one shall enter the clearwell without a confined space permit and a second person outside.", saf)
    p.requirement("saf03", "RWT-SAF-03", "Backwash Interlock", "Only one filter shall be backwashed at a time.", saf)
    for source, target in (("works", "prf01"), ("filter", "reg001"), ("filter", "prf02"), ("cct", "reg002"),
                           ("uv", "prf04"), ("clearwell", "prf03"), ("historian", "reg004"),
                           ("historian", "reg006"), ("wrt", "reg007"), ("fluor", "reg005"), ("hypo", "saf01"),
                           ("backwash", "saf03"), ("ait402", "reg003")):
        p.relate("satisfy", source, target, req)
    p.relate("deriveReqt", "prf04", "reg002", req)
    p.relate("deriveReqt", "prf02", "reg001", req)

    # -- behaviour -------------------------------------------------------------------------------
    p.activity("treat", "Treatment Process", beh, "The path of the water from river to trunk main.", [
        ("t0", "InitialNode", ""), ("t1", "OpaqueAction", "Screen and Lift Raw Water"),
        ("t2", "OpaqueAction", "Coagulate"), ("t3", "OpaqueAction", "Flocculate"), ("t4", "OpaqueAction", "Settle"),
        ("t5", "OpaqueAction", "Filter"), ("t6", "OpaqueAction", "Irradiate with UV"),
        ("t7", "OpaqueAction", "Chlorinate"), ("t8", "OpaqueAction", "Correct pH and Fluoridate"),
        ("t9", "OpaqueAction", "Store in Clearwell"), ("t10", "OpaqueAction", "Pump to Trunk Main"),
        ("t11", "ActivityFinalNode", "")],
        [(f"t{i}", f"t{i + 1}") for i in range(11)])
    for action, block in (("t1", "llps"), ("t2", "rapidmix"), ("t3", "floc"), ("t4", "lamella"), ("t5", "filter"),
                          ("t6", "uv"), ("t7", "cct"), ("t9", "clearwell"), ("t10", "hlps")):
        p.relate("allocate", action, block, beh)
    p.activity("bwseq", "Filter Backwash Sequence", "filter",
               "The steps PLC-300 runs to clean one filter, after the SCADA grants a backwash permit.", [
                   ("b0", "InitialNode", ""), ("b1", "OpaqueAction", "Close Inlet Valve"),
                   ("b2", "OpaqueAction", "Drain to 300 mm Above Media"),
                   ("b3", "OpaqueAction", "Air Scour for 3 Minutes"),
                   ("b4", "OpaqueAction", "Combined Air and Water Wash for 4 Minutes"),
                   ("b5", "OpaqueAction", "Water Rinse for 8 Minutes"), ("b6", "OpaqueAction", "Refill"),
                   ("b7", "OpaqueAction", "Filter to Waste"), ("b8", "DecisionNode", ""),
                   ("b9", "OpaqueAction", "Return to Service"), ("b10", "ActivityFinalNode", "")],
               [("b0", "b1"), ("b1", "b2"), ("b2", "b3"), ("b3", "b4"), ("b4", "b5"), ("b5", "b6"), ("b6", "b7"),
                ("b7", "b8"), ("b8", "b9", "effluent below 0.1 NTU or 15 minutes elapsed"),
                ("b8", "b7", "effluent at or above 0.1 NTU"), ("b9", "b10")])
    p.activity("cldose", "Chlorine Dose Control", beh,
               "The loop PLC-400 runs every 30 seconds to trim the hypochlorite dose.", [
                   ("c0", "InitialNode", ""), ("c1", "OpaqueAction", "Read Post-Contact Residual"),
                   ("c2", "DecisionNode", ""), ("c3", "OpaqueAction", "Increase Hypochlorite Dose"),
                   ("c4", "OpaqueAction", "Reduce Hypochlorite Dose"), ("c5", "OpaqueAction", "Hold Dose"),
                   ("c6", "MergeNode", ""), ("c7", "ActivityFinalNode", "")],
               [("c0", "c1"), ("c1", "c2"), ("c2", "c3", "residual below 0.8 mg/L"),
                ("c2", "c4", "residual above 1.6 mg/L"), ("c2", "c5", "residual within band"),
                ("c3", "c6"), ("c4", "c6"), ("c5", "c6"), ("c6", "c7")])
    p.relate("allocate", "cldose", "plc400", beh)

    for key, name in (("sg_permit", "Backwash Permit"), ("sg_done", "Backwash Complete"),
                      ("sg_ripe", "Ripening Complete"), ("sg_fault", "Filter Fault"), ("sg_reset", "Fault Reset"),
                      ("sg_rest", "Rest Filter"), ("sg_resume", "Resume Filter")):
        p.signal(key, name, beh)
    p.state_machine("fsm", "Filter States", "filter", "The states of one filter, as PLC-300 tracks them.", [
        ("f_init", ""), ("f_run", "Filtering"), ("f_wait", "Awaiting Backwash", "Request a backwash permit"),
        ("f_bw", "Backwashing", "Run the Filter Backwash Sequence"), ("f_ftw", "Filter to Waste"),
        ("f_sb", "Standby"), ("f_oos", "Out of Service", "Raise a maintenance work order")],
        [("f_init", "f_run", None, None),
         ("f_run", "f_wait", None, "head loss above 2.4 m, or 72 hours in service, or effluent above 0.15 NTU"),
         ("f_wait", "f_bw", "sg_permit", None), ("f_bw", "f_ftw", "sg_done", None),
         ("f_ftw", "f_run", "sg_ripe", "effluent below 0.1 NTU"), ("f_run", "f_sb", "sg_rest", None),
         ("f_sb", "f_run", "sg_resume", None), ("f_run", "f_oos", "sg_fault", None),
         ("f_oos", "f_sb", "sg_reset", None)])

    p.constraint_block("ctcalc", "CT Calculation", beh, "CT = C x T10, where T10 = (V / Q) x BF",
                       [("C", vt["mgl"]), ("T10", vt["min"]), ("V", vt["m3"]), ("Q", None), ("BF", None)],
                       doc="Disinfection credit: the chlorine residual C times the contact time T10.")
    p.relate("refine", "ctcalc", "reg002", beh)

    p.activity("t_ct", "CT Compliance Test", ver, "Run quarterly at the lowest recorded water temperature.", [
        ("v0", "InitialNode", ""), ("v1", "OpaqueAction", "Dose Lithium Tracer"),
        ("v2", "OpaqueAction", "Measure T10 at Tank Outlet"), ("v3", "OpaqueAction", "Compute CT"),
        ("v4", "ActivityFinalNode", "")], [("v0", "v1"), ("v1", "v2"), ("v2", "v3"), ("v3", "v4")], test_case=True)
    p.activity("t_turb", "Turbidity Alarm Test", ver, "Injects a 0.5 NTU standard into each filter turbidimeter.", [
        ("w0", "InitialNode", ""), ("w1", "OpaqueAction", "Inject Formazin Standard"),
        ("w2", "OpaqueAction", "Confirm SCADA Alarm"), ("w3", "ActivityFinalNode", "")],
        [("w0", "w1"), ("w1", "w2"), ("w2", "w3")], test_case=True)
    p.activity("t_bwi", "Backwash Interlock Test", ver,
               "Requests two backwashes at once and checks that the second is refused.", [
                   ("x0", "InitialNode", ""), ("x1", "OpaqueAction", "Request Two Backwashes"),
                   ("x2", "OpaqueAction", "Confirm Second Refused"), ("x3", "ActivityFinalNode", "")],
               [("x0", "x1"), ("x1", "x2"), ("x2", "x3")], test_case=True)
    for test, target in (("t_ct", "reg002"), ("t_turb", "reg004"), ("t_bwi", "saf03")):
        p.relate("verify", test, target, ver)

    # -- instances -------------------------------------------------------------------------------
    p.block("mode", "Operating Mode", modes, "A set of dosing and flow settings for one season or event.",
            values=[("alumDose", vt["mgl"], None), ("polymerDose", vt["mgl"], None),
                    ("chlorineDose", vt["mgl"], None), ("plantFlow", vt["mld"], None),
                    ("filtersInService", None, None)])
    for i, (name, alum, poly, cl, flow, nf, doc) in enumerate(MODES):
        p.instance(f"mode{i}", name, "mode", modes, {"alumDose": alum, "polymerDose": poly, "chlorineDose": cl,
                                                     "plantFlow": flow, "filtersInService": nf}, doc)
    for name, year, anth, sand, area, note in FILTERS:
        p.instance(f"reg_{name.lower()}", f"Filter {name}", "filter", reg_f,
                   {"commissioned": year, "anthraciteDepth": anth, "sandDepth": sand, "area": area}, note)

    # -- diagrams --------------------------------------------------------------------------------
    p.ibd("d_ibd", "Riverbend Process Flow", "works")
    p.diagram("d_overview", "Riverbend Overview", "SysML Block Definition Diagram", ctx,
              ["works", "intake", "llps", "rapidmix", "floc", "lamella", "filter", "backwash", "uv", "cct",
               "clearwell", "hlps", "thickener", "wrt", "alum", "poly", "hypo", "fluor", "lime", "scada",
               "historian", "plc100", "plc200", "plc300", "plc400", "plc500", "llpump", "hlpump"])
    p.diagram("d_reg", "Regulatory Requirements", "Requirement Diagram", reg,
              ["reg001", "reg002", "reg003", "reg004", "reg005", "reg006", "reg007", "filter", "cct", "historian",
               "wrt", "fluor", "ait402", "prf02", "prf04"])
    p.diagram("d_inst", "Instrument Allocation", "SysML Block Definition Diagram", ctl,
              [k for k, *_ in instruments] + [k for k, _ in plcs])
    p.behavior_diagram("d_treat", "Treatment Process", "treat", cols=6)
    p.behavior_diagram("d_bw", "Filter Backwash Sequence", "bwseq")
    p.behavior_diagram("d_cl", "Chlorine Dose Control", "cldose")
    p.behavior_diagram("d_fsm", "Filter States", "fsm", cols=3)
    p.diagram("d_ct", "CT Calculation", "SysML Parametric Diagram", beh, ["ctcalc", "reg002", "cct"])
    p.diagram("d_modes", "Operating Modes", "SysML Block Definition Diagram", modes,
              ["mode", "mode0", "mode1", "mode2"])

    # -- questions -------------------------------------------------------------------------------
    p.ask("q01", "parameter", "easy", "How much water does the Riverbend Clearwell hold?",
          "How much treated water can the plant store before pumping it out?", ["clearwell"], ["prf03"],
          evidence="4,500 cubic metres")
    p.ask("q02", "lookup", "easy", "Which UV reactors does the Riverbend works use?",
          "What make of ultraviolet disinfection units does the water plant have?", ["uv"], ["prf04"],
          evidence="Lumora UV-600")
    p.ask("q03", "lookup", "easy", "Which polymer does the Polymer Feed System dose?",
          "What coagulant aid is added to the river water?", ["poly"], evidence="Floctra C-21")
    p.ask("q04", "parameter", "easy", "What is the design capacity of the Riverbend Water Treatment Works?",
          "How much water can the Riverbend plant treat in a day at most?", ["prf01", "works"],
          evidence=["55 megalitres per day", "55 megalitres a day"])
    p.ask("q05", "lookup", "easy", "Which river does the Riverbend Intake draw from?",
          "Where does the town's drinking water plant take its raw water?", ["intake"], ["works"],
          evidence="Tamsin River at Hollow Ford")
    p.ask("q06", "requirement-by-id", "medium", "What does requirement RWT-REG-003 state?",
          "How much chlorine must remain in the water as it enters the pipes to town?", ["reg003"], ["ait402"],
          evidence="no less than 0.5 mg/L")
    p.ask("q07", "behaviour", "medium", "What conditions trigger a filter to await backwash in Filter States?",
          "When does a filter at the water works need cleaning?", ["fsm"], ["filter"],
          evidence="head loss above 2.4 m, or 72 hours in service")
    p.ask("q08", "behaviour", "medium", "How long is the air scour in the Filter Backwash Sequence?",
          "For how long is air blown through the filter media when it is cleaned?", ["bwseq"], ["backwash"],
          evidence="Air Scour for 3 Minutes")
    p.ask("q09", "trace", "medium", "Which block satisfies RWT-PRF-04, UV Dose?",
          "Which equipment is responsible for the ultraviolet dose at the water plant?", ["uv", "prf04"],
          evidence=["UV Reactor satisfies", "satisfies UV Dose", "satisfies [UV Dose]"])
    p.ask("q10", "tagged-value", "medium", "What is the high alarm limit of the Settled Water Turbidimeter AIT-201?",
          "At what cloudiness does the plant alarm on water leaving the settlers?", ["ait201"],
          evidence="alarmHigh = 2.0 NTU")
    p.ask("q11", "instance", "hard", "What alum dose is used in Winter Mode?",
          "How much aluminium sulfate does the plant dose in the cold season?", ["mode1"], ["mode"],
          evidence="alumDose = 42")
    p.ask("q12", "trace", "medium", "Which test verifies RWT-REG-002?",
          "How does the plant prove that its disinfection kills viruses?", ["t_ct", "reg002"],
          evidence=["CT Compliance Test verifies this", "verifies RWT-REG-002"])
    p.ask("q13", "near-duplicate", "hard",
          "What is the high alarm limit of the Combined Filter Effluent Turbidimeter?",
          "At what turbidity does the alarm sound for the blended water from all the filters?", ["ait310"],
          evidence="alarmHigh = 0.3 NTU")
    p.ask("q14", "multi-hop", "hard", "Which PLC handles the Post-Contact Chlorine Analyzer?",
          "Which controller reads the chlorine measurement taken after the contact tank?", ["ait401", "plc400"],
          evidence={"ait401": "is allocated to PLC-400", "plc400": "Post-Contact Chlorine Analyzer is allocated to this"})
    p.ask("q15", "requirement-by-id", "medium", "What does requirement RWT-REG-007 require?",
          "How fast may dirty filter wash water be recycled into the plant?", ["reg007"], ["wrt"],
          evidence="10% of the raw water flow")
    p.ask("q16", "instance", "hard", "How deep is the anthracite in Filter F4?",
          "Which filter has the thicker layer of coal media, and how thick is it?", ["reg_f4"], ["filter"],
          evidence="anthraciteDepth = 900")
    p.ask("q17", "instance", "hard", "Which filter was rebuilt in 2019?",
          "Which of the plant's filters had its media replaced after a loss?", ["reg_f4"],
          evidence="Rebuilt in 2019")
    p.ask("q18", "lookup", "medium", "How is CT calculated at Riverbend?",
          "How does the plant work out its disinfection credit?", ["ctcalc"], ["reg002", "cct"],
          evidence="CT = C x T10")
    p.ask("q19", "behaviour", "hard", "When does a filter return from Filter to Waste to Filtering?",
          "When can a freshly cleaned filter go back to supplying water?", ["fsm", "bwseq"],
          evidence="effluent below 0.1 NTU")
    p.ask("q20", "tagged-value", "medium", "How often is sodium hypochlorite delivered to the Hypochlorite Store?",
          "How frequently does the bleach tanker come to the water works?", ["hypo"],
          evidence="deliveryFrequency = every 9 days")
    p.ask("q21", "parameter", "medium", "What is the baffling factor of the Chlorine Contact Tank?",
          "How well do the baffles in the disinfection tank stop water short-circuiting?", ["cct"],
          evidence=["baffling factor of 0.7", "bafflingFactor = 0.7"])
    p.ask("q22", "parameter", "medium", "How long does the RiverWatch Historian keep its data?",
          "For how many years are the plant's measurements kept?", ["historian", "reg006"],
          evidence=["for 7 years", "kept for 7 years"])
    p.ask("q23", "lookup", "easy", "Which backwash pump is the duty pump?",
          "Which pump normally supplies the water for cleaning the filters?", ["backwash"], evidence="BW-1 is duty")
    p.ask("q24", "behaviour", "medium", "In Chlorine Dose Control, what happens when the residual is below 0.8 mg/L?",
          "What does the plant do when there is too little chlorine left after the contact tank?", ["cldose"],
          ["ait401"], evidence="Increase Hypochlorite Dose")
    p.ask("q25", "structure", "medium", "Which pumps make up the Low-Lift Pump Station?",
          "Which pumps lift the river water into the plant?", ["llps"], evidence="LL-3")
    p.ask("q26", "instance", "hard", "How many filters are in service in Winter Mode?",
          "How many filters run during the cold months?", ["mode1"], evidence="filtersInService = 5")
    return p
