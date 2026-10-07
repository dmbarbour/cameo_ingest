"""The catalog, and the workbook made from it for people to search without tools (plan KX)."""

import hashlib
import json

import xlsx
from fixture_model import make_mdzip
from helpers import cli, ingest, project_dir

from cameo_ingest.catalog import ProjectCatalog
from cameo_ingest.evaluation.fiction import PROJECTS
from cameo_ingest.workbook import write_workbook


def catalog_of(tree, prefix: str) -> list[dict]:
    sha = hashlib.sha256(PROJECTS[prefix]().mdzip()).hexdigest()
    return [json.loads(line) for line in (tree / "by-sha256" / sha / "index" / "catalog.jsonl").open()]


def test_catalog_records(fiction_tree):
    """One record per item, in the pages' vocabulary: a requirement with its id and relations,
    a member listed in its owner, relationships with both ends, and what was left out (KX-02)."""
    recs = catalog_of(fiction_tree, "kois")
    head, by_key = recs[0], {r["key"]: r for r in recs[1:] if r["type"] != "relationship"}
    assert head["type"] == "project" and head["label"].startswith("Kestrel_Orchard_Irrigation [")
    assert head["counts"]["requirement"] == 7 and head["left_out"]["InitialNode"] == 2
    r2 = by_key["_kois_r2"]
    assert (r2["type"], r2["id"], r2["name"]) == ("requirement", "KOIS-R2", "Valve Closing Time (KOIS-R2)")
    assert r2["text"] == "Brine Valve K7 shall close within 340 milliseconds of a leak signal."
    assert ["_kois_satisfy__k7__r2", "Satisfy", "in", "satisfied by", "_kois_k7", "Brine Valve K7"] in r2["relations"]
    assert r2["diagrams"] == [["_kois_d_req", "KOIS Requirements"]] and r2["chunks"]
    tags = by_key["_kois_d_req"]["tags"]  # the diagram's number tags, for links at "[n]" (TR-005)
    assert "_kois_r2" in tags.values() and "_kois_k7" in tags.values() and all(k.isdigit() for k in tags)
    part = by_key["_kois_kois__p_brine_valve_k7"]  # a part property: no chunk of its own
    assert part["listed_in"] == ["_kois_kois", "Kestrel Orchard Irrigation System"]
    assert part["chunks"] == by_key["_kois_kois"]["chunks"][:len(part["chunks"])]
    assert by_key["_kois_d_night"]["kind"] == "SysML Activity Diagram"
    assert not any(r["type"] == "element" and r.get("kind") == "Comment" for r in recs)
    rel = next(r for r in recs if r["type"] == "relationship" and r["key"] == "_kois_deriveReqt__r2__r5")
    assert (rel["source"][1], rel["phrase"], rel["target"][1]) == (
        "Valve Closing Time (KOIS-R2)", "is derived from", "Leak Shutdown (KOIS-R5)")
    doors = next(r for r in catalog_of(fiction_tree, "rwt") if r.get("id") == "RWT-REG-001")
    assert doors["db"] == "16001" and not doors["text"].startswith("[")


def test_catalog_summaries(tmp_path, fake_chat):
    """Generated text is in the catalog, with the model that wrote it."""
    out = ingest(tmp_path, ("drone.mdzip", make_mdzip()), args=("--vision-model", "m", "--text-model", "m", "--no-calibrate", "--no-preflight"))
    recs = [json.loads(line) for line in (project_dir(out) / "index" / "catalog.jsonl").open()]
    summaries = [r for r in recs if r["type"] == "summary"]
    assert summaries and all(r["model"] == "m" and r["text"] and r["of"][0] == r["key"] for r in summaries)
    assert {r["label"] for r in summaries} >= {"Diagram description", "Summary"}


def test_workbook_from_the_tree(fiction_tree, tmp_path, capsys):
    """`export --workbook` writes every sheet from the tree's catalogs, with each item's source,
    and the same bytes each time (KX-03, KX-06)."""
    book = tmp_path / "catalog.xlsx"
    assert cli(["export", "-o", str(fiction_tree), "--workbook", str(book)]) == 0
    assert f"wrote {book}" in capsys.readouterr().out
    sheets = xlsx.sheets(book)
    assert list(sheets) == ["About", "Requirements", "Identifiers", "Elements", "Relationships",
                            "Diagrams", "Subjects", "Summaries", "Projects"]
    subjects = [dict(zip(sheets["Subjects"][0], r, strict=False)) for r in sheets["Subjects"][1:]]
    assert subjects and {r["View"] for r in subjects} >= {"By shared elements (suggested)", "By package"}
    diagrams = [dict(zip(sheets["Diagrams"][0], r, strict=False)) for r in sheets["Diagrams"][1:]]
    suggested = {(r["Model"], r["Diagram"]): r["Subject"] for r in subjects if r["View"].endswith("(suggested)")}
    assert any(d.get("Subject") for d in diagrams)
    assert all(d.get("Subject") in {s for (_, n), s in suggested.items() if n == d["Name"]} for d in diagrams if d.get("Subject"))
    req = sheets["Requirements"]
    row = dict(zip(req[0], next(r for r in req if r[0] == "KOIS-R2"), strict=False))
    assert row["Satisfied by"] == "Brine Valve K7" and row["Derived from"] == "Leak Shutdown (KOIS-R5)"
    assert row["Source"].endswith("Kestrel_Orchard_Irrigation.mdzip")
    # columns to group, sort and filter by (plan WT-04)
    assert row["Coverage"] == "satisfied, derived" and row["Newest"] == "yes" and row["Package 1"] == "Kestrel Orchard Irrigation"
    dia = sheets["Diagrams"]
    req_dia = dict(zip(dia[0], next(r for r in dia if r[0] == "KOIS Requirements"), strict=False))
    assert "Brine Valve K7" in req_dia["Shows"] and "Valve Closing Time (KOIS-R2)" in req_dia["Shows"]
    els = sheets["Elements"]
    k7 = dict(zip(els[0], next(r for r in els if r[1] == "Brine Valve K7"), strict=False))
    assert "KOIS Requirements" in k7["Diagrams"]
    assert any(dict(zip(els[0], r, strict=False)).get("Subject") for r in els[1:])
    rwt = hashlib.sha256(PROJECTS["rwt"]().mdzip()).hexdigest()[:8]  # three proposals share the id
    doors = dict(zip(req[0], next(r for r in req if r[0] == "RWT-REG-001" and rwt in r[4]), strict=False))
    assert doors["Database number"] == "16001"
    assert len(sheets["Projects"]) == 1 + len(PROJECTS)
    ids = [r for r in sheets["Identifiers"][1:] if r[0] == "RWT-REG-003"]
    assert len({r[1] for r in ids}) == 3  # the id in all three Riverbend proposals
    again = tmp_path / "again.xlsx"
    assert cli(["export", "-o", str(fiction_tree), "--workbook", str(again)]) == 0
    assert again.read_bytes() == book.read_bytes()


def test_workbook_writes_text_as_text(tmp_path):
    """Text that looks like a formula, a number or a link stays text; long text is cut; control
    characters, which the file's XML can't hold, are dropped."""
    head = {"type": "project", "name": "x.mdzip", "label": "x [00000000]", "token": "sha256:0", "counts": {}}
    recs = [{"type": "requirement", "key": "r", "id": "1.2.3", "name": "=HYPERLINK(\"http://x\")",
             "text": "=1+1\x0b" + "y" * 9000, "relations": [], "diagrams": []}]
    book = tmp_path / "t.xlsx"
    write_workbook(book, [ProjectCatalog(head, recs, [], [{"path": "C:/models/x.mdzip", "metadata": {"by": "A"}}])],
                   "test")
    req = xlsx.sheets(book)["Requirements"][1]
    assert req[0] == "1.2.3" and req[2] == '=HYPERLINK("http://x")' and not isinstance(req[2], xlsx.Formula)
    assert req[3].startswith("=1+1y") and len(req[3]) == 4000 and req[3].endswith("…")
    assert xlsx.sheets(book)["Projects"][1][4] == "by=A"


def test_export_names_projects_without_a_catalog(tmp_path, capsys):
    out = ingest(tmp_path, ("drone.mdzip", make_mdzip()))
    (project_dir(out) / "index" / "catalog.jsonl").unlink()  # as a project made before 0.8.0
    assert cli(["export", "-o", str(out), "--workbook", str(tmp_path / "c.xlsx")]) == 0
    assert "drone.mdzip; `run` makes them again" in capsys.readouterr().err


def test_svg_sketch_names_its_elements(tmp_path):
    """The SVG sketch draws each shape with its element's key and full label, escaped, without
    the characters XML forbids (KX-05); `run` writes it beside the PNG, and the catalog names
    both."""
    from xml.etree import ElementTree

    from cameo_ingest.diagram_graph import DiagramGraph, Link, Node
    from cameo_ingest.layout import View
    from cameo_ingest.model import ModelIndex
    from cameo_ingest.sketch_svg import render_svg

    g = DiagramGraph()
    for i, (key, label) in enumerate((("a", 'Tank <A> & "B"'), ("b", "Pump\x01\x0b\x1f")), 1):
        node = Node(i, View(f"v{i}", "Class", key, rect=(10 + 200 * (i - 1), 10, 120, 50)), label, 0, shown=label)
        g.nodes.append(node)
        g.node_of[f"v{i}"] = node
    g.links.append(Link(View("l", "Dependency", None, points=[(130, 35), (210, 35)]), g.nodes[0].view,
                        g.nodes[1].view, True, "", "depends on", [], False))
    svg = ElementTree.fromstring(render_svg(ModelIndex(), g, "Class Diagram: x\x08"))  # well-formed despite them
    ns = {"s": "http://www.w3.org/2000/svg"}
    keyed = svg.findall(".//s:g[@data-k]", ns)
    assert {k.get("data-k") for k in keyed} == {"a", "b"}
    titles = [t.text for t in svg.iter("{http://www.w3.org/2000/svg}title")]
    assert '[1] Tank <A> & "B"' in titles and "[2] Pump" in titles
    assert svg.findall(".//s:polyline[@stroke-dasharray]", ns)  # a dependency is dashed

    out = ingest(tmp_path, ("drone.mdzip", make_mdzip()))  # rendering is on by default
    dia = next(r for r in (json.loads(line) for line in (project_dir(out) / "index" / "catalog.jsonl").open())
               if r["type"] == "diagram" and r.get("sketch"))
    assert dia["sketch"].endswith(".png") and dia["svg"] == dia["sketch"][:-4] + ".svg"
    assert (project_dir(out) / dia["svg"]).read_text().startswith("<svg ")


def test_search_page_sketches(tmp_path):
    """`--sketches` puts each diagram's sketch in the page, as WebP or gzipped SVG, in a block of
    its own that the diagram's item names."""
    import base64
    import gzip
    import re

    out = ingest(tmp_path, ("drone.mdzip", make_mdzip()))
    for fmt in ("svg", "webp"):
        page = tmp_path / f"{fmt}.html"
        assert cli(["export", "-o", str(out), "--search-page", str(page), "--sketches", fmt]) == 0
        html = page.read_text()
        found = re.findall(r'<script type="application/octet-stream" data-sketch="([^"]+)" data-format="(\w+)">'
                           r'([^<]+)</script>', html)
        assert found and all(f == fmt for _, f, _ in found)
        raw = base64.b64decode(found[0][2])
        assert gzip.decompress(raw).startswith(b"<svg ") if fmt == "svg" else raw[:4] == b"RIFF"
        data = re.search(r'data-items="\d+">([^<]+)</script>', html).group(1)
        items = json.loads(gzip.decompress(base64.b64decode(data)))["items"]
        assert {i for it in items for i in it.get("sk", [])} == {i for i, _, _ in found}


def test_every_sheet_a_table(fiction_tree, tmp_path):
    """Each data sheet is an Excel Table (plan WT): every part well formed, each table's columns
    the sheet's header row, and the sheet's own filter given way to the table's."""
    import zipfile

    from lxml import etree

    from cameo_ingest.workbook import SHEETS
    from cameo_ingest.xlsx_parts import MAIN

    book = tmp_path / "catalog.xlsx"
    assert cli(["export", "-o", str(fiction_tree), "--workbook", str(book)]) == 0
    with zipfile.ZipFile(book) as z:
        names = set(z.namelist())
        for n in names:
            if n.endswith((".xml", ".rels")):
                etree.fromstring(z.read(n))
        tables = {etree.fromstring(z.read(n)).get("name"): etree.fromstring(z.read(n))
                  for n in names if n.startswith("xl/tables/")}
        assert set(tables) == set(SHEETS)
        for name, t in tables.items():
            assert [c.get("name") for c in t.iter(f"{{{MAIN}}}tableColumn")] == [c for c, _ in SHEETS[name]]
        assert "_xlnm._FilterDatabase" not in z.read("xl/workbook.xml").decode()
    sheets = xlsx.sheets(book)
    assert all(sheets[name][0] == [c for c, _ in SHEETS[name]] for name in SHEETS)  # still readable
