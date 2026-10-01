"""Port Calder Traffic Signal System: a large project (about 5,000 elements), generated from a
seeded table, with hard questions.

Every name and figure is invented. Twelve corridors cross over a hundred streets at about 150
signalised intersections, many streets crossing two corridors, so that names nearly repeat ("Harbour
Road & Copper Row", "Quarry Street & Copper Row"). Each intersection is a block with its
equipment as parts and its site data as tagged values; timing plans are instances; about 130
requirements are imported from DOORS (unnamed, their id in their text). Facts asked about are
unique by construction (site ids, cabinet numbers, cycle lengths), so the answer key holds even
among near-duplicates.
"""

from __future__ import annotations

import random

from .builder import Project, slug

CORRIDORS = [  # code, name, the cross streets it meets (in order), whether buses get priority
    ("HR", "Harbour Road", ["Abbot Lane", "Brindle Street", "Copper Row", "Dunmore Avenue", "Eastgate",
                            "Fennel Street", "Gannet Way", "Hythe Street", "Ironmonger Lane", "Juniper Close",
                            "Keel Street"], True),
    ("QS", "Quarry Street", ["Abbot Lane", "Copper Row", "Lantern Walk", "Mercer Street", "Nettle Lane",
                             "Orchard Rise", "Pilot Street", "Gannet Way", "Rook Lane", "Sexton Street",
                             "Tanner Street"], False),
    ("LA", "Larkspur Avenue", ["Umber Street", "Vane Street", "Copper Row", "Wharf Lane", "Yarrow Street",
                               "Zephyr Way", "Mercer Street", "Ashby Road", "Bellfounder Street", "Cinder Lane",
                               "Rook Lane"], True),
    ("NS", "Ninth Street", ["Dovecote Lane", "Eastgate", "Fletcher Street", "Gannet Way", "Hythe Street",
                            "Islet Road", "Juniper Close", "Kiln Street", "Lantern Walk", "Moorgate",
                            "Nettle Lane"], False),
    ("TR", "Tollgate Road", ["Ostler Street", "Pilot Street", "Quayside", "Rook Lane", "Sexton Street",
                             "Tithe Lane", "Umber Street", "Vane Street", "Wharf Lane", "Yarrow Street",
                             "Zephyr Way"], False),
    ("SP", "Saltmarsh Parkway", ["Ashby Road", "Bellfounder Street", "Cinder Lane", "Dovecote Lane",
                                 "Fletcher Street", "Islet Road", "Kiln Street", "Moorgate", "Ostler Street",
                                 "Quayside", "Tithe Lane"], True),
]
EXTRA_CORRIDORS = ["Cormorant Road", "Fishergate", "Lighthouse Road", "Mill Race Avenue", "Ropewalk Street",
                   "Smelter Road"]  # 15 cross streets each, drawn from STREET_WORDS
STREET_WORDS = (["Alder", "Birch", "Cobble", "Drover", "Elder", "Ferry", "Glass", "Heron", "Ivy", "Jetty", "Lime",
                 "Maple", "Netting", "Oakum", "Pebble", "Quill", "Reed", "Sorrel", "Thistle", "Usher", "Vine",
                 "Willow", "Yew", "Bramble"],
                ["Street", "Lane", "Row", "Walk", "Close"])
CONTROLLERS = [("atc4", "Meridian ATC-4", "The older Meridian controller, being replaced as cabinets are renewed."),
               ("atc5", "Meridian ATC-5", "The current standard controller, with an Ethernet uplink to the ATMS."),
               ("nx2", "Ostrander NX-2", "A compact controller used at three-leg junctions and pedestrian crossings.")]
DETECTORS = [("loop", "Inductive Loop Detector", "Wire loops cut into the road surface at the stop bar."),
             ("radar", "Corvid RD-2 Radar Detector",
              "A pole-mounted radar that tracks vehicles up to 150 m from the stop bar, in rain or fog."),
             ("video", "Vista VD-8 Video Detector",
              "A camera with on-board image processing that places virtual loops on each lane.")]
FEATURES = [  # unique facts, each given to one intersection; {name} is the intersection's
    "A school crossing patrol operates here from 08:10 to 08:50 and from 14:55 to 15:25 on school days.",
    "Fire Station 3 next door preempts the signals from a button in its appliance bay.",
    ("The signals are interconnected with the Tollgate rail level crossing: an approaching train holds all "
    "approaches at red until the barriers rise."),
    "A bus-only queue jump lane runs northbound, with its own early green of 7 seconds.",
    "An all-way pedestrian scramble phase runs every second cycle during shopping hours.",
    "Flood sensor FS-12 under the rail bridge forces the signals to flash amber when water covers the dip.",
    "The cabinet sits inside the Larkspur Library forecourt, behind a locked gate (key at the library desk).",
    "A cycle-only green phase serves the Harbour Greenway crossing before each pedestrian phase.",
    "Tram rails cross diagonally; the tram priority unit TPU-4 requests a dedicated phase.",
    "A wind sensor on the mast arm locks the overhead signs at speeds above 90 km/h.",
    "The intersection was rebuilt in 2021 as a signalised roundabout with metering signals on two arms.",
    "Hospital ambulances from Calder General preempt the signals via the Beacon EVP-90 on a 300 m approach.",
]
PLANS = [("AM Peak", "07:00", "09:30"), ("Midday", "09:30", "15:30"), ("PM Peak", "15:30", "18:30"),
         ("Night", "22:00", "06:00")]
AREAS = [  # package, first id number, requirement texts ({c} is a corridor, where present)
    ("Detection", 100, [
        "Each approach shall have stop-bar detection covering every through lane.",
        "Advance detection shall be placed {n} m before the stop bar on approaches signed at 60 km/h.",
        "A detector fault shall be reported to the ATMS within {n} seconds.",
        "Radar detectors shall track vehicles in heavy rain of up to 50 mm per hour.",
        "Video detectors shall be cleaned of road grime every {n} weeks.",
        "Bicycle detection shall be provided on every approach marked with a cycle lane.",
        "A failed detector shall place a permanent call on its phase until it is repaired.",
        "Queue detectors shall be installed where queues reach the upstream intersection more than {n} times a week.",
    ]),
    ("Signal Timing", 200, [
        "The coordinated corridors shall run a common cycle length within each timing plan.",
        "The minimum green for a through phase shall be {n} seconds.",
        "Yellow change intervals shall be computed from the approach speed using the Port Calder formula.",
        "The all-red clearance shall be at least {n} seconds at intersections wider than 25 m.",
        "Timing plans shall be reviewed every {n} months against measured traffic counts.",
        "A controller shall change timing plan only at the end of a cycle.",
        "Night plans shall run free, uncoordinated, between 22:00 and 06:00.",
        "The offset between adjacent coordinated intersections shall be set for a progression speed of {n} km/h.",
    ]),
    ("Preemption", 300, [
        "An emergency vehicle preemption request shall bring a green to the vehicle's approach within {n} seconds.",
        "Preemption shall not shorten a pedestrian clearance interval that has begun.",
        "After preemption ends, the controller shall return to coordination within {n} cycles.",
        "Rail preemption shall take priority over every other preemption.",
        "Each preemption event shall be logged with the vehicle identifier and the approach.",
        "Preemption shall be confirmed to the emergency vehicle by a white confirmation light.",
    ]),
    ("Transit Priority", 400, [
        "A late bus shall be granted up to {n} seconds of green extension.",
        "Transit priority shall be granted only to buses running more than {n} minutes behind schedule.",
        "A green extension shall not be granted in two consecutive cycles.",
        "The Transit Priority Server shall receive bus positions from the fleet system every {n} seconds.",
        "Transit priority shall be suspended when the cross street queue exceeds {n} vehicles.",
    ]),
    ("Pedestrians", 500, [
        "Every pedestrian crossing shall have accessible push buttons with a locator tone.",
        "The pedestrian walking speed used for clearance shall be {n} metres per second.",
        "A pedestrian shall not wait longer than {n} seconds for a walk signal.",
        "Countdown displays shall show the remaining clearance time.",
        "A leading pedestrian interval of {n} seconds shall be provided where turning traffic conflicts.",
        "Audible signals shall be quieter by 10 dB between 21:00 and 07:00.",
    ]),
    ("Communications", 600, [
        "Every controller shall connect to the Calder Ring fibre network.",
        "A controller that loses the fibre link shall fall back to its cellular modem within {n} seconds.",
        "The Calder Ring shall survive a single fibre cut without losing any controller.",
        "Communications equipment in each cabinet shall run for {n} hours on battery.",
        "Time on every controller shall be kept within 0.1 seconds of the ATMS clock.",
    ]),
    ("Central System", 700, [
        "The ATMS shall show the state of every signal on the video wall within {n} seconds of a change.",
        "Operators shall be able to put any intersection into manual control from the ATMS.",
        "The ATMS shall keep signal timing changes for {n} years, with who made them.",
        "The ATMS shall raise an alarm when a controller reports a conflict monitor trip.",
        "Incident response plans shall be activated by an operator in no more than {n} clicks.",
        "Detector health shall be summarised every morning at 06:00 in a fault report.",
    ]),
    ("Cybersecurity", 800, [
        "Controllers shall accept configuration changes only when signed by the ATMS.",
        "Default passwords shall be changed before a controller is connected to the Calder Ring.",
        "Field cabinets shall report door openings to the ATMS within {n} seconds.",
        "Remote access by contractors shall expire after {n} hours.",
        "Controller firmware shall be updated within {n} days of a vendor security notice.",
    ]),
    ("Maintenance", 900, [
        "Every intersection shall be inspected every {n} months.",
        "A dark signal shall be attended within {n} hours, day or night.",
        "Lamp failures shall be repaired within {n} working days.",
        "Spare controllers of each model in service shall be held at the Calder Depot.",
        "Cabinet filters shall be replaced every {n} months.",
    ]),
]
ATMS = [  # key, name, doc, the areas whose requirements it satisfies
    ("sigman", "Signal Manager", "Downloads timing plans to controllers and shows signal states on the video wall.",
     ["Signal Timing", "Central System"]),
    ("incman", "Incident Manager", "Holds incident response plans and activates them on an operator's command.",
     ["Central System"]),
    ("dethealth", "Detector Health Monitor", "Watches every detector and reports faults to the morning fault report.",
     ["Detection"]),
    ("tsps", "Transit Priority Server", ("Receives bus positions from the Calder Transit fleet system and requests "
                                        "priority from the controllers."), ["Transit Priority"]),
    ("evpm", "Preemption Manager", "Logs preemption events and checks that every controller returns to coordination.",
     ["Preemption"]),
    ("secgw", "Field Security Gateway", "Signs configuration changes and watches cabinet doors.", ["Cybersecurity"]),
    ("netman", "Ring Network Manager", "Monitors the Calder Ring and the cellular fallback links.",
     ["Communications"]),
]


def build() -> Project:
    rng = random.Random(2026)
    p = Project("Port Calder Traffic Signal System", "pct")
    p.profile("PCT", "Port Calder Profile", {
        "SignalSite": ["siteId", "cabinet", "ward", "commissioned", "firmware"],
        "Equipment": ["vendor", "partNumber", "mtbfHours"],
    })
    top = p.package("sys", "Port Calder Signals",
                    doc="The city of Port Calder's traffic signals: field equipment, corridors and the central system.")
    eq = p.package("eq", "Equipment Catalogue", top, doc="Every type of field equipment approved for use.")
    net = p.package("net", "Signal Network", top, doc="The six signal corridors and their intersections.")
    plans_pkg = p.package("plans", "Timing Plans", top, doc="Coordination plans, one set per corridor.")
    central = p.package("central", "Central System", top, doc="The Harbormaster ATMS at the Calder Traffic Centre.")
    reqs = p.package("reqs", "System Requirements", doc="Imported from DOORS, module PCT-SYS, baseline 12.")
    sub = p.package("subreqs", "ATMS Requirements", doc="Requirements on the central system, derived from PCT-SYS.")
    beh = p.package("beh", "Operations")

    vt_s = p.value_type("vt_s", "seconds", eq, unit="s")
    for key, name, doc in CONTROLLERS:
        p.block(key, name, eq, doc, values=[("phases", None, 8 if key != "nx2" else 4)])
        p.apply("PCT", "Equipment", key, vendor=name.split()[0], partNumber=f"{name.split()[-1]}-STD",
                mtbfHours=rng.choice([60000, 75000, 90000]))
    for key, name, doc in DETECTORS:
        p.block(key, name, eq, doc)
    p.block("evp", "Beacon EVP-90 Receiver", eq,
            "An optical receiver that picks up the strobe of an approaching emergency vehicle.")
    p.block("tspu", "TransitLink TSP Unit", eq, "A cabinet module that passes bus priority requests to the controller.")
    p.block("pb", "Accessible Push Button", eq, "A push button with a locator tone, a raised arrow and a vibrating tactile.")
    p.block("modem", "Cellular Modem", eq, "Fallback link to the ATMS when the Calder Ring is down.")

    # -- the network -----------------------------------------------------------------------------
    pool = sorted(f"{a} {b}" for a in STREET_WORDS[0] for b in STREET_WORDS[1])
    corridors = CORRIDORS + [(  # generated corridors, which share some cross streets with each other
        "".join(w[0] for w in name.split()) + ("X" if len(name.split()) == 1 else ""), name,
        sorted(rng.sample(pool[k * 18:k * 18 + 40], 15)), k % 2 == 0)
        for k, name in enumerate(EXTRA_CORRIDORS)]
    names = sorted({f"{corr} & {x}" for _, corr, xs, _ in corridors for x in xs})
    site_ids = rng.sample(range(1001, 1999), len(names))
    cabinets = rng.sample(range(4001, 4999), len(names))
    features = dict(zip(rng.sample(names, len(FEATURES)), FEATURES, strict=True))
    site: dict[str, dict] = {}
    by_corridor: dict[str, list[str]] = {}
    for code, corridor, crosses, buses in corridors:
        pkg = p.package(f"cor_{code.lower()}", f"Corridor {corridor}", net,
                        doc=f"The {len(crosses)} signalised intersections along {corridor}, in order from the "
                            f"harbour outwards.")
        by_corridor[code] = []
        for i, cross in enumerate(crosses, 1):
            name = f"{corridor} & {cross}"
            key = f"x_{code.lower()}{i:02d}"
            n = names.index(name)
            legs = 3 if rng.random() < 0.25 else 4
            controller = "nx2" if legs == 3 and rng.random() < 0.6 else rng.choice(["atc4", "atc5", "atc5"])
            detector = rng.choice(["loop", "loop", "radar", "video"])
            parts = [("controller", controller), ("detectors", detector, f"{legs}..{legs * 3}"),
                     ("push buttons", "pb", f"{legs * 2}..{legs * 2}"), ("modem", "modem")]
            if buses and rng.random() < 0.7:
                parts.append(("tsp", "tspu"))
            if rng.random() < 0.4 or name in features and "preempt" in features[name]:
                parts.append(("evp", "evp"))
            doc = (f"The signals at {name} ({code}-{i:02d}) control {legs} approaches"
                   + (", with a protected right turn from " + cross if legs == 4 and rng.random() < 0.3 else "")
                   + ". " + features.get(name, ""))
            p.block(key, name, pkg, doc.strip(), parts=parts,
                    values=[("lanes", None, legs * 2 + rng.randint(0, 4)), ("pedestrianPhases", None, legs)])
            year = rng.randint(1984, 2024)
            fw = f"{rng.choice([3, 4])}.{rng.randint(0, 14)}.{rng.randint(0, 9)}"
            p.apply("PCT", "SignalSite", key, siteId=f"PC-{site_ids[n]}", cabinet=f"C-{cabinets[n]}",
                    ward=rng.choice(["Harbourside", "Quarry", "Larkspur", "Northgate", "Tollgate", "Saltings"]),
                    commissioned=year, firmware=fw)
            site[name] = {"key": key, "site": f"PC-{site_ids[n]}", "cabinet": f"C-{cabinets[n]}",
                          "controller": controller, "corridor": code}
            by_corridor[code].append(key)

    # Timing plans: one per corridor and period, each with a cycle length no other plan has.
    p.block("plan", "Timing Plan", plans_pkg, "A coordination plan for one corridor and one period of the day.",
            values=[("cycleLength", vt_s, None), ("startTime", None, None), ("endTime", None, None),
                    ("coordinatedDirection", None, None)])
    cycles = rng.sample(range(50, 180), len(corridors) * len(PLANS))
    plan_cycle: dict[tuple[str, str], tuple[str, int]] = {}
    for c, (code, corridor, crosses, _) in enumerate(corridors):
        for j, (period, start, end) in enumerate(PLANS):
            cycle = cycles[c * len(PLANS) + j]
            pk = f"plan_{code.lower()}_{slug(period)}"
            direction = rng.choice(["inbound", "outbound", "balanced"])
            p.instance(pk, f"{corridor} {period}", "plan", plans_pkg,
                       {"cycleLength": cycle, "startTime": start, "endTime": end, "coordinatedDirection": direction},
                       doc=(f"Runs on {corridor} from {start} to {end}" + (", free and uncoordinated." if period == "Night"
                            else f", favouring {direction} traffic, with offsets referenced to {corridor} & "
                                 f"{crosses[0]}.")))
            plan_cycle[(code, period)] = (pk, cycle)

    # -- central system --------------------------------------------------------------------------
    for key, name, doc, _ in ATMS:
        p.block(key, name, central, doc)
    p.block("ring", "Calder Ring", central,
            "A 48-fibre ring of 38 km linking every signal cabinet to the Calder Traffic Centre, in two directions.")
    p.block("atms", "Harbormaster ATMS", central,
            "The advanced traffic management system at the Calder Traffic Centre, on Wharf Lane.",
            parts=[(name.lower(), key) for key, name, _, _ in ATMS], refs=[("field network", "ring")])

    # -- requirements ----------------------------------------------------------------------------
    numbers = iter(rng.sample(range(2, 99), 90))
    req_keys: dict[str, list[str]] = {}
    req_text: dict[str, str] = {}
    for area, first, texts in AREAS:
        pkg = p.package(f"r_{slug(area)}", area, reqs)
        req_keys[area] = []
        for i, text in enumerate(texts):
            rid = f"PCT-SYS-{first + i * 3 + 1:04d}"
            text = text.format(n=next(numbers)) if "{n}" in text else text
            key = f"sys{first + i * 3 + 1}"
            p.requirement(key, str(52000 + first + i), None, f"[{rid}] {text}", pkg)
            req_keys[area].append(key)
            req_text[key] = text
        for code, corridor, _, buses in CORRIDORS:  # corridor variants: near-duplicate texts
            if area == "Signal Timing" or (area == "Transit Priority" and buses):
                rid_n = first + 50 + [c[0] for c in CORRIDORS].index(code)
                key = f"sys{rid_n}"
                target = rng.choice([45, 50, 55]) if area == "Signal Timing" else rng.choice([8, 10, 12, 15])
                text = (f"On {corridor}, the coordinated plans shall give a progression band of at least {target}% "
                        "of the cycle in the peak direction." if area == "Signal Timing" else
                        f"On {corridor}, a late bus shall clear each intersection within {target} seconds of "
                        "arriving at the stop bar.")
                p.requirement(key, str(52000 + rid_n), None, f"[PCT-SYS-{rid_n:04d}] {text}", pkg)
                req_keys[area].append(key)
                req_text[key] = text
    sub_n = 0  # each ATMS module's requirements, derived from the first two of each area it serves
    for key, name, _, areas in ATMS:
        for area in areas:
            for parent in req_keys[area][:2]:
                sub_n += 1
                sk = f"atms{sub_n:02d}"
                parent_id = f"PCT-SYS-{int(parent[3:]):04d}"
                p.requirement(sk, f"PCT-ATMS-{sub_n:02d}", f"{name} Support for {parent_id}",
                              f"The {name} shall provide what the central system needs to meet {parent_id}.", sub)
                p.relate("deriveReqt", sk, parent, sub)
                p.relate("satisfy", key, sk, sub)

    # -- behaviour -------------------------------------------------------------------------------
    p.activity("evp_act", "Emergency Vehicle Preemption", beh,
               "What a controller does when its Beacon EVP-90 receiver detects an emergency vehicle.", [
                   ("e0", "InitialNode", ""), ("e1", "OpaqueAction", "Receive Strobe Signal"),
                   ("e2", "DecisionNode", ""), ("e3", "OpaqueAction", "Finish Pedestrian Clearance"),
                   ("e4", "MergeNode", ""), ("e5", "OpaqueAction", "Terminate Conflicting Phases"),
                   ("e6", "OpaqueAction", "Hold Green for the Emergency Approach"),
                   ("e7", "OpaqueAction", "Light the White Confirmation Lamp"),
                   ("e8", "OpaqueAction", "Return to Coordination over Two Cycles"),
                   ("e9", "ActivityFinalNode", "")],
               [("e0", "e1"), ("e1", "e2"), ("e2", "e3", "pedestrian clearance running"),
                ("e2", "e4", "no pedestrian clearance"), ("e3", "e4"), ("e4", "e5"), ("e5", "e6"), ("e6", "e7"),
                ("e7", "e8", "strobe lost for 10 seconds"), ("e8", "e9")])
    p.activity("inc_act", "Incident Response Plan Activation", beh,
               "How an operator at the Calder Traffic Centre puts an incident response plan into effect.", [
                   ("i0", "InitialNode", ""), ("i1", "OpaqueAction", "Confirm Incident on CCTV"),
                   ("i2", "OpaqueAction", "Choose Plan from the Incident Manager"),
                   ("i3", "OpaqueAction", "Download Diversion Timings"),
                   ("i4", "OpaqueAction", "Post Messages on Variable Signs"),
                   ("i5", "OpaqueAction", "Notify Calder Transit Control"), ("i6", "ActivityFinalNode", "")],
               [(f"i{k}", f"i{k + 1}") for k in range(6)])
    for key, name in (("sg_power", "Power Restored"), ("sg_conflict", "Conflict Monitor Trip"),
                      ("sg_preempt", "Preemption Request"), ("sg_preend", "Preemption Ended"),
                      ("sg_manual", "Manual Control Request"), ("sg_release", "Manual Release"),
                      ("sg_planfree", "Free Plan Selected"), ("sg_plancoord", "Coordinated Plan Selected"),
                      ("sg_tech", "Technician Reset")):
        p.signal(key, name, beh)
    p.state_machine("modes", "Controller Operating Modes", "atc5",
                    "The modes of a Meridian ATC-5; the ATC-4 and NX-2 follow the same scheme.", [
                        ("m_init", ""), ("m_start", "Startup Flash", "Flash red on all approaches"),
                        ("m_coord", "Coordinated"), ("m_free", "Free"), ("m_pre", "Preemption"),
                        ("m_man", "Manual Control"), ("m_fault", "Fault Flash", "Flash amber on the main road")],
                    [("m_init", "m_start", "sg_power", None),
                     ("m_start", "m_coord", None, "after 8 seconds of startup flash and a valid plan"),
                     ("m_coord", "m_free", "sg_planfree", None), ("m_free", "m_coord", "sg_plancoord", None),
                     ("m_coord", "m_pre", "sg_preempt", None), ("m_free", "m_pre", "sg_preempt", None),
                     ("m_pre", "m_coord", "sg_preend", None), ("m_coord", "m_man", "sg_manual", None),
                     ("m_man", "m_coord", "sg_release", None), ("m_coord", "m_fault", "sg_conflict", None),
                     ("m_fault", "m_start", "sg_tech", "cabinet door closed")])

    # -- diagrams --------------------------------------------------------------------------------
    p.diagram("d_network", "Signal Network Overview", "SysML Block Definition Diagram", net,
              [k for keys in by_corridor.values() for k in keys], cols=15)
    for code, corridor, _, _ in corridors:
        p.diagram(f"d_cor_{code.lower()}", f"Corridor {corridor}", "SysML Block Definition Diagram",
                  f"cor_{code.lower()}", by_corridor[code] + ["atc4", "atc5", "nx2", "loop", "radar", "video"],
                  cols=6)
    p.diagram("d_eq", "Equipment Catalogue", "SysML Block Definition Diagram", eq,
              [k for k, *_ in CONTROLLERS] + [k for k, *_ in DETECTORS] + ["evp", "tspu", "pb", "modem"])
    p.diagram("d_central", "Harbormaster ATMS", "SysML Block Definition Diagram", central,
              ["atms", "ring"] + [k for k, *_ in ATMS])
    for area, _, _ in AREAS:
        p.diagram(f"d_req_{slug(area)}", f"{area} Requirements", "Requirement Diagram", f"r_{slug(area)}",
                  req_keys[area], cols=5)
    p.diagram("d_trace", "ATMS Traceability", "Requirement Diagram", sub,
              [k for k, *_ in ATMS] + [f"atms{i:02d}" for i in range(1, sub_n + 1)], cols=8)
    p.behavior_diagram("d_evp", "Emergency Vehicle Preemption", "evp_act")
    p.behavior_diagram("d_inc", "Incident Response Plan Activation", "inc_act", cols=7)
    p.behavior_diagram("d_modes", "Controller Operating Modes", "modes", cols=3)

    # -- questions -------------------------------------------------------------------------------
    def x(name: str) -> dict:
        return site[name]

    near = [n for n in names if sum(1 for m in names if m.split(" & ")[1] == n.split(" & ")[1]) > 1]
    picks = sorted(rng.sample(near, 4)) + sorted(rng.sample([n for n in names if n not in near], 2))
    for i, name in enumerate(picks, 1):
        hard = "hard" if name in near else "medium"
        p.ask(f"q0{i}", "near-duplicate" if name in near else "tagged-value", hard,
              f"What is the site id of the signals at {name}?",
              f"Under what site number is the junction of {name.replace(' & ', ' and ')} registered?",
              [x(name)["key"]], evidence=f"siteId = {x(name)['site']}")
    for i, name in enumerate(sorted(rng.sample(names, 2)), 7):
        p.ask(f"q0{i}" if i < 10 else f"q{i}", "tagged-value", "medium", f"Which cabinet serves {name}?",
              f"What is the cabinet number for the traffic lights where {name.replace(' & ', ' meets ')}?",
              [x(name)["key"]], evidence=f"cabinet = {x(name)['cabinet']}")
    feature_qs = [
        ("school crossing", "When does the school crossing patrol operate at {name}?",
         "At what times are children helped across the road at {where}?", "08:10 to 08:50"),
        ("Fire Station 3", "Which fire station can preempt the signals at {name}?",
         "Which emergency service has its own button for the lights at {where}?", "Fire Station 3"),
        ("level crossing", "What happens at {name} when a train approaches?",
         "How do the traffic lights at {where} react to a train?", "holds all approaches at red"),
        ("queue jump", "How long is the early green for the bus queue jump lane at {name}?",
         "How much of a head start do buses get at {where}?", "early green of 7 seconds"),
        ("scramble", "When does the pedestrian scramble phase run at {name}?",
         "When can people cross diagonally at {where}?", "every second cycle"),
        ("Flood sensor", "What makes the signals at {name} flash amber?",
         "Why would the lights at {where} switch to flashing in bad weather?", "Flood sensor FS-12"),
        ("Larkspur Library", "Where is the signal cabinet for {name}, and who holds its key?",
         "Where would a technician find the controller box for {where}?", "Larkspur Library forecourt"),
        ("wind sensor", "At what wind speed are the overhead signs at {name} locked?",
         "How strong must the wind be before the signs over {where} are secured?", "above 90 km/h"),
    ]
    for i, (marker, literal, para, evidence) in enumerate(feature_qs, 11):
        name = next(n for n, f in features.items() if marker in f)
        p.ask(f"q{i}", "lookup", "hard", literal.format(name=name),
              para.format(where=name.replace(" & ", " and ")), [x(name)["key"]], evidence=evidence)
    for i, (code, period) in enumerate((("HR", "PM Peak"), ("QS", "AM Peak"), ("SP", "Night"), ("LA", "Midday")), 21):
        pk, cycle = plan_cycle[(code, period)]
        corridor = next(c[1] for c in corridors if c[0] == code)
        p.ask(f"q{i}", "instance", "hard", f"What is the cycle length of the {period} plan on {corridor}?",
              f"How long is one full signal cycle on {corridor} during the {period.lower()} period?",
              [pk], ["plan"], evidence=f"cycleLength = {cycle}")
    by_id = [("Preemption", 2), ("Pedestrians", 2), ("Communications", 3), ("Cybersecurity", 3), ("Maintenance", 2),
             ("Detection", 4)]  # not the first two of an area, which ATMS requirements derive from
    for i, (area, k) in enumerate(by_id, 31):
        key = req_keys[area][k]
        rid = f"PCT-SYS-{int(key[3:]):04d}"
        text = req_text[key]
        evidence = text.rstrip(".").split(" shall ")[1] if " shall " in text else text
        p.ask(f"q{i}", "requirement-by-id", "medium", f"What does requirement {rid} state?", None, [key],
              evidence=evidence[:60])
    p.ask("q41", "lookup", "medium", "How far does the Corvid RD-2 Radar Detector track vehicles?",
          "How far back from the junction can Port Calder's radar sensors see traffic?", ["radar"],
          evidence="up to 150 m")
    p.ask("q42", "lookup", "easy", "How long is the Calder Ring?",
          "How much fibre links Port Calder's traffic signals to the control centre?", ["ring"], evidence="38 km")
    p.ask("q43", "behaviour", "medium",
          "In Emergency Vehicle Preemption, what does the controller do after holding green for the emergency approach?",
          "How does a driver of a fire engine know the lights have been changed for them?", ["evp_act"],
          evidence="Light the White Confirmation Lamp")
    p.ask("q44", "behaviour", "hard", "What puts a Meridian ATC-5 into Fault Flash?",
          "What makes a Port Calder traffic controller give up and flash amber?", ["modes"],
          evidence="Fault Flash — Conflict Monitor Trip")
    p.ask("q45", "behaviour", "hard", "How long does a controller stay in Startup Flash?",
          "How long do the lights flash red after the power comes back?", ["modes"], evidence="after 8 seconds")
    p.ask("q46", "trace", "medium", "Which ATMS component receives bus positions from the fleet system?",
          "Which part of the central system knows where the buses are?", ["tsps", "sys410"],
          evidence=["Receives bus positions from the Calder Transit", "Transit Priority Server shall receive bus positions"])
    p.ask("q47", "behaviour", "medium", "What is the first step of Incident Response Plan Activation?",
          "What does a traffic centre operator do first when told of a crash?", ["inc_act"],
          evidence="Confirm Incident on CCTV")
    return p
