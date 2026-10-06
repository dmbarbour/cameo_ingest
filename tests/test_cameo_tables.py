"""Cameo's tables, computed as Cameo shows them (plan CT)."""

import csv
import json

from fixture_model import MODEL, make_mdzip
from helpers import check_invariants, project_dir, run

# The fixture's requirements table, configured as Cameo writes it: a second requirement, a tag on
# the first, columns with one hidden and one Cameo computes from an expression, and a sort.
TABLE = """ <MagicDraw_Profile:DiagramTable xmi:id='st7' base_Diagram='d2' displayMode='List' rowElements='r1 r2'
   showElementNumber='true'>
  <columnIds>_NUMBER_</columnIds><columnIds>QPROP:Element:Id</columnIds><columnIds>QPROP:Element:name</columnIds>
  <columnIds>QPROP:Element:Text</columnIds><columnIds>QPROP:Element:SatisfiedBy</columnIds>
  <columnIds>QPROP:Element:owner</columnIds><columnIds>QPROP:Element:Driving</columnIds>
  <columnIds>CUSTOM_COLUMN:Risk</columnIds>
  <hideColumns>QPROP:Element:owner</hideColumns>
  <sort>QPROP:Element:Id^Desc</sort>
  <rowElementType href='http://www.omg.org/spec/SysML/20181001/SysML.xmi#SysML.Requirement'/>
 </MagicDraw_Profile:DiagramTable>
"""


def table_model() -> str:
    start = MODEL.index(" <MagicDraw_Profile:DiagramTable xmi:id='st7'")
    end = MODEL.index("</MagicDraw_Profile:DiagramTable>\n") + len("</MagicDraw_Profile:DiagramTable>\n")
    model = MODEL[:start] + TABLE + MODEL[end:]
    model = model.replace("<packagedElement xmi:type='uml:Class' xmi:id='r1' name='Endurance'/>",
                          "<packagedElement xmi:type='uml:Class' xmi:id='r1' name='Endurance'/>\n"
                          "   <packagedElement xmi:type='uml:Class' xmi:id='r2' name='Range'/>")
    model = model.replace("<sysml:Requirement xmi:id='st3' base_Class='r1' Id='R-1'",
                          "<sysml:Requirement xmi:id='st9' base_Class='r2' Id='R-10' Text='The drone shall fly 12 km.'/>\n"
                          " <sysml:Requirement xmi:id='st3' base_Class='r1' Id='R-1' Driving='Yes'")
    assert model.count("xmi:id='r2'") == 1 and model.count("Driving='Yes'") == 1
    return model


def test_a_requirement_table_computed(tmp_path):
    """Visible columns in order, rows sorted as configured (R-10 after R-1 in descending order,
    numbers compared as numbers), a relationship column and a tag column filled, a custom column
    kept but marked; on the page, in a CSV and in chunks."""
    out = run(tmp_path, "drone.mdzip", make_mdzip(table_model()))
    check_invariants(out)
    proj = project_dir(out)
    page = (proj / "diagrams/Req_Table.md").read_text()
    assert ("Columns: #, Id, Name, Text, Satisfied By, Driving, Risk. Sorted by Id, descending. "
            "Row types: Requirement. Rows: 2, as the table lists them. "
            "Not computed here (Cameo computes them): Risk.") in page, page
    assert "| # | Id | Name | Text | Satisfied By | Driving | Risk |" in page
    rows = [line for line in page.splitlines() if line.startswith(("| 1 |", "| 2 |"))]
    assert rows[0].startswith("| 1 | R-10 | [Range](") and "The drone shall fly 12 km." in rows[0]
    assert rows[1].startswith("| 2 | R-1 | [Endurance](") and "The drone shall fly 30 min." in rows[1]
    assert "[Battery](" in rows[1] and "| Yes |" in rows[1] and "Owner" not in page.split("**Rows")[1]

    with (proj / "tables/diagram-tables/Req_Table.csv").open() as f:
        table = list(csv.DictReader(f))
    assert [(r["#"], r["Id"], r["Name"], r["Satisfied By"], r["Driving"]) for r in table] == [
        ("1", "R-10", "Range", "", ""), ("2", "R-1", "Endurance", "Battery", "Yes")]
    assert table[0]["id"] == "r2" and table[0]["trace"].startswith("sha256:")

    chunks = [json.loads(line) for line in (proj / "index/chunks.jsonl").open()]
    [rows_chunk] = [c for c in chunks if c["metadata"].get("element_id") == "d2" and "- 1. " in c["text"]]
    assert "- 1. Id: R-10; Name: Range; Text: The drone shall fly 12 km." in rows_chunk["text"]
    assert "- 2. Id: R-1; Name: Endurance; Text: The drone shall fly 30 min.; Satisfied By: Battery; Driving: Yes" \
        in rows_chunk["text"]


def test_an_instance_table(tmp_path):
    """An instance table's attribute column reads the rows' slots (`IColumn:<feature id>`), headed
    by the attribute's name; a reference column links its element."""
    instance = ("<packagedElement xmi:type='uml:InstanceSpecification' xmi:id='i1' name='drone1' classifier='b1'>"
                "<slot xmi:type='uml:Slot' xmi:id='sl1' definingFeature='a1'>"
                "<value xmi:type='uml:LiteralString' xmi:id='sv1' value='B-7'/></slot></packagedElement>\n")
    diagram = ("<ownedDiagram xmi:type='uml:Diagram' xmi:id='d4' name='Drones' ownerOfDiagram='p1'>"
               "<xmi:Extension extender='MagicDraw UML 2024x'><diagramRepresentation>"
               "<diagram:DiagramRepresentationObject xmlns:diagram='http://www.nomagic.com/ns/magicdraw/core/diagram/1.0' "
               "type='Instance Table' umlType='Class Diagram'><diagramContents><binaryObject/></diagramContents>"
               "</diagram:DiagramRepresentationObject></diagramRepresentation></xmi:Extension></ownedDiagram>\n")
    config = ("<MagicDraw_Profile:InstanceTable xmi:id='st11' base_Diagram='d4' rowElements='i1' classifiers='b1'>"
              "<columnIds>_NUMBER_</columnIds><columnIds>QPROP:Element:name</columnIds>"
              "<columnIds>QPROP:Element:classifier</columnIds><columnIds>IColumn:a1</columnIds>"
              "</MagicDraw_Profile:InstanceTable>\n")
    model = MODEL.replace("<packagedElement xmi:type='uml:Class' xmi:id='b2' name='Battery'/>",
                          instance + "<packagedElement xmi:type='uml:Class' xmi:id='b2' name='Battery'/>")
    model = model.replace("    </ownedDiagram>\n    </modelExtension>", "    </ownedDiagram>\n" + diagram
                          + "    </modelExtension>", 1)
    model = model.replace("</xmi:XMI>", config + "</xmi:XMI>")
    assert all(model.count(x) == 1 for x in ("xmi:id='i1'", "xmi:id='d4'", "xmi:id='st11'"))
    proj = project_dir(run(tmp_path, "drone.mdzip", make_mdzip(model)))
    page = (proj / "diagrams/Drones.md").read_text()
    assert "Columns: #, Name, Classifier, battery. Rows: 1, as the table lists them." in page, page
    assert "| 1 | [drone1](" in page and "| [Drone](" in page and "| B-7 |" in page


def test_headers_order_and_values():
    from cameo_ingest import cameo_tables as ct

    assert ct._words("SatisfiedBy") == "Satisfied By" and ct._words("hierarchyId") == "Hierarchy Id"
    assert ct._natural("REQ-2") < ct._natural("REQ-10") and ct._natural("b") > ct._natural("A")
    assert ct._once([ct.Value("Key"), ct.Value("Key")]) == [ct.Value("Key")]  # one tag on two stereotypes


def test_a_table_not_computed_says_why(tmp_path):
    """A table that finds its rows in a scope lists none in the file: its page says what isn't
    shown and why, and the catalog, the workbook and the search page report it (plan CT)."""
    import xlsx
    from helpers import cli

    model = table_model().replace("rowElements='r1 r2'", "scope='p2'")
    out = run(tmp_path, "drone.mdzip", make_mdzip(model))
    proj = project_dir(out)
    page = (proj / "diagrams/Req_Table.md").read_text()
    assert ("**Not computed:**\n\nCameo finds this table's rows in its scope whenever it shows the table, and the model "
            "file doesn't store them, so its rows and cells aren't shown here. Its configuration follows.") in page, page
    assert "**Rows" not in page and "**Table / matrix configuration**" in page
    assert not (proj / "tables/diagram-tables").exists()
    records = [json.loads(line) for line in (proj / "index/catalog.jsonl").open()]
    assert records[0]["tables"] == {"not computed": 1}
    assert next(r for r in records if r.get("key") == "d2")["table"] == "not computed: rows from scope"
    book = tmp_path / "catalog.xlsx"
    assert cli(["export", "-o", str(out), "--workbook", str(book), "--search-page", str(tmp_path / "s.html")]) == 0
    sheets = xlsx.sheets(book)
    assert ["Not computed", "1"] in [row[:2] for row in sheets["About"]]
    assert any("not computed: rows from scope" in (row or []) for row in sheets["Diagrams"])
    assert "tables not computed 1" in str(sheets["Projects"])
    assert "Tables show their rows only where the model file lists them" in (tmp_path / "s.html").read_text()


def test_a_matrix_described_not_computed():
    """A matrix says what it relates, from its configuration alone: rows, columns, what a cell
    marks and which way, and which rows and columns it shows (ADR-0025)."""
    from cameo_ingest import cameo_tables as ct

    criteria = ('<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\n<callExpressionSpecification '
                'xmlns="http://www.nomagic.com/schemas/MagicDraw/StructuredExpression/2013"><taggedValues><entry '
                'key="name"><value>Satisfy</value></entry></taggedValues></callExpressionSpecification>')
    config = ("<MagicDraw_Profile:DependencyMatrix xmi:id='st12' base_Diagram='d2' direction='Column to row' "
              "showElements='With relations' rowScope='p2'>"
              "<columnScope xmi:idref='p1'/><columnScope href='Lib.mdzip#_lib_root'/>"
              "<rowElementType href='http://www.omg.org/spec/SysML/20181001/SysML.xmi#SysML.Requirement'/>"
              "<columnElementType href='http://www.omg.org/spec/SysML/20181001/SysML.xmi#SysML.Block'/>"
              f"<dependencyCriteria>{criteria.replace('<', '&lt;').replace('>', '&gt;')}</dependencyCriteria>"
              "</MagicDraw_Profile:DependencyMatrix>\n")
    start = MODEL.index(" <MagicDraw_Profile:DiagramTable xmi:id='st7'")
    end = MODEL.index("</MagicDraw_Profile:DiagramTable>\n") + len("</MagicDraw_Profile:DiagramTable>\n")
    model = (MODEL[:start] + config + MODEL[end:]).replace("type='Requirement Table'", "type='Dependency Matrix'")
    from cameo_ingest.archive import discover
    from cameo_ingest.pipeline import parse_project

    ix = parse_project(next(discover(make_mdzip(model), "drone.mdzip")))
    assert ct.describe_matrix(ix, "d2") == (
        "Rows: Requirement in Model::Requirements. Columns: Block in Model::Structure; _lib_root (outside this "
        "project). A cell marks Satisfy, from column to row. Only rows and columns with a marked cell are shown.")
    assert ct.not_computed(ix, "d2")[0] == "a matrix" and ct.describe_matrix(ix, "d1") is None
