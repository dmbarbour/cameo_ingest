"""How elements, requirements and relationships are named: one vocabulary (AR-010, AR-011)."""

from cameo_ingest import semantics as sem
from cameo_ingest.model import Element, ModelIndex, StereotypeApplication


def model() -> ModelIndex:
    ix = ModelIndex()

    def el(id_: str, kind: str, name: str | None = None, **kw) -> Element:
        e = Element(id_, f"uml:{kind}", "packagedElement", name, None, "e", None, **kw)
        ix.elements[id_] = e
        return e

    def stereotype(base: str, name: str, **tags: str) -> None:
        app = StereotypeApplication(f"st-{base}-{name}", f"p:{name}", "", base, {k: [v] for k, v in tags.items()}, "e",
                                    None)
        ix.stereotypes[app.id] = app
        ix.elements[base].stereotypes.append(app.id)

    el("named", "Class", "Endurance")
    stereotype("named", "Requirement", Id="R-1", Text="The drone shall fly 30 min.")
    el("doors", "Class")  # a DOORS import: no name, a database number, the id in the text
    stereotype("doors", "TMT_Requirement", Id="16001", Text="[RWT-REG-001] The turbidity shall stay low.")
    el("blk", "Class", "Battery")
    stereotype("blk", "Block")
    el("dia", "Class", "Drone BDD")
    stereotype("dia", "DiagramInfo")
    el("act", "OpaqueAction", attrs={"body": "j = 1"})
    el("call", "CallBehaviorAction", refs=[("behavior", "blk")])
    el("bare", "Class")
    return ix


def test_requirements_read_one_way():
    ix = model()
    named, doors = sem.requirement(ix, ix.elements["named"]), sem.requirement(ix, ix.elements["doors"])
    assert (named.id, named.db_id, named.title) == ("R-1", None, "Endurance (R-1)")
    # The id in the text is the one people use; the tag is then a database number.
    assert (doors.id, doors.db_id, doors.text) == ("RWT-REG-001", "16001", "The turbidity shall stay low.")
    from cameo_ingest.text import requirement_title

    assert requirement_title(None, "11130", "- [REQ-1-OAD-1050] Focal length") == "REQ-1-OAD-1050: Focal length"
    assert doors.title == "RWT-REG-001: The turbidity shall stay low."
    assert sem.requirement(ix, ix.elements["blk"]) is None


def test_labels_and_kind_words():
    ix = model()
    assert [sem.label(ix, i) for i in ("named", "doors", "blk", "act", "call", "bare")] == [
        "Endurance (R-1)", "RWT-REG-001: The turbidity shall stay low.", "Battery", "j = 1", "Battery",
        "(unnamed Class)"]
    assert sem.label(ix, "used.mdzip#_lib_ValueType") == "_lib_ValueType"  # a reference into a used project
    assert sem.own_name(ix, ix.elements["bare"]) == ""  # a diagram then shows a typed element by its type
    assert [sem.kind_word(ix, ix.elements[i]) for i in ("doors", "blk", "dia", "bare")] == [
        "Requirement", "Block", "Class", "Class"]  # «DiagramInfo» is never a kind


def test_relationship_wording():
    assert sem.wording("Satisfy", "Abstraction") == sem.Wording("satisfies", "satisfied by")
    assert sem.wording("", "Abstraction").forward == "depends on"  # the metaclass when no stereotype has one
    assert sem.wording("copy").forward == "is a copy of"
    assert sem.wording("Association") is None
