"""References outside a project, named from the OMG libraries and the cached copies of used
projects (plan UL)."""

from fixture_model import EXTERNAL, LAYOUT_EXTERNAL, MODEL_EXTERNAL, STRING_14, make_mdzip
from helpers import project_dir, run

from cameo_ingest import semantics as sem
from cameo_ingest.archive import discover
from cameo_ingest.external import external_label, omg_name
from cameo_ingest.pipeline import parse_project


def test_omg_names():
    assert omg_name(STRING_14) == "String"
    assert omg_name("http://www.omg.org/spec/SysML/20181001/SysML.xmi#SysML_dataType.Real") == "Real"
    assert omg_name("http://www.omg.org/spec/SysML/20181001/SysML.xmi#SysML_dataType.VerdictKind.pass") == "pass"
    assert omg_name("http://www.omg.org/spec/SysML/20181001/SysML.xmi#SysML.Block") == "Block"
    assert omg_name("http://www.omg.org/spec/UML/20131001/UML.xmi#_0") == "UML"
    assert omg_name("http://www.omg.org/spec/UML/20131001/UML.xmi#Class") == "Class"
    assert omg_name("Lib.mdzip#_lib_motor") is None
    assert external_label({}, "Lib.mdzip#_lib_motor") == "_lib_motor"  # no proxy: the id, as before


def test_labels_from_used_projects(tmp_path):
    """A part's type, a tagged value and a diagram's shape read with their names; a proxy is
    read for names only, never ingested as a project."""
    data = make_mdzip(MODEL_EXTERNAL, LAYOUT_EXTERNAL, EXTERNAL)
    ix = parse_project(next(discover(data, "drone.mdzip")))
    assert ix.external == {"_lib_root": "Parts Library", "_lib_motor": "Brushless Motor", "_lib_cell": "Lithium Cell"}
    assert [sem.label(ix, t) for x in ("x1", "x2", "x3") for r, t in ix.elements[x].refs if r == "type"] == [
        "String", "Real", "Brushless Motor"]
    out = run(tmp_path, "drone.mdzip", data)
    assert len(list((out / "by-sha256").glob("[0-9a-f]*"))) == 1  # the proxy is not a project
    pkg = (project_dir(out) / "packages/Model__Structure.md").read_text()
    assert "serial** : String" in pkg and "mass** : Real" in pkg and "motor** : Brushless Motor" in pkg, pkg
    assert "«Trace» supplier = Lithium Cell" in pkg
    assert "_SysML_Libraries" not in pkg and "_lib_" not in pkg
    dia = (project_dir(out) / "diagrams/Drone_BDD.md").read_text()
    assert "Class: Brushless Motor" in dia, dia


def test_a_damaged_proxy_leaves_the_ids(tmp_path):
    from fixture_model import PROXY

    data = make_mdzip(MODEL_EXTERNAL, LAYOUT_EXTERNAL, {PROXY: "<xmi:XMI><uml:Package"})
    ix = parse_project(next(discover(data, "drone.mdzip")))
    assert ix.external == {} and ix.label("Lib.mdzip#_lib_motor") == "_lib_motor"
    assert run(tmp_path, "drone.mdzip", data).is_dir()  # the project is written all the same
