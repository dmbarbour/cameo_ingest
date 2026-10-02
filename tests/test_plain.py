"""Plain chunk text: headings, parts within a token budget, and only emit's markup removed."""


def test_plain_chunk_text():
    """The plain chunk style (plan RE-08): references by their labels, no traces or marks, meaning
    before details (apart when long), parts that repeat their heading, readable requirement
    titles. A section is built once and rendered twice, for the page and for chunks (AR-003R2)."""
    from cameo_ingest import plain as pl
    from cameo_ingest import sections as sx
    from cameo_ingest.text import md_inline, requirement_title

    def link(id_: str, label: str) -> str:
        return f"[{md_inline(label)}](../p.md#{id_})"

    def requirement(values: str) -> sx.Section:
        return sx.Section(sx.line("«Requirement» ", sx.name("(unnamed)")), [
            ("Kind", sx.line("Class")), ("Qualified name", sx.line(sx.Span("M::P::Q::R", "code"))),
            ("Requirement ID", sx.line("16890"))], [
            sx.Block("Requirement text", [sx.line("[REQ-1-OAD-0468] Tip/tilt error budget")], quoted=True),
            sx.Block("Tagged values", [sx.line(f"- «TMT_Requirement» Rationale = {values}")], form="list", detail=True),
            sx.Block("Relationships", [sx.line("- Satisfy: ", sx.ref("drone-b1", "Drone"), " satisfies this")],
                     form="list")])

    view = requirement("[CR163] latest results")
    assert view.markdown(2, link) == [
        "## «Requirement» (unnamed)", "", "- **Kind:** Class", "- **Qualified name:** `M::P::Q::R`",
        "- **Requirement ID:** 16890", "", "**Requirement text:**", "", "> [REQ-1-OAD-0468] Tip/tilt error budget", "",
        "**Tagged values:**", "- «TMT_Requirement» Rationale = [CR163] latest results", "",
        "**Relationships:**", "- Satisfy: [Drone](../p.md#drone-b1) satisfies this", ""]
    meaning, details = view.plain("Requirement X in P (project p)")
    assert meaning == [("Requirement X in P (project p)\n\nRequirement ID: 16890\n"
                       "Requirement text: [REQ-1-OAD-0468] Tip/tilt error budget\n"
                       "Relationships:\n- Satisfy: Drone satisfies this\n"
                       "Tagged values:\n- «TMT_Requirement» Rationale = [CR163] latest results")] and not details
    meaning, details = requirement("latest " + "word " * 250 + "\n- Note = " + "word " * 250).plain(
        "Requirement X in P (project p)")
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
    # Model text is never parsed for markup: it keeps its operators, quotes and '#' lines (AR-003).
    view = sx.Section(sx.line(sx.name("Mass")), [("Kind", sx.line("Constraint"))], [
        sx.Block("Documentation", [sx.line("#1 priority is safety.\n> 5 bar: trip\nx**2 + y**2 < r**2")]),
        sx.Block("Specification (OCL2.0)", [sx.line("self.mass <= 2 * self.tare * 1.5")], fenced=True),
        sx.Block("Members", [sx.line("- ", sx.Span("part", "italic"), " Property ", sx.name("pump*2", "bold"), " : ",
                                     sx.ref("pump", "Pump"))], form="list", detail=True),
        sx.Block("Summary", [sx.line("It weighs *little*.")], label="**Summary** _(rule-based; not part of the "
                                                                    "source model)_:")])
    assert "- *part* Property **pump\\*2** : [Pump](../p.md#pump)" in view.markdown(3, link)
    assert view.markdown(3, link)[-4:] == ["**Summary** _(rule-based; not part of the source model)_:", "",
                                           "It weighs *little*.", ""]
    assert view.plain("Constraint Mass (project p)")[0] == [(
        "Constraint Mass (project p)\n\nDocumentation:\n#1 priority is safety.\n> 5 bar: trip\nx**2 + y**2 < r**2\n"
        "Specification (OCL2.0): self.mass <= 2 * self.tare * 1.5\nSummary: It weighs *little*.\n"
        "Members:\n- part Property pump*2 : Pump")]
    assert pl.plain("- **16001** [R-1](l.md#r) — “a * b * c”") == "- 16001 R-1 — “a * b * c”"


def test_pack_and_chunk_records():
    """One packer for ledger rows, and chunk records checked where they are made (AR-015)."""
    import pytest

    from cameo_ingest import chunks
    from cameo_ingest import plain as pl

    rows = [(i, f"- row {i} " + "word " * 30) for i in range(10)]
    parts = pl.pack(rows, "A header", budget=200, max_rows=3)
    assert [k for p in parts for k, _ in p] == list(range(10)) and all(1 <= len(p) <= 3 for p in parts)
    assert all(pl.tokens("A header") + sum(pl.tokens(r) + 1 for _, r in p) <= 200 for p in parts if len(p) > 1)
    meta = {"kind": "element", "file": "p.md", "content": "sha256:ab12",
            "provenance": {"locator": "sha256:ab12!e#x@L1", "derivation": {"method": "extracted"}}}
    c = chunks.make(("ab12", "element", "x", ""), "T", "text", meta)
    assert c["id"] == chunks.chunk_id("ab12", "element", "x", "") and list(c) == ["id", "title", "text", "metadata"]
    with pytest.raises(ValueError, match="trace that starts from the project's content"):
        chunks.make(("x",), "T", "text", {**meta, "provenance": {**meta["provenance"], "locator": "elsewhere"}})
    with pytest.raises(ValueError, match="metadata.file"):
        chunks.make(("x",), "T", "text", {k: v for k, v in meta.items() if k != "file"})
