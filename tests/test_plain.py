"""Plain chunk text: headings, parts within a token budget, and only emit's markup removed."""


def test_plain_chunk_text():
    """The plain chunk style (plan RE-08): links to labels, no traces or marks, meaning before
    details (apart when long), parts that repeat their heading, readable requirement titles."""
    from cameo_ingest import plain as pl
    from cameo_ingest.text import requirement_title

    md = ("## «Requirement» (unnamed)\n\n- **Kind:** Class\n- **Qualified name:** `M::P::Q::R`\n"
          "- **Requirement ID:** 16890\n\n**Requirement text:**\n\n> [REQ-1-OAD-0468] Tip/tilt error budget\n\n"
          "**Tagged values:**\n- «TMT_Requirement» Rationale = \\[CR163\\] latest results\n\n"
          "**Relationships:**\n- Satisfy: [Drone](../p.md#drone-b1) satisfies this\n\n"
          "<sub>trace: `sha256:x!e#r@L1`</sub>\n")
    meaning, details = pl.section(md, "Requirement X in P (project p)")
    assert meaning == [("Requirement X in P (project p)\n\nRequirement ID: 16890\n"
                       "Requirement text: [REQ-1-OAD-0468] Tip/tilt error budget\n"
                       "Relationships:\n- Satisfy: Drone satisfies this\n"
                       "Tagged values:\n- «TMT_Requirement» Rationale = [CR163] latest results")] and not details
    long_values = md.replace("latest results", "latest results " + "word " * 250 + "\n- Note = " + "word " * 250)
    meaning, details = pl.section(long_values, "Requirement X in P (project p)")
    assert meaning[0].endswith("Drone satisfies this") and len(details) == 2
    assert details[0].startswith("Requirement X in P (project p), details (part 1 of 2)\n\nTagged values:\n")
    # Parts are budgeted in estimated tokens: ids make more tokens per character than prose.
    assert pl.tokens("The pump lifts water.") < pl.tokens("_2021x_2_1b400495_1742239490487") < 40
    assert requirement_title(None, "16890", "[REQ-1-OAD-0468] Tip/tilt error budget") == \
        "REQ-1-OAD-0468: Tip/tilt error budget"
    assert requirement_title("Endurance", "R-1", "The drone shall fly.") == "Endurance (R-1)"
    assert pl.where("A::B::C::D", "x.mdzip") == "in B::C::D (project x.mdzip)"
    long = pl.parts("H", "\n".join(f"line {i} " + "word " * 20 for i in range(40)), budget=300)
    assert len(long) > 2 and all(p.startswith("H (part ") and pl.tokens(p) <= 300 for p in long)
    cut = pl.parts("H", "x" * 3000, budget=300)  # a line too long for any part is cut into parts that fit
    assert len(cut) > 1 and all(pl.tokens(p) <= 300 for p in cut) and sum(p.count("x") for p in cut) == 3000
    nested = pl.parts("H", "- root\n" + "\n".join(f"  - child {i} " + "word " * 20 for i in range(12)), budget=150)
    assert len(nested) > 2 and all(p.split("\n\n", 1)[1].startswith("  - child") for p in nested[1:])  # nesting kept
    # Only emit's markup goes; model text keeps its operators, quotes and '#' lines (AR-003).
    md = ("### Constraint Mass\n\n- **Kind:** Constraint\n\n**Documentation:**\n\n#1 priority is safety.\n"
          "> 5 bar: trip\nx**2 + y**2 < r**2\n\n**Requirement text:**\n\n> > 5 bar: trip\n\n"
          "**Specification (OCL2.0):**\n\n```\nself.mass <= 2 * self.tare * 1.5\n```\n\n"
          "**Members:**\n- *part* Property **pump\\*2** : [Pump](p.md#pump)\n\n"
          "**Table / matrix configuration** (rows are computed by Cameo):\n- «DiagramTable» scope = P\n\n"
          "**Summary** _(rule-based; not part of the source model)_:\n\nIt weighs *little*.\n")
    header, bs = pl.blocks(md)
    assert header == ["- **Kind:** Constraint"]
    assert [n for n, _ in bs] == ["Documentation", "Requirement text", "Specification (OCL2.0)", "Members",
                                  "Table / matrix configuration", "Summary"], bs
    meaning, _ = pl.section(md, "Constraint Mass (project p)")
    assert meaning == [("Constraint Mass (project p)\n\nDocumentation:\n#1 priority is safety.\n> 5 bar: trip\n"
                        "x**2 + y**2 < r**2\nRequirement text: > 5 bar: trip\n"
                        "Specification (OCL2.0): self.mass <= 2 * self.tare * 1.5\n"
                        "Table / matrix configuration:\n- «DiagramTable» scope = P\nSummary: It weighs *little*.\n"
                        "Members:\n- part Property pump*2 : Pump")], meaning
    assert pl.plain("- **16001** [R-1](l.md#r) — “a * b * c”") == "- 16001 R-1 — “a * b * c”"
