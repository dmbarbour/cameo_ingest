"""Ferrous Valley Level Crossing: a medium project (about 550 XMI ids) built to be hard.

Every name and figure is invented. The crossing comes in two variants, single-track rural (A)
and double-track urban (B), whose blocks share their names and differ in their figures (a gate
arm of 4.5 m or 7.2 m), so a question must be matched to its variant. Besides:
- traceability three levels deep: stakeholder needs, system and subsystem requirements;
- a hazard log in tagged values, with requirements tracing to the hazards they mitigate;
- the crossing sequence as a state machine shared by both variants, and a fault response;
- crossing sites as instances, and one fact found only in a note on a diagram.
"""

from __future__ import annotations

import itertools

from .builder import Project

VARIANTS = {  # figure: (variant A, variant B)
    "armLength": (4.5, 7.2), "loweringTime": (8, 10), "warningTime": (27, 35), "strikeIn": (1200, 1650),
    "bellVolume": (95, 85), "batteryHours": (8, 24),
}


def build() -> Project:
    p = Project("Ferrous Valley Level Crossing", "fvx")
    p.profile("FVX", "Ferrous Valley Profile", {
        "Hazard": ["hazardId", "severity", "likelihood", "sil"],
        "StakeholderNeed": ["needId", "source", "priority"],
    })
    needs = p.package("needs", "1 Stakeholder Needs", doc="Needs gathered at the Ferrous Valley consultation, 2023.")
    sysr = p.package("sysr", "2 System Requirements")
    subr = p.package("subr", "3 Subsystem Requirements")
    haz = p.package("haz", "4 Hazard Log", doc="Hazards from the 2024 hazard identification workshop.")
    common = p.package("common", "5 Common Design", doc="What both variants share.")
    var_a = p.package("var_a", "6 Variant A Single Track Rural",
                      doc="For single-track lines at up to 100 km/h with light road traffic.")
    var_b = p.package("var_b", "7 Variant B Double Track Urban",
                      doc="For double-track lines at up to 140 km/h in towns, with pedestrian gates.")
    sites = p.package("sites", "8 Crossing Sites", doc="Every crossing on the Ferrous Valley line, and its variant.")
    ver = p.package("ver", "9 Verification")

    vt = {k: p.value_type(f"vt_{k}", n, common, unit=u) for k, n, u in (
        ("m", "metres", "m"), ("s", "seconds", "s"), ("db", "decibels A-weighted", "dB(A)"), ("h", "hours", "h"),
        ("kmh", "kilometres per hour", "km/h"))}

    # -- needs, requirements, hazards ------------------------------------------------------------
    need_rows = [
        ("sn01", "SN-01", "Warn Road Users", "Road users shall be warned of an approaching train in good time.",
         "Ferrous Valley Highways Office", "essential"),
        ("sn02", "SN-02", "Stop Road Users", "Road users shall be physically stopped from crossing while a train passes.",
         "Office of Rail Safety", "essential"),
        ("sn03", "SN-03", "Safe Pedestrian Access", "Pedestrians and wheelchair users shall cross safely at town crossings.",
         "Ferrous Valley Council access forum", "essential"),
        ("sn04", "SN-04", "Quiet Nights", "Residents near town crossings shall not be woken by warning bells.",
         "Willow Lane Residents' Association", "desirable"),
        ("sn05", "SN-05", "Fail Safe", "A failure of the crossing shall never leave the road open with a train coming.",
         "Office of Rail Safety", "essential"),
        ("sn06", "SN-06", "Minimal Road Delay", "Road traffic shall not wait longer than necessary.",
         "Ferrous Valley Highways Office", "desirable"),
    ]
    for key, nid, name, text, source, priority in need_rows:
        p.requirement(key, nid, name, text, needs)
        p.apply("FVX", "StakeholderNeed", key, needId=nid, source=source, priority=priority)
    sys_rows = [  # key, id, name, text, needs it derives from, variant
        ("s01", "FVX-SYS-001", "Warning Lights", "The crossing shall show twin flashing red lights to every road approach.",
         ["sn01"], None),
        ("s02", "FVX-SYS-002", "Audible Warning", "The crossing shall sound an audible warning while the lights flash.",
         ["sn01"], None),
        ("s03", "FVX-SYS-003", "Barriers", "The crossing shall lower barriers across every road lane before the train arrives.",
         ["sn02"], None),
        ("s04", "FVX-SYS-004", "Warning Time A",
         (f"For variant A, the warning shall begin at least {VARIANTS['warningTime'][0]} seconds before the "
         "fastest train reaches the crossing."), ["sn01", "sn02"], "A"),
        ("s05", "FVX-SYS-005", "Warning Time B",
         (f"For variant B, the warning shall begin at least {VARIANTS['warningTime'][1]} seconds before the "
         "fastest train reaches the crossing."), ["sn01", "sn02"], "B"),
        ("s06", "FVX-SYS-006", "Pedestrian Gates", "Town crossings shall have self-closing pedestrian gates on each footway.",
         ["sn03"], "B"),
        ("s07", "FVX-SYS-007", "Night Bell Volume",
         "The audible warning shall be reduced at night where a noise agreement applies.", ["sn04"], "B"),
        ("s08", "FVX-SYS-008", "Fail Safe State",
         "On any detected fault the crossing shall keep or bring the barriers down and the lights flashing.",
         ["sn05"], None),
        ("s09", "FVX-SYS-009", "Second Train",
         "The barriers shall stay down, or lower again, if a second train approaches before they are fully raised.",
         ["sn02", "sn05"], None),
        ("s10", "FVX-SYS-010", "Prompt Reopening",
         "The barriers shall start to rise within 3 seconds of the last train clearing the crossing.", ["sn06"], None),
        ("s11", "FVX-SYS-011", "Obstacle Detection",
         ("Double-track crossings shall confirm that no vehicle is trapped between the barriers before the "
         "train is given a proceed signal."), ["sn02", "sn05"], "B"),
        ("s12", "FVX-SYS-012", "Battery Backup", "The crossing shall work on battery for a full shift after mains failure.",
         ["sn05"], None),
    ]
    for key, rid, name, text, parents, _ in sys_rows:
        p.requirement(key, rid, name, text, sysr)
        for parent in parents:
            p.relate("deriveReqt", key, parent, sysr)
    sub_rows = [  # key, id, name, text, parent
        ("u11", "FVX-SUB-011", "Lamp Intensity", "Each warning lamp shall give at least 400 candela on its axis.", "s01"),
        ("u12", "FVX-SUB-012", "Flash Rate", "The warning lamps shall flash alternately 60 times a minute.", "s01"),
        ("u21", "FVX-SUB-021", "Bell Pattern", "The audible warning shall be a two-tone yodel, not a bell, on variant B.",
         "s02"),
        ("u31", "FVX-SUB-031", "Gate Arm Lighting",
         "Each gate arm shall carry three red lamps, the tip lamp lit steadily.", "s03"),
        ("u32", "FVX-SUB-032", "Arm Breakaway", ("A gate arm struck by a vehicle shall break away at its shear pin "
                                                "without damaging the barrier machine."), "s03"),
        ("u61", "FVX-SUB-061", "Gate Closing Force", "Pedestrian gates shall close with no more than 50 newtons of force.",
         "s06"),
        ("u81", "FVX-SUB-081", "Detection Watchdog",
         "The controller shall declare a detection fault if a track section is occupied for more than 20 minutes.",
         "s08"),
        ("u111", "FVX-SUB-111", "Radar Coverage", ("The obstacle detector shall cover the whole area between the "
                                                  "barriers, down to an object 0.5 m high."), "s11"),
    ]
    for key, rid, name, text, parent in sub_rows:
        p.requirement(key, rid, name, text, subr)
        p.relate("deriveReqt", key, parent, subr)
    hazards = [
        ("hz01", "HZ-01", "Late Warning", "The warning starts too late for a road user to stop.", "catastrophic",
         "remote", "SIL 3"),
        ("hz02", "HZ-02", "Barriers Raised with Train Approaching",
         "The barriers rise while a second train is approaching.", "catastrophic", "improbable", "SIL 4"),
        ("hz03", "HZ-03", "Vehicle Trapped", "A vehicle is trapped between the barriers.", "critical", "occasional",
         "SIL 2"),
        ("hz04", "HZ-04", "Pedestrian Struck by Gate", "A closing pedestrian gate strikes a child or wheelchair user.",
         "marginal", "occasional", "SIL 1"),
        ("hz05", "HZ-05", "Silent Failure", "A detection fault leaves the crossing open with no warning.",
         "catastrophic", "remote", "SIL 3"),
    ]
    for key, hid, name, doc, severity, likelihood, sil in hazards:
        p.block(key, name, haz, doc, stereotype=None)
        p.apply("FVX", "Hazard", key, hazardId=hid, severity=severity, likelihood=likelihood, sil=sil)
    for req, hazard in (("s04", "hz01"), ("s05", "hz01"), ("s09", "hz02"), ("s11", "hz03"), ("u61", "hz04"),
                        ("s08", "hz05"), ("u81", "hz05")):
        p.relate("trace", req, hazard, haz)

    # -- design ----------------------------------------------------------------------------------
    p.block("controller", "Level Crossing Controller", common,
            "The common design of the crossing controller; each variant specializes it.",
            values=[("warningTime", vt["s"], None)])
    for key, name in (("sg_strike", "Train Approaching"), ("sg_lowered", "Lowering Time Elapsed"),
                      ("sg_down", "Barriers Down Proven"), ("sg_clear", "Train Cleared"),
                      ("sg_up", "Barriers Up Proven"), ("sg_fault", "Detection Fault"), ("sg_reset", "Fault Reset")):
        p.signal(key, name, common)
    p.state_machine("seq", "Crossing Sequence", "controller",
                    "The sequence every Ferrous Valley crossing follows; variant B adds the obstacle check.", [
                        ("q_init", ""), ("q_open", "Open"), ("q_warn", "Warning", "Flash lights and sound the warning"),
                        ("q_lower", "Barriers Lowering"), ("q_closed", "Closed", "Clear the protecting signal"),
                        ("q_raise", "Barriers Raising"),
                        ("q_fail", "Failed Safe", "Keep barriers down and lights flashing; call the signaller")],
                    [("q_init", "q_open", None, None), ("q_open", "q_warn", "sg_strike", None),
                     ("q_warn", "q_lower", "sg_lowered", None),
                     ("q_lower", "q_closed", "sg_down", "variant A, or the obstacle detector reports the area clear"),
                     ("q_closed", "q_raise", "sg_clear", "no other train approaching"),
                     ("q_raise", "q_lower", "sg_strike", None), ("q_raise", "q_open", "sg_up", None),
                     ("q_open", "q_fail", "sg_fault", None), ("q_closed", "q_fail", "sg_fault", None),
                     ("q_fail", "q_open", "sg_reset", "technician present and detection healthy")])
    p.constraint_block("wtcalc", "Warning Time Calculation", common,
                       "warningTime = strikeInDistance / lineSpeed + 5 s margin",
                       [("warningTime", vt["s"]), ("strikeInDistance", vt["m"]), ("lineSpeed", vt["kmh"])],
                       doc="How the strike-in point is placed: far enough back that the warning time is met.")
    p.relate("refine", "wtcalc", "s04", common)
    p.relate("refine", "wtcalc", "s05", common)
    p.activity("faultresp", "Barrier Fault Response", common,
               "What the controller and the signaller do when a barrier fails to come down.", [
                   ("r0", "InitialNode", ""), ("r1", "OpaqueAction", "Detect Barrier Not Down After 12 Seconds"),
                   ("r2", "OpaqueAction", "Hold Protecting Signal at Danger"),
                   ("r3", "OpaqueAction", "Alert Ferrous Valley Signal Box"),
                   ("r4", "DecisionNode", ""), ("r5", "OpaqueAction", "Caution Train Over Crossing at 10 km/h"),
                   ("r6", "OpaqueAction", "Send Crossing Keeper"), ("r7", "ActivityFinalNode", "")],
               [("r0", "r1"), ("r1", "r2"), ("r2", "r3"), ("r3", "r4"), ("r4", "r5", "crossing keeper on site"),
                ("r4", "r6", "no keeper on site"), ("r6", "r5"), ("r5", "r7")])
    p.relate("allocate", "faultresp", "controller", common)

    variant_blocks = {}
    for v, (pkg, label) in enumerate(((var_a, "A"), (var_b, "B"))):
        k = label.lower()
        f = {name: values[v] for name, values in VARIANTS.items()}
        p.block(f"arm_{k}", "Gate Arm", pkg,
                f"An aluminium boom {f['armLength']} m long, with three red lamps.",
                values=[("armLength", vt["m"], f["armLength"])])
        p.block(f"bm_{k}", "Barrier Machine", pkg,
                f"An electro-hydraulic barrier machine that lowers its arm in {f['loweringTime']} seconds.",
                values=[("loweringTime", vt["s"], f["loweringTime"])])
        p.block(f"lights_{k}", "Warning Lights", pkg, "Twin red LED lamps on each road approach.")
        p.block(f"audio_{k}", "Audible Warning", pkg,
                ("A two-tone yodel loudspeaker." if label == "B" else "A mechanical bell.")
                + f" It sounds at {f['bellVolume']} dB(A) at 3 m.",
                values=[("volume", vt["db"], f["bellVolume"])])
        p.block(f"det_{k}", "Train Detection Section", pkg,
                f"Axle counters at the strike-in point, {f['strikeIn']} m before the crossing, and at the crossing.",
                values=[("strikeInDistance", vt["m"], f["strikeIn"])])
        p.block(f"power_{k}", "Power Supply", pkg,
                f"Mains supply with a valve-regulated battery that runs the crossing for {f['batteryHours']} hours.",
                values=[("batteryHours", vt["h"], f["batteryHours"])])
        parts = [("arms", f"arm_{k}", "2..2" if label == "A" else "4..4"), ("barrier machines", f"bm_{k}"),
                 ("lights", f"lights_{k}"), ("audible warning", f"audio_{k}"), ("detection", f"det_{k}"),
                 ("power", f"power_{k}")]
        if label == "B":
            p.block("obst_b", "Obstacle Detector", pkg,
                    "A scanning radar that checks the area between the barriers is clear. Variant B only.")
            p.block("pgate_b", "Pedestrian Gate", pkg,
                    "A self-closing gate on each footway, released when the barriers rise.")
            parts += [("obstacle detector", "obst_b"), ("pedestrian gates", "pgate_b", "4..4")]
        name = "Single Track Rural Crossing" if label == "A" else "Double Track Urban Crossing"
        controller = "Halcyon LX-200" if label == "A" else "Halcyon LX-400"
        p.block(f"cross_{k}", name, pkg,
                f"Variant {label} of the Ferrous Valley crossing, run by a {controller} controller"
                + (", duplicated two-out-of-two." if label == "B" else "."),
                general="controller", parts=parts,
                values=[("warningTime", vt["s"], f["warningTime"]), ("controllerModel", None, controller)])
        variant_blocks[label] = f"cross_{k}"
    for source, target in (("lights_a", "s01"), ("lights_b", "s01"), ("audio_a", "s02"), ("audio_b", "s02"),
                           ("bm_a", "s03"), ("bm_b", "s03"), ("cross_a", "s04"), ("cross_b", "s05"),
                           ("pgate_b", "s06"), ("audio_b", "s07"), ("controller", "s08"), ("controller", "s09"),
                           ("controller", "s10"), ("obst_b", "s11"), ("power_a", "s12"), ("power_b", "s12"),
                           ("obst_b", "u111"), ("pgate_b", "u61"), ("arm_b", "u31"), ("arm_a", "u31"),
                           ("arm_a", "u32"), ("arm_b", "u32"), ("lights_a", "u11"), ("lights_b", "u11"),
                           ("audio_b", "u21"), ("controller", "u81")):
        p.relate("satisfy", source, target, sysr if target.startswith("s") else subr)
    p.note("n_willow", "Willow Lane: under the noise agreement with Ferrous Valley Council, the audible warning is "
                       "turned down to 75 dB(A) from 22:00 to 06:00.", var_b, ["audio_b"])

    # -- sites, verification ---------------------------------------------------------------------
    p.block("site", "Crossing Site", sites, "A place where the Ferrous Valley line crosses a road.",
            values=[("lineSpeed", vt["kmh"], None), ("roadVehiclesPerDay", None, None), ("milepost", None, None)])
    for key, name, variant, speed, traffic, milepost, doc in (
            ("cutlers", "Cutler's Drove", "A", 90, 340, "12.4", "A farm road with a poor sightline to the north."),
            ("moss", "Moss Gate", "A", 100, 610, "15.1", "Next to the Moss Gate grain silos; harvest lorries in autumn."),
            ("quarry", "Quarry Siding", "A", 60, 120, "18.7", "Serves the quarry only; locked outside working hours."),
            ("willow", "Willow Lane", "B", 140, 9400, "22.9", "In Ferrous Valley town, beside the primary school."),
            ("station", "Station Road", "B", 110, 15200, "23.6", "At the east end of Ferrous Valley station platforms.")):
        p.instance(f"site_{key}", name, "site", sites,
                   {"lineSpeed": speed, "roadVehiclesPerDay": traffic, "milepost": milepost},
                   doc=f"{doc} Variant {variant}.")
        p.relate("allocate", f"site_{key}", variant_blocks[variant], sites)
    for key, name, target, steps in (
            ("t_wt", "Warning Time Test", "s05", ["Run Test Train at Line Speed", "Time Strike-In to Arrival"]),
            ("t_second", "Second Train Test", "s09", ["Clear First Train", "Strike In Second Train While Raising",
                                                      "Confirm Barriers Lower Again"]),
            ("t_obst", "Trapped Vehicle Test", "s11", ["Park Test Car Between Barriers",
                                                       "Confirm Protecting Signal Stays at Danger"])):
        nodes = [(f"{key}_0", "InitialNode", "")] + [(f"{key}_{i}", "OpaqueAction", s) for i, s in enumerate(steps, 1)]
        nodes.append((f"{key}_end", "ActivityFinalNode", ""))
        p.activity(key, name, ver, f"Site acceptance test for {target.upper().replace('S', 'FVX-SYS-0')}.", nodes,
                   [(a[0], b[0]) for a, b in itertools.pairwise(nodes)], test_case=True)
        p.relate("verify", key, target, ver)

    # -- diagrams --------------------------------------------------------------------------------
    p.diagram("d_needs", "Needs to Requirements", "Requirement Diagram", sysr,
              [r[0] for r in need_rows] + [r[0] for r in sys_rows], cols=6)
    p.diagram("d_sub", "Subsystem Requirements", "Requirement Diagram", subr,
              [r[0] for r in sub_rows] + ["s01", "s02", "s03", "s06", "s08", "s11"], cols=7)
    p.diagram("d_haz", "Hazard Mitigation", "Requirement Diagram", haz,
              [h[0] for h in hazards] + ["s04", "s05", "s08", "s09", "s11", "u61", "u81"], cols=6)
    p.diagram("d_var", "Variants", "SysML Block Definition Diagram", common, ["controller", "cross_a", "cross_b"])
    p.ibd("d_ibd_a", "Variant A Parts", "cross_a")
    p.ibd("d_ibd_b", "Variant B Parts", "cross_b")
    p.diagram("d_audio_b", "Variant B Warnings", "SysML Block Definition Diagram", var_b,
              ["audio_b", "lights_b", "n_willow"])
    p.behavior_diagram("d_seq", "Crossing Sequence", "seq", cols=3)
    p.behavior_diagram("d_fault", "Barrier Fault Response", "faultresp")
    p.diagram("d_wt", "Warning Time Calculation", "SysML Parametric Diagram", common, ["wtcalc", "s04", "s05"])
    p.diagram("d_sites", "Crossing Sites", "SysML Block Definition Diagram", sites,
              ["site", "site_cutlers", "site_moss", "site_quarry", "site_willow", "site_station", "cross_a",
               "cross_b"], cols=4)

    # -- questions -------------------------------------------------------------------------------
    p.ask("q01", "lookup", "easy", "Which controller runs a Variant A Single Track Rural Crossing?",
          "What make of controller is used at the country crossings on the Ferrous Valley line?", ["cross_a"],
          evidence="Halcyon LX-200")
    p.ask("q02", "near-duplicate", "hard", "How long is the Gate Arm in Variant B?",
          "How long are the barrier booms at the double-track town crossings?", ["arm_b"],
          evidence=["7.2 m long", "armLength = 7.2"])
    p.ask("q03", "near-duplicate", "hard", "How long is the Gate Arm in Variant A?",
          "How long are the barrier booms at the rural single-track crossings?", ["arm_a"],
          evidence=["4.5 m long", "armLength = 4.5"])
    p.ask("q04", "near-duplicate", "hard", "What is the minimum warning time for variant B under FVX-SYS-005?",
          "How much warning must drivers get before a train reaches a town crossing?", ["s05", "cross_b"],
          evidence=["at least 35 seconds", "warningTime = 35"])
    p.ask("q05", "near-duplicate", "hard", "How far before the crossing is the strike-in point in Variant A?",
          "At what distance does an approaching train start the warning at a rural crossing?", ["det_a"],
          evidence=["1200 m before the crossing", "strikeInDistance = 1200"])
    p.ask("q06", "behaviour", "hard", "In the Crossing Sequence, what happens if a train approaches while the barriers "
                                      "are raising?",
          "What do the barriers do if another train comes just as they start to go up?", ["seq"], ["s09"],
          evidence="Barriers Raising → Barriers Lowering — Train Approaching")
    p.ask("q07", "behaviour", "medium", "What does the crossing do in the Failed Safe state?",
          "What happens at a crossing when its train detection fails?", ["seq"], ["s08"],
          evidence="Keep barriers down and lights flashing")
    p.ask("q08", "tagged-value", "medium", "What safety integrity level does hazard HZ-02 require?",
          "Which hazard at the crossing needs the highest safety integrity, and what level?", ["hz02"],
          evidence="sil = SIL 4")
    p.ask("q09", "trace", "hard", "Which requirement mitigates hazard HZ-03, Vehicle Trapped?",
          "How is the risk of a car being caught between the barriers dealt with?", ["s11", "hz03"],
          evidence=["Obstacle Detection traces to", "Obstacle Detection (FVX-SYS-011) traces",
                    "Obstacle Detection traces"])
    p.ask("q10", "note", "hard", "How loud is the audible warning at Willow Lane at night?",
          "How quiet is the crossing warning near the school in town during the night?", ["audio_b"], ["s07"],
          evidence="75 dB(A) from 22:00 to 06:00")
    p.ask("q11", "instance", "hard", "What is the line speed at Moss Gate?",
          "How fast do trains pass the crossing by the grain silos?", ["site_moss"], evidence="lineSpeed = 100")
    p.ask("q12", "instance", "medium", "Which crossing site is beside the primary school?",
          "Which crossing is near where children go to school in Ferrous Valley?", ["site_willow"],
          evidence="beside the primary school")
    p.ask("q13", "multi-hop", "hard", "Which stakeholder need does FVX-SYS-011, Obstacle Detection, derive from?",
          "Whose concern led to checking for trapped vehicles at the crossings?", ["s11", "sn02", "sn05"], ["u111"],
          evidence={"s11": "is derived from Stop Road Users",
                    "sn02": ["Obstacle Detection (FVX-SYS-011) is derived from this", "Obstacle Detection is derived from this"],
                    "sn05": ["Obstacle Detection (FVX-SYS-011) is derived from this",
                             "Obstacle Detection is derived from this"]})  # titles with ids from 0.6.1
    p.ask("q14", "lookup", "medium", "How is the required warning time calculated?",
          "How do engineers decide where the strike-in point goes?", ["wtcalc"], ["s04", "s05"],
          evidence="strikeInDistance / lineSpeed + 5 s margin")
    p.ask("q15", "trace", "medium", "Which test verifies FVX-SYS-009, Second Train?",
          "How is it checked that the barriers come back down for a second train?", ["t_second", "s09"],
          evidence=["Second Train Test verifies", "verifies Second Train"])
    p.ask("q16", "lookup", "medium", "Which variant has an obstacle detector?",
          "Which kind of crossing scans for cars left between the barriers?", ["obst_b"], ["s11"],
          evidence="Variant B only")
    p.ask("q17", "near-duplicate", "hard", "How long does the battery run a Variant B crossing?",
          "How long can a town crossing keep working after a power cut?", ["power_b"],
          evidence=["for 24 hours", "batteryHours = 24"])
    p.ask("q18", "near-duplicate", "hard", "How long does the Barrier Machine take to lower its arm in Variant A?",
          "How quickly do the barriers come down at a country crossing?", ["bm_a"],
          evidence=["in 8 seconds", "loweringTime = 8"])
    p.ask("q19", "tagged-value", "medium", "Who raised stakeholder need SN-03, Safe Pedestrian Access?",
          "Which group asked for wheelchair users to be able to cross safely?", ["sn03"],
          evidence="Ferrous Valley Council access forum")
    p.ask("q20", "requirement-by-id", "medium", "What does FVX-SUB-081 require?",
          "When does the crossing controller decide that train detection has failed?", ["u81"],
          evidence="occupied for more than 20 minutes")
    p.ask("q21", "behaviour", "medium", "In the Barrier Fault Response, at what speed is a train cautioned over the crossing?",
          "How slowly must a train go over a crossing whose barrier is stuck up?", ["faultresp"],
          evidence="Caution Train Over Crossing at 10 km/h")
    p.ask("q22", "multi-hop", "hard", "What does the Audible Warning of variant B sound like?",
          "Do the town crossings ring a bell?", ["audio_b", "u21"], evidence=["two-tone yodel"])
    return p
