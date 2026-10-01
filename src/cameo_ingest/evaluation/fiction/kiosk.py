"""Ashgrove Library Book Return Kiosk: a small project (about 190 XMI ids), easy questions.

Every name and figure is invented. The facts sit in documentation, requirement text, one
activity and one state machine; the questions use the model's own words, or a plain paraphrase.
"""

from __future__ import annotations

from .builder import Project


def build() -> Project:
    p = Project("Ashgrove Library Book Return Kiosk", "abk")
    st = p.package("st", "Kiosk Structure", doc="The parts of the Book Return Kiosk and what passes between them.")
    rq = p.package("rq", "Kiosk Requirements")
    bh = p.package("bh", "Kiosk Behavior")

    mm = p.value_type("mm", "millimetres", st, unit="mm")
    bpm = p.value_type("bpm", "items per minute", st, unit="item/min")
    p.block("item", "Library Item", st, "Any book, audiobook or DVD carrying an Ashgrove library tag.")
    p.block("tagdata", "Tag Data", st, "The item number and branch code read from a library tag.")
    p.block("slot", "Drop Slot", st,
            ("The Drop Slot is a spring-loaded flap 380 mm wide in the library's front wall. It admits one item at "
             "a time, and a light curtain behind it detects each item as it passes."),
            values=[("slotWidth", mm, 380), ("sillHeight", mm, 960)],
            ports=[("item out", None)])
    p.block("reader", "Tag Reader", st,
            ("The Tag Reader is a Tallis R2 RFID reader. It reads the library tag inside each item and checks the "
             "item in with the catalogue."),
            ports=[("item in", None), ("tag out", None)])
    p.block("conveyor", "Sorting Conveyor", st,
            "A belt conveyor with three diverter paddles that sends each item to its bin.",
            values=[("beltSpeed", None, "0.4 m/s")], ports=[("item in", None)])
    p.block("bins", "Bin Array", st,
            ("Four wheeled bins: Adult Fiction, Junior, Media and Holds. The Holds bin has a red liner, so that "
             "staff see reserved items first. Items that can't be identified drop into the Exceptions Tray."))
    p.block("printer", "Receipt Printer", st,
            "A thermal printer that lists the items returned, unless the patron taps No Receipt.")
    p.block("pc", "Kiosk Computer", st,
            "A fanless Juniper Mini computer running the ShelfLink kiosk software, version 5.3.",
            ports=[("tag in", None)])
    p.block("kiosk", "Book Return Kiosk", st,
            ("The Book Return Kiosk at Ashgrove Library takes back borrowed items through the front wall, day and "
             "night, sorts them and prints a receipt."),
            values=[("throughput", bpm, 9)],
            parts=[("slot", "slot"), ("reader", "reader"), ("conveyor", "conveyor"), ("bins", "bins"),
                   ("printer", "printer"), ("computer", "pc")])
    p.connector("kiosk", "item path", ("slot", "item out"), ("reader", "item in"), items=["item"])
    p.connector("kiosk", "tag link", ("reader", "tag out"), ("computer", "tag in"), items=["tagdata"])
    p.connector("kiosk", None, ("reader", None), ("conveyor", "item in"), items=["item"])

    p.requirement("r1", "ABK-1", "Return Throughput", "The kiosk shall accept at least 9 items per minute.", rq)
    p.requirement("r2", "ABK-2", "Unreadable Tags",
                  "The kiosk shall send any item whose tag can't be read to the Exceptions Tray.", rq)
    p.requirement("r3", "ABK-3", "Receipt Choice", "The kiosk shall let the patron decline a printed receipt.", rq)
    p.requirement("r4", "ABK-4", "Jam Alert",
                  "The kiosk shall alert the duty librarian within 30 seconds of a conveyor jam.", rq)
    p.requirement("r5", "ABK-5", "Slot Height",
                  "The drop slot shall be no higher than 1,050 mm above the pavement, for wheelchair users.", rq)
    p.requirement("r6", "ABK-6", "Opening Hours",
                  ("The kiosk shall accept returns at all hours, except in the weekly maintenance window on Tuesdays "
                   "from 06:00 to 06:30."), rq)
    for block, req in (("conveyor", "r1"), ("reader", "r2"), ("printer", "r3"), ("pc", "r4"), ("slot", "r5")):
        p.relate("satisfy", block, req, rq)

    p.activity("return", "Return an Item", bh, "What the kiosk does with each item put through the slot.", [
        ("a0", "InitialNode", ""), ("a1", "OpaqueAction", "Detect Item at Slot"), ("a2", "OpaqueAction", "Read Tag"),
        ("a3", "DecisionNode", ""), ("a4", "OpaqueAction", "Check In Item"), ("a5", "OpaqueAction", "Choose Bin"),
        ("a6", "OpaqueAction", "Divert to Bin"), ("a7", "OpaqueAction", "Send to Exceptions Tray"),
        ("a8", "MergeNode", ""), ("a9", "OpaqueAction", "Print Receipt"), ("a10", "ActivityFinalNode", "")],
        [("a0", "a1"), ("a1", "a2"), ("a2", "a3"), ("a3", "a4", "tag read"), ("a3", "a7", "no tag"),
         ("a4", "a5"), ("a5", "a6"), ("a6", "a8"), ("a7", "a8"), ("a8", "a9"), ("a9", "a10")])
    for action, block in (("a2", "reader"), ("a6", "conveyor"), ("a9", "printer")):
        p.relate("allocate", action, block, bh)

    for key, name in (("sg_item", "Item Detected"), ("sg_binned", "Item Binned"), ("sg_jam", "Jam Detected"),
                      ("sg_clear", "Jam Cleared"), ("sg_mstart", "Maintenance Start"),
                      ("sg_mend", "Maintenance End")):
        p.signal(key, name, bh)
    p.state_machine("modes", "Kiosk Modes", "kiosk", "The kiosk's modes of operation.", [
        ("m_init", ""), ("m_idle", "Idle"), ("m_acc", "Accepting", "Open the flap"),
        ("m_sort", "Sorting"), ("m_jam", "Jammed", "Page the duty librarian"),
        ("m_oos", "Out of Service", "Show the closed sign")],
        [("m_init", "m_idle", None, None), ("m_idle", "m_acc", "sg_item", None),
         ("m_acc", "m_sort", None, "tag read or no tag"), ("m_sort", "m_idle", "sg_binned", None),
         ("m_sort", "m_jam", "sg_jam", None), ("m_jam", "m_idle", "sg_clear", None),
         ("m_idle", "m_oos", "sg_mstart", None), ("m_oos", "m_idle", "sg_mend", None)])

    p.diagram("d_bdd", "Kiosk Structure", "SysML Block Definition Diagram", st,
              ["kiosk", "slot", "reader", "conveyor", "bins", "printer", "pc"], cols=6)
    p.ibd("d_ibd", "Kiosk Item Path", "kiosk")
    p.diagram("d_req", "Kiosk Requirements", "Requirement Diagram", rq,
              ["r1", "r2", "r3", "r4", "r5", "r6", "conveyor", "reader", "printer", "pc", "slot"], cols=6)
    p.behavior_diagram("d_return", "Return an Item", "return")
    p.behavior_diagram("d_modes", "Kiosk Modes", "modes", cols=3)

    p.ask("q01", "lookup", "easy", "Which RFID reader does the Book Return Kiosk use?",
          "What device identifies each book that is handed back?", ["reader"], evidence="Tallis R2")
    p.ask("q02", "parameter", "easy", "How wide is the Drop Slot?",
          "How big is the opening that returned books go through?", ["slot"], evidence="380 mm")
    p.ask("q03", "lookup", "easy", "Which bins make up the Bin Array?",
          "Where do returned items end up after they are sorted?", ["bins"], evidence="Adult Fiction")
    p.ask("q04", "lookup", "medium", "Why does the Holds bin have a red liner?",
          "How do staff spot reserved books among the returns?", ["bins"], evidence="red liner")
    p.ask("q05", "parameter", "easy", "How many items per minute must the kiosk accept under ABK-1?",
          "How fast must the library's return machine take books in?", ["r1"], ["conveyor"],
          evidence="9 items per minute")
    p.ask("q06", "requirement-by-id", "medium", "What does requirement ABK-4 state?",
          "How quickly must someone be told when the return conveyor gets stuck?", ["r4"], ["pc"],
          evidence="30 seconds")
    p.ask("q07", "trace", "medium", "Which block satisfies ABK-5, Slot Height?",
          "Which part of the kiosk must stay within reach of wheelchair users?", ["slot", "r5"], [],
          evidence=["Drop Slot satisfies", "satisfies Slot Height", "satisfies [Slot Height]"])
    p.ask("q08", "behaviour", "medium", "In Return an Item, what happens when there is no tag?",
          "What does the kiosk do with a book it can't identify?", ["return"], ["r2"],
          evidence="Send to Exceptions Tray")
    p.ask("q09", "behaviour", "medium", "What does the kiosk do in the Jammed state?",
          "Who is called when the return machine's belt gets stuck?", ["modes"], ["r4"],
          evidence="Page the duty librarian")
    p.ask("q10", "lookup", "easy", "Which software does the Kiosk Computer run?",
          "What program drives the library's self-service book drop?", ["pc"], evidence="ShelfLink")
    p.ask("q11", "parameter", "medium", "When is the kiosk's weekly maintenance window?",
          "At what time each week is the book drop closed for upkeep?", ["r6"], evidence="06:00 to 06:30")
    return p
