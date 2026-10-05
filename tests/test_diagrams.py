"""Diagram text, directions, labels and large diagrams' modules, through the pipeline."""

import json
import re

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

    # A note's text can be HTML, as Cameo writes rich text: it reads as text.
    html = ("&lt;html&gt;&lt;head&gt;&lt;style&gt;p {padding:0px;}&lt;/style&gt;&lt;/head&gt;&lt;body&gt;"
            "&lt;p&gt;Check the &lt;b&gt;battery&lt;/b&gt; first&lt;/p&gt;&lt;/body&gt;&lt;/html&gt;")
    out = run(tmp_path / "html", "drone.mdzip", make_mdzip(layout=LAYOUT_BROKEN.replace("first line\nsecond line", html)))
    page = (project_dir(out) / "diagrams/Drone_BDD.md").read_text()
    assert '- [4] Note: "Check the battery first"' in page and "padding" not in page, page

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
    from cameo_ingest.diagram_text import describe, markdown
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
    legend, _ = describe(ix, g, markdown(lambda e: f"page.md#{e}"))
    assert legend == [f"- [1] OpaqueAction: [j = 1](page.md#{action})"], legend
    # A label that starts with a bracket is text, not a link, when there is no target (AR-002).
    pump = el("Class")
    ix.elements[pump].name = "[Deleted] Pump"
    g.nodes.append(dg.Node(2, View("v2", "Class", pump), "[Deleted] Pump", 0))
    legend, _ = describe(ix, g, markdown(lambda e: None))
    assert legend[1] == "- [2] Class: \\[Deleted\\] Pump", legend
    # The LLM's request has the text as it is, without Markdown's escapes (AR-002).
    ix.elements[pump].name = "T/T < Threshold [Deleted]"
    g.nodes[1] = dg.Node(2, View("v2", "Class", pump), "T/T < Threshold [Deleted]", 0)
    assert describe(ix, g)[0][1] == "- [2] Class: T/T < Threshold [Deleted]"
    assert describe(ix, g, markdown(lambda e: None))[0][1] == "- [2] Class: T/T \\< Threshold \\[Deleted\\]"


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
    assert main([str(src), "-o", str(out), "--vision-model", "v", "--no-calibrate", "--no-preflight"]) == 0
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
    assert [r[0] for r in rows] == ["module-description@v3"] * 2 + ["diagram-synthesis@v2"]
    assert "Module: M2 of 2" in rows[1][1] and "(in M" in rows[1][1]
    assert rows[2][1].count("A block definition diagram showing Drone") == 2 and rows[2][2] == "diagrams/Drone_BDD.png"

    # The thresholds are a setting: N = 0 draws and describes every diagram whole.
    assert main(["run", "-o", str(out), "--diagram-modules", "0:6:25", "--no-preflight"]) == 0
    page = (project_dir(out) / "diagrams/Drone_BDD.md").read_text()
    assert "## Module" not in page and "generated:module_description" not in (out / "chunks.jsonl").read_text()
    assert main(["run", "-o", str(out), "--diagram-modules", "25:6"]) == 2


# The Drone diagram with Battery's kinds drawn as Cameo draws a tree of generalizations (each
# member's stub reaches a bar, and a `Tree` view joins the bar to the parent), a frame listed
# after the shape it encloses, an association's name box, and an association-class line (plan SK).
MODEL_SK = MODEL.replace("<packagedElement xmi:type='uml:Class' xmi:id='b2' name='Battery'/>", """\
<packagedElement xmi:type='uml:Class' xmi:id='b2' name='Battery'/>
   <packagedElement xmi:type='uml:Class' xmi:id='k1' name='LiPo'>
    <generalization xmi:type='uml:Generalization' xmi:id='g1' general='b2'/></packagedElement>
   <packagedElement xmi:type='uml:Class' xmi:id='k2' name='NiMH'>
    <generalization xmi:type='uml:Generalization' xmi:id='g2' general='b2'/></packagedElement>
   <packagedElement xmi:type='uml:Class' xmi:id='k3' name='LiFe'>
    <generalization xmi:type='uml:Generalization' xmi:id='g3' general='b2'/></packagedElement>""")
LAYOUT_SK = LAYOUT.replace("</mdOwnedViews>", "".join(
    f"<mdElement elementClass='Class' xmi:id='k{i}v'><elementID xmi:idref='k{i}'/>"
    f"<geometry>{50 + 100 * i}, 200, 80, 40</geometry></mdElement>"
    f"<mdElement elementClass='Generalization' xmi:id='g{i}v'><elementID xmi:idref='g{i}'/>"
    f"<linkFirstEndID xmi:idref='v2'/><linkSecondEndID xmi:idref='k{i}v'/>"
    f"<geometry>{90 + 100 * i}, 150; {90 + 100 * i}, 200; </geometry><treeID xmi:idref='t1'/></mdElement>"
    for i in (1, 2, 3)) + """
 <mdElement elementClass='Tree' xmi:id='t1'><geometry>190, 150, 200, 0</geometry><baseShape xmi:idref='v2'/>
  <verticalBarX xmi:value='50'/><verticalBarY xmi:value='70'/><horizontalBarLeft xmi:value='190'/>
  <horizontalBarRight xmi:value='390'/><horizontalBarY xmi:value='150'/></mdElement>
 <mdElement elementClass='RectangularShape' xmi:id='fr'><text>Frame</text><geometry>0, 0, 150, 100</geometry></mdElement>
 <mdElement elementClass='LinkAttribute' xmi:id='la'><linkFirstEndID xmi:idref='v3'/><linkSecondEndID xmi:idref='k1v'/>
  <geometry>155, 40; 155, 200; </geometry></mdElement>
</mdOwnedViews>""").replace("<geometry>110, 40; 200, 40; </geometry></mdElement>", """<geometry>110, 40; 200, 40; </geometry>
  <mdOwnedViews><mdElement elementClass='AssociationTextBox' xmi:id='atb'><text>powers</text>
   <geometry>140, 30, 40, 12</geometry></mdElement></mdOwnedViews></mdElement>""")  # nested in its connection's view


def test_trees_frames_labels_and_association_classes(monkeypatch):
    """Plan SK: a tree's bars are drawn, with a hollow head at the parent and the members' own on
    their stubs; a frame lies under the shapes inside it; an association's name box is no shape;
    an association-class line is dashed. The legend still lists each generalization."""
    from cameo_ingest import sketch, sketch_svg
    from cameo_ingest.archive import discover
    from cameo_ingest.diagram_graph import drawing_order
    from cameo_ingest.diagram_text import describe
    from cameo_ingest.pipeline import load_layouts, parse_project
    from cameo_ingest.provenance import ContentInfo
    from cameo_ingest.view import ProjectView

    project = next(discover(make_mdzip(MODEL_SK, LAYOUT_SK), "drone.mdzip"))
    ix = parse_project(project)
    view = ProjectView(ContentInfo(project.sha256, "drone.mdzip"), project, ix, layouts=load_layouts(project, ix))
    g = view.graph("d1")
    (tree,) = g.trees
    battery = g.node_of["v2"]
    assert tree.parent is battery and tree.vertical == ((250.0, 70.0), (250.0, 150.0)) and len(tree.members) == 3
    assert [n.label for n in g.nodes if n.view.cls in ("AssociationTextBox", "RectangularShape")] == ['"Frame"']
    _, connections = describe(ix, g)
    assert sum("Generalization" in c and "Battery" in c for c in connections) == 3, connections
    assert any("Association: powers" in c for c in connections), connections  # the name box's text, not a shape
    order = [n.view.view_id for n in drawing_order(g)]
    assert order.index("fr") < order.index("v1")  # the frame first: under the Drone it encloses

    heads, lines = [], []
    arrowhead, polyline = sketch._arrowhead, sketch._polyline
    monkeypatch.setattr(sketch, "_arrowhead", lambda d, p, q, hollow, **kw: heads.append((p, q, hollow))
                        or arrowhead(d, p, q, hollow, **kw))
    monkeypatch.setattr(sketch, "_polyline", lambda d, pts, dashed, **kw: lines.append(dashed)
                        or polyline(d, pts, dashed, **kw))
    assert sketch.render_png(ix, g, "BDD") is not None
    hollow = sorted([h for h in heads if h[2]], key=lambda h: h[1][1])
    assert len(hollow) == 4 and all(q[1] < p[1] for p, q, _ in hollow)  # all pointing up
    tips = [q[1] for _, q, _ in hollow]
    assert tips[0] < tips[1] == tips[2] == tips[3]  # the tree's at Battery's lower edge, the stubs' at the bar
    assert lines.count(True) == 1  # the association-class line, and nothing else, dashed
    svg = sketch_svg.render_svg(ix, g, "BDD")
    assert "Generalization of [2]" in svg and svg.count('stroke-dasharray') == 1
    # A containment tree (Cameo draws a package's contents so too): bars, and no head at all.
    contained = re.sub(r"<elementID xmi:idref='g\d'/>", "",
                       LAYOUT_SK.replace("elementClass='Generalization'", "elementClass='ContainmentLink'"))
    project = next(discover(make_mdzip(MODEL_SK, contained), "drone.mdzip"))
    ix = parse_project(project)
    view = ProjectView(ContentInfo(project.sha256, "drone.mdzip"), project, ix, layouts=load_layouts(project, ix))
    (tree,) = view.graph("d1").trees
    assert not tree.to_parent
    heads.clear()
    sketch.render_png(ix, view.graph("d1"), "BDD")
    assert not [h for h in heads if h[2]] and not heads  # containment: no head at all


def test_a_tree_below_its_parent():
    """A tree whose parent is below its bar: the head points down, at the parent's upper edge."""
    from cameo_ingest import sketch
    from cameo_ingest.archive import discover
    from cameo_ingest.pipeline import load_layouts, parse_project
    from cameo_ingest.provenance import ContentInfo
    from cameo_ingest.view import ProjectView

    layout = LAYOUT_SK.replace("<verticalBarY xmi:value='70'/>", "<verticalBarY xmi:value='10'/>").replace(
        "<horizontalBarY xmi:value='150'/>", "<horizontalBarY xmi:value='-30'/>")
    project = next(discover(make_mdzip(MODEL_SK, layout), "drone.mdzip"))
    ix = parse_project(project)
    view = ProjectView(ContentInfo(project.sha256, "drone.mdzip"), project, ix, layouts=load_layouts(project, ix))
    (tree,) = view.graph("d1").trees
    assert tree.vertical == ((250.0, 10.0), (250.0, -30.0))
    heads = []
    arrowhead = sketch._arrowhead
    sketch._arrowhead = lambda d, p, q, hollow, **kw: heads.append((p, q, hollow)) or arrowhead(d, p, q, hollow, **kw)
    try:
        sketch.render_png(ix, view.graph("d1"), "BDD")
    finally:
        sketch._arrowhead = arrowhead
    hollow = [h for h in heads if h[2]]
    assert len(hollow) == 4 and sum(q[1] > p[1] for p, q, _ in hollow) == 1  # the tree's head points down


def test_reading_guides():
    """Plan SK: a request explains the drawing conventions its sketch uses, and no others; a
    module's request those of its own shapes."""
    from cameo_ingest import prompt_values as pv
    from cameo_ingest import sketch
    from cameo_ingest.archive import discover
    from cameo_ingest.pipeline import load_layouts, parse_project
    from cameo_ingest.prompts import CURRENT
    from cameo_ingest.provenance import ContentInfo
    from cameo_ingest.view import ProjectView

    project = next(discover(make_mdzip(MODEL_SK, LAYOUT_SK), "drone.mdzip"))
    ix = parse_project(project)
    view = ProjectView(ContentInfo(project.sha256, "drone.mdzip"), project, ix, layouts=load_layouts(project, ix))
    g = view.graph("d1")
    assert sketch.conventions(g) == {"tags", "frames", "open", "hollow", "tree", "association-class"}
    guide = pv.diagram_description(ix, g, ix.diagrams["d1"]).values["GUIDE"]
    t = CURRENT["diagram-description"]
    assert guide.startswith("\n\nReading the sketch:\n") and t.fragment("tree") in guide
    assert t.fragment("sequence") not in guide and t.fragment("pins") not in guide
    assert guide.index(t.fragment("tags")) < guide.index(t.fragment("tree"))  # in the template's order
    assert sketch.conventions(g, {1}) == {"tags", "open"}  # around the Drone alone: its association
    plain = next(discover(make_mdzip(), "drone.mdzip"))
    ix = parse_project(plain)
    view = ProjectView(ContentInfo(plain.sha256, "drone.mdzip"), plain, ix, layouts=load_layouts(plain, ix))
    assert pv.diagram_description(ix, view.graph("d1"), ix.diagrams["d1"]).values["GUIDE"].count("\n- ") == 2


def test_what_shapes_hold(tmp_path):
    """A drawn diagram's page says what its shapes show inside them (plan IS): the elements Cameo
    lists as used but which have no shape, under the shape drawn for their owner, by kind; those
    whose owner isn't drawn are counted; drawn elements aren't repeated."""
    used = "".join(f"<usedObjects href='#{e}'/>" for e in ("b1", "b2", "a1", "op1", "r1"))
    model = MODEL.replace(
        "<diagramContents><binaryObject streamContentID='BINARY-1'/></diagramContents>",
        f"<diagramContents><binaryObject streamContentID='BINARY-1'/>{used}</diagramContents>").replace(
        "    <xmi:Extension extender='MagicDraw UML 2024x'><modelExtension>\n     <ownedDiagram xmi:type='uml:Diagram' xmi:id='d1'",
        "    <ownedOperation xmi:type='uml:Operation' xmi:id='op1' name='charge'/>\n"
        "    <xmi:Extension extender='MagicDraw UML 2024x'><modelExtension>\n     <ownedDiagram xmi:type='uml:Diagram' xmi:id='d1'")
    assert model.count("usedObjects") == 5 and model.count("xmi:id='op1'") == 1
    out = run(tmp_path, "drone.mdzip", make_mdzip(model))
    page = (project_dir(out) / "diagrams/Drone_BDD.md").read_text()
    block = page.split("**Shown inside its shapes:**\n", 1)[1].split("\n\n", 1)[0]
    assert block.splitlines() == [
        "- [1] «Block» Drone: properties battery; operations charge()",
        "- and 1 more that Cameo lists as used, whose owners aren't drawn here"], block
    chunks = [json.loads(line) for line in (project_dir(out) / "index/chunks.jsonl").open()]
    assert any("- [1] «Block» Drone: properties battery; operations charge()" in c["text"]
               for c in chunks if c["metadata"].get("element_id") == "d1")
