"""Diagram text, directions, labels and large diagrams' modules, through the pipeline."""

import json

from fixture_model import LAYOUT, MODEL, make_mdzip
from helpers import (
    check_invariants,
    project_dir,
    run,
)

from cameo_ingest.cli import main

# The Drone diagram again, with the «refine» abstraction drawn as Cameo stores it: the first
# end of a directed path is its target (FU-001).
LAYOUT_DIRECTED = LAYOUT.replace("</mdOwnedViews>", """ <mdElement elementClass='Class' xmi:id='v4'><elementID xmi:idref='r1'/><geometry>200, 200, 100, 60</geometry></mdElement>
 <mdElement elementClass='Abstraction' xmi:id='v5'><elementID xmi:idref='rf1'/><linkFirstEndID xmi:idref='v4'/><linkSecondEndID xmi:idref='v1'/>
  <geometry>250, 200; 60, 70; </geometry></mdElement>
</mdOwnedViews>""")


# A second part, a connector between the two parts, and an item flow over it (FU-002).
MODEL_IBD = MODEL.replace("""    </ownedAttribute>
    <xmi:Extension""", """    </ownedAttribute>
    <ownedAttribute xmi:type='uml:Property' xmi:id='a2' name='motor' aggregation='composite' type='m1'/>
    <ownedConnector xmi:type='uml:Connector' xmi:id='cn1'>
     <end xmi:type='uml:ConnectorEnd' xmi:id='cn1a' role='a1'/><end xmi:type='uml:ConnectorEnd' xmi:id='cn1b' role='a2'/>
    </ownedConnector>
    <xmi:Extension""").replace("""   <packagedElement xmi:type='uml:Class' xmi:id='b2' name='Battery'/>""", """   <packagedElement xmi:type='uml:Class' xmi:id='b2' name='Battery'/>
   <packagedElement xmi:type='uml:Class' xmi:id='m1' name='Motor'/>
   <packagedElement xmi:type='uml:Class' xmi:id='e1' name='Energy'/>
   <packagedElement xmi:type='uml:InformationFlow' xmi:id='if1' name='flow for Energy'>
    <conveyed xmi:idref='e1'/><informationSource xmi:idref='b2'/><informationTarget xmi:idref='m1'/>
    <realizingConnector xmi:idref='cn1'/>
   </packagedElement>""")


LAYOUT_IBD = LAYOUT.replace("</mdOwnedViews>", """ <mdElement elementClass='Part' xmi:id='v6'><elementID xmi:idref='a1'/><geometry>10, 200, 100, 60</geometry></mdElement>
 <mdElement elementClass='Part' xmi:id='v7'><elementID xmi:idref='a2'/><geometry>200, 200, 100, 60</geometry></mdElement>
 <mdElement elementClass='Connector' xmi:id='v8'><elementID xmi:idref='cn1'/><linkFirstEndID xmi:idref='v7'/><linkSecondEndID xmi:idref='v6'/>
  <geometry>200, 230; 110, 230; </geometry></mdElement>
 <mdElement elementClass='ConnectorEnd' xmi:id='v9'><geometry>195, 225, 10, 10</geometry></mdElement>
</mdOwnedViews>""")


# A flow drawn as two segments that end at a pair of connector circles (FU-017), a note on
# two lines (FU-016), and a shape naming its element through the project's own file (FU-019).
LAYOUT_BROKEN = LAYOUT.replace("</mdOwnedViews>", """ <mdElement elementClass='Class' xmi:id='v4'><elementID xmi:idref='r1'/><geometry>200, 200, 100, 60</geometry></mdElement>
 <mdElement elementClass='FlowConnector' xmi:id='fc1'><geometry>55, 100, 20, 20</geometry></mdElement>
 <mdElement elementClass='FlowConnector' xmi:id='fc2'><geometry>240, 150, 20, 20</geometry></mdElement>
 <mdElement elementClass='Abstraction' xmi:id='s1'><elementID xmi:idref='rf1'/><linkFirstEndID xmi:idref='fc1'/><linkSecondEndID xmi:idref='v1'/>
  <geometry>65, 100; 60, 70; </geometry></mdElement>
 <mdElement elementClass='Abstraction' xmi:id='s2'><elementID xmi:idref='rf1'/><linkFirstEndID xmi:idref='v4'/><linkSecondEndID xmi:idref='fc2'/>
  <geometry>250, 200; 250, 170; </geometry></mdElement>
 <mdElement elementClass='Note' xmi:id='n1'><text>first line
second line</text><geometry>400, 10, 100, 60</geometry></mdElement>
 <mdElement elementClass='Class' xmi:id='v10'><elementID href='drone.mdzip#long1'/><geometry>400, 200, 100, 60</geometry></mdElement>
</mdOwnedViews>""")


def test_diagram_broken_flows_notes_and_file_references(tmp_path):
    """A flow broken by connector circles is one connection between the shapes at its far
    ends (FU-017); a note's line breaks neither stop the sketch nor split its legend line
    (FU-016); and a shape that names its element through the project's file shows that
    element (FU-019)."""
    out = run(tmp_path, "drone.mdzip", make_mdzip(layout=LAYOUT_BROKEN))
    page = (project_dir(out) / "diagrams/Drone_BDD.md").read_text()
    assert (project_dir(out) / "diagrams/Drone_BDD.png").exists()
    refine = [line for line in page.splitlines() if "«Refine»" in line]
    assert len(refine) == 1 and "(not shown)" not in page, page
    assert refine[0].index("Drone") < refine[0].index("→[Abstraction: «Refine»; refines]→") < refine[0].index("Endurance")
    assert '- [4] Note: "first line second line"' in page, page
    assert "drone.mdzip#long1" not in page and "- [5] Class: [Gravity calibration" in page, page

    # A flow whose element is in another project: Cameo's convention (a path's first end is
    # its target) gives the direction.
    out = run(tmp_path / "ext", "drone.mdzip", make_mdzip(layout=LAYOUT_BROKEN.replace(
        "<elementID xmi:idref='rf1'/>", "<elementID href='other.mdzip#flow9'/>")))
    page = (project_dir(out) / "diagrams/Drone_BDD.md").read_text()
    assert "→[Abstraction: depends on]→" in page and "(not shown)" not in page, page
    line = next(line for line in page.splitlines() if "→[Abstraction: depends on]→" in line)
    assert line.index("Drone") < line.index("→[Abstraction: depends on]→") < line.index("Endurance"), line


def test_diagram_directions_item_flows_and_labels(tmp_path):
    """Directed edges run from source to target (FU-001), connectors show the items they
    carry and which way (FU-002), labels read cleanly (FU-003), and the sketch is drawn at
    the model's image size with no connector-end boxes (FU-007, FU-012)."""
    from PIL import Image

    out = run(tmp_path, "drone.mdzip", make_mdzip(layout=LAYOUT_DIRECTED))
    page = (project_dir(out) / "diagrams/Drone_BDD.md").read_text()
    refine = next(line for line in page.splitlines() if "«Refine»" in line)
    assert refine.index("Drone") < refine.index("→[Abstraction: «Refine»; refines]→") < refine.index("Endurance"), refine
    assert "numbered as in the sketch" in page and "- [1] Class: «Block» [Drone]" in page
    with Image.open(project_dir(out) / "diagrams/Drone_BDD.png") as img:
        w, h = img.size  # the model's pixel budget, sides in multiples of 48 (FU-015)
        assert w * h <= 645_120 and w % 48 == 0 and h % 48 == 0

    out = run(tmp_path / "ibd", "drone.mdzip", make_mdzip(MODEL_IBD, LAYOUT_IBD))
    page = (project_dir(out) / "diagrams/Drone_BDD.md").read_text()
    # The flow names the parts' types, Battery to Motor; the connector is listed that way.
    assert "- [3] battery : Battery —[Connector: carries Energy →]— [4] motor : Motor" in page, page
    assert "ConnectorEnd" not in page  # a decoration, not a shape

    from cameo_ingest import diagram_graph as dg
    from cameo_ingest.archive import discover
    from cameo_ingest.diagram_graph import shape_label
    from cameo_ingest.diagram_text import Refs, describe
    from cameo_ingest.layout import View
    from cameo_ingest.pipeline import parse_project

    ix = parse_project(next(discover(make_mdzip(), "drone.mdzip")))
    ix.elements["a1"].name = None  # an unnamed part reads as its type, not ": Battery"
    def element_label(ix, v):
        return shape_label(ix, v).full()

    assert element_label(ix, View("v", "Part", "a1")) == "Battery"
    assert element_label(ix, View("v", "Diagram", "d1")) == "Drone BDD"  # «DiagramInfo» is not shown
    assert shape_label(ix, View("v", "Part", "a1")).shown() == "Battery"  # drawn in the sketch too (FU-018)
    assert element_label(ix, View("v", "InitialNode", el_id := "a1-initial")) == el_id  # not in the index
    # Unnamed elements that say what they are otherwise (FU-024).
    from cameo_ingest.model import Element

    def el(kind: str, **kw) -> str:
        e = Element(f"x{len(ix.elements)}", f"uml:{kind}", "packagedElement", None, None, "e", None, **kw)
        ix.elements[e.id] = e
        return e.id

    assert element_label(ix, View("v", "SwimlaneHeader", el("ActivityPartition", refs=[("represents", "a1")]))) \
        == "Battery"  # the part it represents is unnamed here: its type
    assert element_label(ix, View("v", "OpaqueAction", el("OpaqueAction", attrs={"body": "j = 1\nk = 2"}))) == "j = 1 k = 2"
    assert element_label(ix, View("v", "Note", el("Comment", attrs={"body": "Check this\n"}))) \
        == '"Check this"'
    # An unnamed element with a page is linked by the same label as in the legend.
    g = dg.DiagramGraph()
    action = el("OpaqueAction", attrs={"body": "j = 1"})
    g.nodes.append(dg.Node(1, View("v1", "OpaqueAction", action), "j = 1", 0))
    legend, _ = describe(ix, g, Refs(lambda e: f"page.md#{e}"))
    assert legend == [f"- [1] OpaqueAction: [j = 1](page.md#{action})"], legend
    # A label that starts with a bracket is text, not a link, when there is no target (AR-002).
    pump = el("Class")
    ix.elements[pump].name = "[Deleted] Pump"
    g.nodes.append(dg.Node(2, View("v2", "Class", pump), "[Deleted] Pump", 0))
    legend, _ = describe(ix, g)
    assert legend[1] == "- [2] Class: \\[Deleted\\] Pump", legend


def large_layout() -> str:
    """The fixture's diagram with two chains of 15 steps added, far apart: 32 shapes."""
    views = []
    for i in range(30):
        x, y = (0 if i < 15 else 3000) + 150 * (i % 5), 200 + 100 * ((i % 15) // 5)
        views.append(f"<mdElement elementClass='Note' xmi:id='n{i}'><text>step {i}</text>"
                     f"<geometry>{x}, {y}, 100, 40</geometry></mdElement>")
        if i % 15:  # Cameo stores a flow's target as its first end
            views.append(f"<mdElement elementClass='ControlFlow' xmi:id='f{i}'><linkFirstEndID xmi:idref='n{i}'/>"
                         f"<linkSecondEndID xmi:idref='n{i - 1}'/><geometry>{x - 50}, {y + 20}; {x}, {y + 20}; "
                         "</geometry></mdElement>")
    views.append("<mdElement elementClass='ControlFlow' xmi:id='f15'><linkFirstEndID xmi:idref='n15'/>"
                 "<linkSecondEndID xmi:idref='n14'/><geometry>700, 420; 3000, 220; </geometry></mdElement>")
    return LAYOUT.replace("</mdOwnedViews>", "\n".join(views) + "\n</mdOwnedViews>")


def test_large_diagram_modules(tmp_path, fake_chat):
    """A large diagram is split into modules, each drawn, described and chunked with its place
    in the diagram; the diagram is then described as a whole from them (plan DV)."""
    import sqlite3

    from PIL import Image

    src = tmp_path / "drone.mdzip"
    src.write_bytes(make_mdzip(layout=large_layout()))
    out = tmp_path / "out"
    assert main([str(src), "-o", str(out), "--vision-model", "v", "--no-preflight"]) == 0
    check_invariants(out)
    pdir = project_dir(out)
    page = (pdir / "diagrams/Drone_BDD.md").read_text()
    assert "**Modules (2):**" in page and "## Module M2 of 2" in page and '<a id="module-m2"></a>' in page
    assert "- [3] Note: \"step 0\" (M" in page  # the legend gives each shape's module
    for k in (1, 2):
        with Image.open(pdir / f"diagrams/Drone_BDD.modules/M{k}.png") as img:
            assert img.mode == "L" and img.size[0] * img.size[1] <= 645_120
    with Image.open(pdir / "diagrams/Drone_BDD.png") as img:
        assert img.mode == "RGB"  # the overview, modules tinted
    chunks = [json.loads(line) for line in (out / "chunks.jsonl").open()]
    mods = [c for c in chunks if c["metadata"]["kind"] == "generated:module_description"]
    assert [c["metadata"]["covers"]["number"] for c in mods] == [1, 2]
    m = mods[0]["metadata"]["covers"]
    assert m["of"] == 2 and m["anchor"] == "diagrams/Drone_BDD.md#module-m1" and len(m["box"]) == 4
    assert m["image"] == "diagrams/Drone_BDD.modules/M1.png" and m["shapes"]
    assert sum(len(c["metadata"]["covers"]["shapes"]) for c in mods) == 32
    assert "module m1 of 2, showing" in mods[0]["text"]
    whole = [c for c in chunks if c["metadata"]["kind"] == "generated:diagram_description"]
    assert [c["metadata"]["provenance"]["derivation"]["template"] for c in whole] == ["diagram-synthesis@v2"]
    db = sqlite3.connect(out / ".cache/llm.sqlite")
    rows = db.execute("SELECT template, prompt, image_path FROM requests WHERE template LIKE 'module%' "
                      "OR template LIKE 'diagram%' ORDER BY rowid").fetchall()
    assert [r[0] for r in rows] == ["module-description@v2"] * 2 + ["diagram-synthesis@v2"]
    assert "Module: M2 of 2" in rows[1][1] and "(in M" in rows[1][1]
    assert rows[2][1].count("A block definition diagram showing Drone") == 2 and rows[2][2] == "diagrams/Drone_BDD.png"

    # The thresholds are a setting: N = 0 draws and describes every diagram whole.
    assert main(["run", "-o", str(out), "--diagram-modules", "0:6:25", "--no-preflight"]) == 0
    page = (project_dir(out) / "diagrams/Drone_BDD.md").read_text()
    assert "## Module" not in page and "generated:module_description" not in (out / "chunks.jsonl").read_text()
    assert main(["run", "-o", str(out), "--diagram-modules", "25:6"]) == 2
