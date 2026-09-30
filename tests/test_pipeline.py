import csv
import hashlib
import io
import json
import logging
import os
import re
import threading
import time
import zipfile
from collections import Counter
from pathlib import Path
from types import SimpleNamespace

import pytest
from fixture_model import LAYOUT, MODEL, make_mdzip

from cameo_ingest.cli import main
from cameo_ingest.llm import PREFLIGHT_PROMPT

csv.field_size_limit(1 << 30)  # documentation columns in large models exceed the default

LLM_ENV = ("OPENAI_API_KEY", "OPENAI_BASE_URL", "OPENAI_MODEL", "CAMEO_INGEST_TEXT_MODEL",
           "CAMEO_INGEST_VISION_MODEL", "CAMEO_INGEST_LLM_TIMEOUT", "CAMEO_INGEST_LLM_RETRIES",
           "CAMEO_INGEST_LLM_MAX_CALLS")


@pytest.fixture(autouse=True)
def isolated_env(monkeypatch):
    """Tests never see the developer's LLM settings, and --env cannot leak between tests."""
    monkeypatch.setattr(os, "environ", {k: v for k, v in os.environ.items() if k not in LLM_ENV})


# Root files that name local paths or times; everything else in a tree is reproducible.
RUN_RECORDS = {"run.json", "provenance.jsonl", "state.sqlite", "state.sqlite-wal", "state.sqlite-shm", "state.lock"}


def tree(out: Path) -> dict[str, bytes]:
    return {str(f.relative_to(out)): f.read_bytes() for f in out.rglob("*")
            if f.is_file() and f.name not in RUN_RECORDS and ".cache" not in f.parts}


def project_dir(out: Path, name: str | None = None) -> Path:
    """The directory of the only (or the named) written project in an output tree."""
    projects = [p for p in json.loads((out / "manifest.json").read_text())["projects"]
                if name is None or p["name"] == name]
    assert len(projects) == 1, [p["name"] for p in projects]
    return out / projects[0]["dir"]


def provenance(out: Path) -> dict[str, dict]:
    return {r["token"]: r for r in map(json.loads, (out / "provenance.jsonl").open())}


def run(tmp_path: Path, name: str, data: bytes) -> Path:
    tmp_path.mkdir(parents=True, exist_ok=True)
    src = tmp_path / name
    src.write_bytes(data)
    out = tmp_path / "out"
    assert main([str(src), "-o", str(out), "--meta", "program=test", "--no-llm"]) == 0
    return out


def check_invariants(out: Path) -> None:
    """Properties every output tree must have, whatever the input (BASE-007R1)."""
    for md in out.rglob("*.md"):
        text = md.read_text(encoding="utf-8")
        head = text.split("\n---\n", 1)[0]
        assert head.startswith("---\n") and "provenance:" in head, md
        dup = [a for a, n in Counter(re.findall(r'<a id="([^"]+)"></a>', text)).items() if n > 1]
        assert not dup, (md, dup[:3])
        assert "<unnamed>" not in text and "{#" not in text, md  # placeholders and anchors (BASE-009)
    for f in out.rglob("*.csv"):
        with f.open(encoding="utf-8", newline="") as fh:
            assert all(r.get("trace", "").startswith("sha256:") for r in csv.DictReader(fh)), f
    chunks = [json.loads(line) for line in (out / "chunks.jsonl").open(encoding="utf-8")]
    dup = [i for i, n in Counter(c["id"] for c in chunks).items() if n > 1]
    assert not dup, dup[:3]
    for c in chunks:
        if "content" in c["metadata"]:  # traces start from the project's content (plan RI-02)
            assert c["metadata"]["provenance"]["locator"].startswith(c["metadata"]["content"][:23]), c["id"]
            assert "source_metadata" in c["metadata"], c["id"]  # joined in at the root
        if c["metadata"]["provenance"]["derivation"]["method"] == "llm":  # labelled (BASE-025)
            assert c["metadata"]["kind"].startswith("generated:"), c["id"]
            assert "not part of the source model" in c["text"], c["id"]
    # A `base_*` attribute or reference means a stereotype application was read as an element.
    for f in out.glob("by-sha256/*/index/elements.jsonl"):
        for line in f.open(encoding="utf-8"):
            rec = json.loads(line)
            assert not any(n.startswith("base_") for n in [*rec["attrs"], *(r for r, _ in rec["refs"])]), rec["id"]


def test_mdzip_end_to_end(tmp_path):
    out = run(tmp_path, "drone.mdzip", make_mdzip())
    check_invariants(out)
    proj = project_dir(out)
    reqs = list(csv.DictReader((proj / "tables/requirements.csv").open()))
    assert [(r["req_id"], r["text"]) for r in reqs] == [("R-1", "The drone shall fly 30 min.")]
    assert "Satisfy_in" in reqs[0]["relationships"]

    rels = list(csv.DictReader((proj / "tables/relationships.csv").open()))
    assert {(r["kind"], r["source"], r["target"]) for r in rels} >= {
        ("Satisfy", "Model::Structure::Battery", "Model::Requirements::Endurance"),
        ("Refine", "Model::Structure::Drone", "Model::Requirements::Endurance"),  # StandardProfile (BASE-001)
    }

    dia = (proj / "diagrams/Drone_BDD.md").read_text()
    assert "SysML Block Definition Diagram" in dia
    assert "Drone" in dia and "Battery" in dia and "[Association]" in dia
    assert "- **Author:** tester" in dia and "Table / matrix" not in dia
    assert (proj / "diagrams/Drone_BDD.png").exists()

    table = (proj / "diagrams/Req_Table.md").read_text()
    assert "**Table / matrix configuration**" in table and "«DiagramTable» displayMode: List" in table
    assert "additionalElements: Model::Requirements::Endurance; Model::Structure::Drone" in table

    readme = (proj / "README.md").read_text()
    kinds = readme.split("## Element kinds")[1].split("##")[0]
    assert "DiagramTable" not in kinds and "DiagramInfo" not in kinds and "Refine" not in kinds
    assert "«Refine»: 1" in readme and "«DiagramTable»: 1" in readme

    pkg = (proj / "packages/Model__Structure.md").read_text()
    assert "A delivery drone." in pkg and "battery" in pkg and "[1..2]" in pkg
    assert '-long1"></a>' in pkg and '-long2"></a>' in pkg  # anchors keep the id after long names (BASE-003)
    assert "## «Block» Drone\n" in pkg  # no anchor syntax in headings (BASE-009R2)
    assert "## Cell \\[A\\*\\] \\<v2>\n" in pkg  # names are escaped (BASE-009R3)
    ledger = [json.loads(line) for line in (out / "chunks.jsonl").open()]
    elements = next(c for c in ledger if c["metadata"]["kind"] == "ledger:elements" and "Structure" in c["text"])
    assert "Cell [A*] <v2>" in elements["text"]  # ...but plain in chunk text
    from cameo_ingest.archive import discover
    from cameo_ingest.pipeline import parse_project

    ix = parse_project(next(discover(make_mdzip(), "drone.mdzip")))
    assert ix.label("s1") == "(Abstraction)"  # not an HTML-like "<Abstraction>" (BASE-009R1)


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


def test_diagram_directions_item_flows_and_labels(tmp_path):
    """Directed edges run from source to target (FU-001), connectors show the items they
    carry and which way (FU-002), labels read cleanly (FU-003), and the sketch is drawn at
    the model's image size with no connector-end boxes (FU-007, FU-012)."""
    from PIL import Image

    out = run(tmp_path, "drone.mdzip", make_mdzip(layout=LAYOUT_DIRECTED))
    page = (project_dir(out) / "diagrams/Drone_BDD.md").read_text()
    refine = next(line for line in page.splitlines() if "«Refine»" in line)
    assert refine.index("Drone") < refine.index("→[Abstraction: «Refine»]→") < refine.index("Endurance"), refine
    assert "numbered as in the sketch" in page and "- [1] Class: «Block» [Drone]" in page
    with Image.open(project_dir(out) / "diagrams/Drone_BDD.png") as img:
        assert max(img.size) <= 768

    out = run(tmp_path / "ibd", "drone.mdzip", make_mdzip(MODEL_IBD, LAYOUT_IBD))
    page = (project_dir(out) / "diagrams/Drone_BDD.md").read_text()
    # The flow names the parts' types, Battery to Motor; the connector is listed that way.
    assert "- [3] battery : Battery —[Connector: carries Energy →]— [4] motor : Motor" in page, page
    assert "ConnectorEnd" not in page  # a decoration, not a shape

    from cameo_ingest.archive import discover
    from cameo_ingest.diagrams import element_label
    from cameo_ingest.layout import View
    from cameo_ingest.pipeline import parse_project

    ix = parse_project(next(discover(make_mdzip(), "drone.mdzip")))
    ix.elements["a1"].name = None  # an unnamed part reads as its type, not ": Battery"
    assert element_label(ix, View("v", "Part", "a1")) == "Battery"
    assert element_label(ix, View("v", "Diagram", "d1")) == "Drone BDD"  # «DiagramInfo» is not shown


def test_provenance_everywhere(tmp_path):
    out = run(tmp_path, "drone.mdzip", make_mdzip())
    proj = project_dir(out)
    token = f"sha256:{proj.name}"
    # Where the content was found is looked up by its token (plan decision 2).
    [record] = provenance(out).values()
    assert record["token"] == token and record["name"] == "drone.mdzip"
    assert record["sightings"] == [{"path": str((tmp_path / "drone.mdzip").resolve()), "input_sha256": proj.name,
                                    "chain": [], "metadata": {"program": "test"}, "missing": False}]
    chunks = [json.loads(line) for line in (out / "chunks.jsonl").open()]
    for c in chunks:
        if c["metadata"]["kind"] != "ledger:projects":
            assert c["metadata"]["content"] == token
            assert c["metadata"]["provenance"]["content_sha256"] == proj.name
            assert c["metadata"]["source_metadata"] == {"program": ["test"]}
    # The project's own files carry the token only: no paths, no --meta.
    for f in proj.rglob("*"):
        if f.is_file() and f.suffix in (".md", ".json", ".jsonl", ".csv"):
            text = f.read_text(encoding="utf-8")
            assert str(tmp_path) not in text and "program" not in text, f
    req = next(c for c in chunks if c["metadata"]["kind"] == "requirement")
    assert req["metadata"]["provenance"]["xmi_id"] == "r1"
    assert req["metadata"]["provenance"]["line"]
    assert "provenance:" in (proj / "images.md").read_text()  # BASE-024


def test_nested_bundle(tmp_path):
    inner = io.BytesIO()
    with zipfile.ZipFile(inner, "w") as z:
        z.writestr("samples/drone.mdzip", make_mdzip())
    outer = io.BytesIO()
    with zipfile.ZipFile(outer, "w") as z:
        z.writestr("resource.zip", inner.getvalue())
    out = run(tmp_path, "bundle.rdzip", outer.getvalue())
    [record] = provenance(out).values()
    assert record["name"] == "drone.mdzip"
    [seen] = record["sightings"]
    assert seen["path"].endswith("bundle.rdzip") and seen["chain"] == ["resource.zip", "samples/drone.mdzip"]
    # The project inside the bundle is the same content as the file on its own.
    assert project_dir(out).name == hashlib.sha256(make_mdzip()).hexdigest()


def test_reproducible_output(tmp_path):
    """Same input and options give byte-identical output, apart from the files that name
    paths and times, even from another directory (BASE-015)."""
    data = make_mdzip()
    trees = []
    for i, d in enumerate(["a", "a", "b"]):
        src = tmp_path / d / "drone.mdzip"
        src.parent.mkdir(exist_ok=True)
        src.write_bytes(data)
        out = tmp_path / f"out{i}"
        assert main([str(src), "-o", str(out), "--meta", "program=test", "--no-llm"]) == 0
        trees.append(tree(out))
    assert trees[0] == trees[1] == trees[2]
    [record] = provenance(tmp_path / "out2").values()
    assert record["sightings"][0]["path"].endswith("b/drone.mdzip")
    sha = project_dir(tmp_path / "out0").name
    assert f"by-sha256/{sha}/diagrams/Drone_BDD.png" in trees[0]  # rendering is covered too


def test_rejects_non_model(tmp_path):
    src = tmp_path / "x.mdzip"
    src.write_bytes(b"not a zip")
    assert main([str(src), "-o", str(tmp_path / "out"), "--no-llm"]) == 3


def test_failed_project_does_not_stop_others(tmp_path, caplog):
    truncated = io.BytesIO()
    with zipfile.ZipFile(truncated, "w") as z:
        z.writestr("com.nomagic.magicdraw.uml_model.model", MODEL[:2000])
    good = make_mdzip()
    outer = io.BytesIO()
    with zipfile.ZipFile(outer, "w", compression=zipfile.ZIP_STORED) as z:
        z.writestr("good.mdzip", good)
        z.writestr("bad.mdzip", truncated.getvalue())
        z.writestr("corrupt.mdzip", good)
    data = bytearray(outer.getvalue())
    i = data.rfind(good) + len(good) // 2  # damage the stored copy of corrupt.mdzip: bad CRC
    data[i] ^= 0xFF
    src = tmp_path / "bundle.rdzip"
    src.write_bytes(bytes(data))
    out = tmp_path / "out"
    assert main([str(src), "-o", str(out), "--no-llm", "--no-render"]) == 4
    manifest = json.loads((out / "manifest.json").read_text())
    assert [p["name"] for p in manifest["projects"]] == ["good.mdzip"]
    assert [f["name"] for f in manifest["failed"]] == ["bad.mdzip"]
    assert "XMLSyntaxError" in manifest["failed"][0]["error"]
    assert "skipping nested member bundle.rdzip!corrupt.mdzip" in caplog.text
    check_invariants(out)


def test_contents_and_sightings(tmp_path):
    """Output goes by content: two different files both called drone.mdzip get a project
    each, and the same content under another path is one project seen twice (BASE-016,
    BASE-017). Inputs can be added first and run later, and the tree remembers settings."""
    out = tmp_path / "out"
    a, b, copy = tmp_path / "a/drone.mdzip", tmp_path / "b/drone.mdzip", tmp_path / "c/copy.mdzip"
    for f, model in ((a, MODEL), (b, MODEL.replace("name='Requirements'", "name='Needs'")), (copy, MODEL)):
        f.parent.mkdir()
        f.write_bytes(make_mdzip(model))
    assert main(["add", "-o", str(out), str(a), str(b), "--meta", "program=X"]) == 0
    assert not (out / "by-sha256").exists()  # added, not processed
    assert main(["run", "-o", str(out), "--no-llm", "--no-render"]) == 0
    projects = json.loads((out / "manifest.json").read_text())["projects"]
    assert [p["name"] for p in projects] == ["drone.mdzip", "drone.mdzip"]
    # No flags: the tree remembers --no-llm and --no-render.
    assert main([str(tmp_path / "c"), "-o", str(out)]) == 0
    assert len(json.loads((out / "manifest.json").read_text())["projects"]) == 2
    assert json.loads((out / "run.json").read_text())["projects"]["written"] == 0
    seen = {r["token"]: [s["path"] for s in r["sightings"]] for r in provenance(out).values()}
    assert sorted(len(v) for v in seen.values()) == [1, 2]
    assert any(str(copy) in v and str(a) in v for v in seen.values())
    index = (out / "INDEX.md").read_text()
    assert "`copy.mdzip`" in index and "(program=X)" in index


def test_tree_rules_and_missing_inputs(tmp_path, capsys):
    foreign = tmp_path / "foreign"
    foreign.mkdir()
    (foreign / "notes.txt").write_text("mine")
    src = tmp_path / "drone.mdzip"
    src.write_bytes(make_mdzip())
    assert main([str(src), "-o", str(foreign), "--no-llm"]) == 2  # never write into an unrelated directory
    assert main(["run", "-o", str(tmp_path / "nothing")]) == 2
    assert "not a cameo-ingest output tree" in capsys.readouterr().err
    out = tmp_path / "out"
    assert main([str(src), "-o", str(out), "--no-llm", "--no-render"]) == 0
    src.unlink()  # the input disappears: its project stays (plan decision 3)
    assert main(["run", "-o", str(out)]) == 0
    [record] = provenance(out).values()
    assert record["status"] == "written" and record["sightings"][0]["missing"]
    assert "(input missing)" in (out / "INDEX.md").read_text()


def test_options_change_rewrites_projects(tmp_path, monkeypatch):
    """Output made with other options or another tool version is written again, and files
    the new version doesn't produce disappear with the old directory (plan RI-06)."""
    src = tmp_path / "drone.mdzip"
    src.write_bytes(make_mdzip())
    out = tmp_path / "out"
    assert main([str(src), "-o", str(out), "--no-llm"]) == 0
    proj = project_dir(out)
    assert (proj / "diagrams/Drone_BDD.png").exists()
    assert main(["run", "-o", str(out)]) == 0
    assert json.loads((out / "run.json").read_text())["projects"]["written"] == 0  # up to date
    assert main(["run", "-o", str(out), "--no-render"]) == 0
    assert json.loads((out / "run.json").read_text())["projects"]["written"] == 1
    assert not (proj / "diagrams/Drone_BDD.png").exists() and (proj / "README.md").exists()
    from cameo_ingest import runner

    monkeypatch.setattr(runner, "TOOL", "cameo-ingest/99")
    assert main(["run", "-o", str(out)]) == 0
    assert json.loads((out / "run.json").read_text())["projects"]["written"] == 1


def test_decompression_budget(tmp_path, monkeypatch):
    from cameo_ingest import archive

    monkeypatch.setattr(archive, "MAX_TOTAL_BYTES", 1000)
    src = tmp_path / "drone.mdzip"
    src.write_bytes(make_mdzip())
    out = tmp_path / "out"
    assert main([str(src), "-o", str(out), "--no-llm", "--no-render"]) == 4
    failed = json.loads((out / "manifest.json").read_text())["failed"]
    assert "exceeds 1,000 decompressed bytes" in failed[0]["error"]


def test_first_tag():
    from cameo_ingest.archive import first_tag, sniff_xmi

    decl = b"<?xml version='1.0' encoding='UTF-8' standalone='no'?>\n"
    assert first_tag(b"\xef\xbb\xbf" + decl + b"<!-- a <b> -->\n<mdOwnedViews>") == "mdOwnedViews"
    assert first_tag(b"\x89PNG\r\n\x1a\n") is None
    assert sniff_xmi(decl + b"<xmi:XMI xmlns:xmi='http://www.omg.org/spec/XMI/20131001'>")
    assert not sniff_xmi(decl + b"<Types xmlns='urn:x'>")


def test_omg_namespace_prefixes():
    from cameo_ingest.xmi import _prefix_for

    assert _prefix_for("http://www.omg.org/spec/UML/20131001", {}) == "uml"
    assert _prefix_for("http://schema.omg.org/spec/XMI/2.1", {}) == "xmi"
    std = "http://www.omg.org/spec/UML/20131001/StandardProfile"
    assert _prefix_for(std, {std: "StandardProfile"}) == "StandardProfile"


SAMPLES_DIR = Path(__file__).parent.parent / "samples"
SAMPLES = sorted(SAMPLES_DIR.glob("*.mdzip")) + sorted(SAMPLES_DIR.glob("resource_bundles/*.zip"))
SMALL = 5_000_000  # larger samples only run with `pytest -m slow`
SAF_CONTENTS = 8  # the .mdzip files in the SAF_Plugin bundle; the standalone copies add none
# Counts that changed when BASE-001, BASE-003 and BASE-013 were fixed; a change is a regression
# or a deliberate improvement, to be checked either way (BASE-007R2).
PINNED = {
    "Package_Delivery_Drone.mdzip": {
        "summary": {"elements": 839, "diagrams": 11, "stereotype_applications": 238, "relationships": 281,
                    "requirements": 42},
        "table_configs": 2, "diagrams_with_shapes": 9,
    },
    "TMT.mdzip": {  # slow
        "summary": {"elements": 71093, "diagrams": 1346, "stereotype_applications": 22551, "relationships": 7947,
                    "requirements": 4284},
        "table_configs": 100, "diagrams_with_shapes": 1171,
    },
}


@pytest.mark.parametrize("sample", [
    pytest.param(s, id=s.name, marks=() if s.stat().st_size < SMALL else pytest.mark.slow) for s in SAMPLES])
def test_samples(tmp_path, sample):
    out = tmp_path / "out"
    assert main([str(sample), "-o", str(out), "--no-llm", "--no-render"]) == 0
    check_invariants(out)
    expected = PINNED.get(sample.name)
    if expected:
        summary = json.loads((out / "manifest.json").read_text())["projects"][0]["summary"]
        assert {k: summary[k] for k in expected["summary"]} == expected["summary"]
        pages = [p.read_text(encoding="utf-8") for p in out.glob("by-sha256/*/diagrams/*.md")]
        assert sum("**Table / matrix configuration**" in p for p in pages) == expected["table_configs"]
        assert sum("**Shapes (" in p for p in pages) == expected["diagrams_with_shapes"]
        check_edge_directions(sample)


def check_edge_directions(sample: Path) -> None:
    """Every drawn edge that shows a model relationship between the shapes (or pins) at its
    ends runs from the relationship's source to its target (FU-001)."""
    from cameo_ingest import diagrams as dg
    from cameo_ingest import semantics as sem
    from cameo_ingest.archive import discover
    from cameo_ingest.pipeline import load_layouts, parse_project

    proj = next(discover(sample.read_bytes(), sample.name))
    ix = parse_project(proj)
    rels = {r.id: r for r in sem.relationships(ix)}
    flows = sem.item_flows(ix)
    checked = 0
    for layout in load_layouts(proj, ix).values():
        for lk in dg.build(ix, layout, rels, flows).links:
            rel = rels.get(lk.view.element or "")
            if rel is None or not lk.directed or lk.source is None or lk.target is None:
                continue
            ends = (lk.source.element, lk.target.element)
            if {rel.source, rel.target} == set(ends):
                assert ends == (rel.source, rel.target), (rel.metaclass, lk.view.view_id)
                checked += 1
    assert checked


SAF = [SAMPLES_DIR / "resource_bundles/SAF_Plugin_2026-09-16.zip",
       *(SAMPLES_DIR / n for n in ("SAF_FFDS.mdzip", "SAF_Blank.mdzip", "SAF_Profile.mdzip"))]


@pytest.mark.slow
@pytest.mark.skipif(not all(p.exists() for p in SAF), reason="samples not fetched (scripts/fetch_samples.py)")
def test_bundle_and_standalone_copies_share_projects(tmp_path):
    """BASE-017's evidence: three standalone samples are byte-identical to members of the
    SAF_Plugin bundle. Each is one project, seen twice."""
    out = tmp_path / "out"
    assert main([*map(str, SAF), "-o", str(out), "--no-llm", "--no-render"]) == 0
    check_invariants(out)
    records = provenance(out)
    for f in SAF[1:]:
        paths = [s["path"] for s in records[f"sha256:{hashlib.sha256(f.read_bytes()).hexdigest()}"]["sightings"]]
        assert sorted(Path(p).name for p in paths) == sorted([f.name, SAF[0].name])
    assert len(records) == len(list((out / "by-sha256").glob("[0-9a-f]*"))) == SAF_CONTENTS


class FakeOpenAI:
    """Stands in for openai.OpenAI: records requests and returns a fixed reply."""

    fail = False  # set on the class to make every request raise
    interrupt_at: int | None = None  # raise KeyboardInterrupt on this enrichment request (Ctrl-C)
    delay = 0.0  # seconds per request
    inflight = max_inflight = 0
    _lock = threading.Lock()

    def __init__(self, **kwargs):
        self.kwargs = kwargs
        self.requests: list[tuple[str, list]] = []
        self.chat = SimpleNamespace(completions=SimpleNamespace(create=self._create))

    def _create(self, model, messages, **kw):
        self.requests.append((model, messages))
        if self.interrupt_at is not None and len(self.enrichment()) == self.interrupt_at:
            raise KeyboardInterrupt
        if self.fail:
            raise RuntimeError("endpoint down")
        with FakeOpenAI._lock:
            FakeOpenAI.inflight += 1
            FakeOpenAI.max_inflight = max(FakeOpenAI.max_inflight, FakeOpenAI.inflight)
        time.sleep(self.delay)
        with FakeOpenAI._lock:
            FakeOpenAI.inflight -= 1
        reply = "A block definition diagram showing Drone composed of Battery."
        return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content=reply))])

    def close(self):
        pass

    def enrichment(self) -> list[tuple[str, list]]:
        """Requests other than the preflight check."""
        return [r for r in self.requests if PREFLIGHT_PROMPT not in json.dumps(r[1])]


@pytest.fixture
def fake_openai(monkeypatch) -> list[FakeOpenAI]:
    import openai

    made: list[FakeOpenAI] = []
    monkeypatch.setattr(openai, "OpenAI", lambda **kw: made.append(FakeOpenAI(**kw)) or made[-1])
    return made


def test_llm_enrichment_is_labelled(tmp_path, fake_openai):
    src = tmp_path / "drone.mdzip"
    src.write_bytes(make_mdzip())
    out = tmp_path / "out"
    assert main([str(src), "-o", str(out), "--vision-model", "gemma-4"]) == 0
    check_invariants(out)  # includes unique chunk ids for the two image descriptions (BASE-002)
    client = fake_openai[0]
    assert len(client.requests) == 4  # preflight, then the diagram and two images: no budget (BASE-019)
    assert [m for m, _ in client.enrichment()] == ["gemma-4"] * 3
    dia = (project_dir(out) / "diagrams/Drone_BDD.md").read_text()
    assert "generated by gemma-4; not part of the source model" in dia
    chunks = [json.loads(line) for line in (out / "chunks.jsonl").open()]
    record = (out / "run.json").read_text()
    assert json.loads(record)["options"]["vision_model"] == "gemma-4"
    assert "api_key" not in (record + (out / "manifest.json").read_text()).lower()
    gen = [c for c in chunks if c["metadata"]["kind"].startswith("generated:")]
    assert gen and all(c["metadata"]["provenance"]["derivation"]["method"] == "llm" for c in gen)
    assert sum(c["metadata"]["kind"] == "generated:image_description" for c in chunks) == 2
    extracted = [c for c in chunks if not c["metadata"]["kind"].startswith("generated:")]
    assert not any("gemma-4" in c["text"] for c in extracted)


def test_templates_and_request_log(tmp_path, fake_openai):
    """Prompts are named, versioned templates with described slots (plan LQ-01), and every
    request is logged with what it asked (LQ-02)."""
    import sqlite3

    from cameo_ingest.prompts import TEMPLATES

    for key, tpl in TEMPLATES.items():
        text_slots = [s.name for s in tpl.slots if s.kind == "text"]
        assert "{{" not in tpl.render({s: "x" for s in text_slots}), key
        shown = tpl.stand_in()
        assert all(f"⟦{s.name}" in shown or f"⟦IMAGE {s.name}" in shown for s in tpl.slots), key
    src = tmp_path / "drone.mdzip"
    src.write_bytes(make_mdzip())
    out = tmp_path / "out"
    assert main([str(src), "-o", str(out), "--text-model", "m", "--no-preflight"]) == 0
    token = f"sha256:{project_dir(out).name}"
    db = sqlite3.connect(out / ".cache/llm.sqlite")
    rows = db.execute("SELECT template, project, item, image_path, prompt, notes FROM requests ORDER BY template, "
                      "image_path").fetchall()
    assert [(r[0], r[3]) for r in rows] == [("diagram-description@v2", "diagrams/Drone_BDD.png"),
                                           ("image-description@v1", "images/BINARY-img1.png"),
                                           ("image-description@v1", "images/BINARY-img2.png"),
                                           ("package-summary@v2", None)]
    assert all(r[1] == token and r[2].startswith(token[:23]) for r in rows)
    assert rows[0][4].startswith(TEMPLATES["diagram-description@v2"].text.split("{{")[0])
    assert "Diagram: Drone BDD (SysML Block Definition Diagram)" in rows[0][4]
    chunks = [json.loads(line) for line in (out / "chunks.jsonl").open()]
    templates = {c["metadata"]["provenance"]["derivation"].get("template") for c in chunks
                 if c["metadata"]["kind"].startswith("generated:")}
    assert templates == {"diagram-description@v2", "image-description@v1", "package-summary@v2"}


def test_quality_sample(tmp_path, fake_openai, capsys):
    """A spot-check set shows each template with stand-ins, and each item with its request,
    image, response, and reference without the response (plan LQ-03)."""
    src = tmp_path / "drone.mdzip"
    src.write_bytes(make_mdzip())
    out = tmp_path / "out"
    assert main([str(src), "-o", str(out), "--text-model", "m", "--no-preflight"]) == 0
    drawn = []
    for _ in range(2):  # the same seed draws the same items
        assert main(["quality", "sample", "-o", str(out), "--n", "3", "--seed", "7"]) == 0
        set_dir = Path(capsys.readouterr().out.split("spot-check set ")[1].split(":")[0])
        items = [json.loads(line) for line in (set_dir / "items.jsonl").open()]
        drawn.append((set_dir.name, [i["id"] for i in items]))
    assert drawn[0][1] == drawn[1][1] and drawn[0][0] != drawn[1][0]
    assert sorted(i["kind"] for i in items) == ["diagram_description", "image_description", "summary"]
    for it in items:
        assert it["response"] and it["response"] not in it["reference"], it["kind"]
    summary = next(i for i in items if i["kind"] == "summary")
    assert "Model::Structure" in summary["prompt"] and summary["image"] is None
    page = (set_dir / "index.html").read_text()
    assert '<span class="slot">⟦LEGEND:' in page and '<span class="slot">⟦IMAGE SKETCH' in page
    assert page.count("src='data:image/png;base64,") == 2  # the diagram sketch and the embedded image
    with (set_dir / "rate-items.csv").open() as f:
        assert [r["item"] for r in csv.DictReader(f)] == [i["id"] for i in items]
    with (set_dir / "rate-templates.csv").open() as f:
        assert {r["template"] for r in csv.DictReader(f)} == {i["template"] for i in items}


def test_llm_call_budget(tmp_path, fake_openai):
    src = tmp_path / "drone.mdzip"
    src.write_bytes(make_mdzip())
    out = tmp_path / "out"
    assert main([str(src), "-o", str(out), "--vision-model", "m", "--llm-max-calls", "1"]) == 0
    assert len(fake_openai[0].enrichment()) == 1
    report = json.loads((out / "run.json").read_text())["llm"]
    assert report["calls"] == 1 and report["outcomes"]["skipped_budget"] == 2
    assert all(i["item"].startswith("sha256:") for i in report["incomplete"])


def test_llm_store_and_replay(tmp_path, fake_openai, monkeypatch):
    src = tmp_path / "drone.mdzip"
    src.write_bytes(make_mdzip())
    store = tmp_path / "store"
    args = [str(src), "--vision-model", "m", "--cache-dir", str(store), "--meta", "program=test"]
    trees = []
    for i in range(2):  # the second run is answered from the store (BASE-005)
        out = tmp_path / f"out{i}"
        assert main([*args, "-o", str(out)]) == 0
        trees.append(tree(out))
    report = json.loads((out / "run.json").read_text())["llm"]
    assert report["calls"] == 0 and report["outcomes"] == {"cached": 3}
    # Replay never touches the network; it reproduces the recorded run exactly (BASE-022R5).
    monkeypatch.setattr(FakeOpenAI, "fail", True)
    out = tmp_path / "replayed"
    assert main([str(src), "--vision-model", "m", "--llm-replay", str(store / "llm.sqlite"),
                 "--meta", "program=test", "-o", str(out)]) == 0
    assert json.loads((out / "run.json").read_text())["llm"]["outcomes"] == {"replayed": 3}
    assert tree(out) == trees[1]
    assert len(fake_openai) == 2  # no client at all in replay mode
    # A request the store has no answer for fails the project, loudly.
    out = tmp_path / "missed"
    assert main([str(src), "--vision-model", "other", "--llm-replay", str(store / "llm.sqlite"), "-o", str(out)]) == 4
    assert "ReplayMiss: no recorded other response" in json.loads((out / "manifest.json").read_text())["failed"][0]["error"]


def test_llm_store_corrupt(tmp_path, fake_openai, caplog):
    import sqlite3

    store = tmp_path / "store"
    store.mkdir()
    (store / "llm.sqlite").write_bytes(b"not a database, e.g. a file cut short by a killed run")
    src = tmp_path / "drone.mdzip"
    src.write_bytes(make_mdzip())
    out = tmp_path / "out"
    assert main([str(src), "-o", str(out), "--vision-model", "m", "--cache-dir", str(store)]) == 0  # BASE-005
    assert "is unreadable" in caplog.text and list(store.glob("llm.sqlite.corrupt-*"))
    assert sqlite3.connect(store / "llm.sqlite").execute("SELECT count(*) FROM responses").fetchone() == (3,)


def test_llm_circuit_breaker(tmp_path, fake_openai, monkeypatch):
    monkeypatch.setattr(FakeOpenAI, "fail", True)
    src = tmp_path / "drone.mdzip"
    src.write_bytes(make_mdzip())
    out = tmp_path / "out"
    # Four items (a diagram, two images, a package summary); the endpoint fails every request.
    assert main([str(src), "-o", str(out), "--text-model", "m", "--no-preflight"]) == 0
    assert len(fake_openai[0].requests) == 3  # then enrichment is switched off (BASE-006)
    report = json.loads((out / "run.json").read_text())["llm"]
    assert report["disabled_after_failures"] and report["outcomes"] == {"failed": 3, "skipped_disabled": 1}
    assert report["incomplete"][0]["detail"] == "RuntimeError: endpoint down"


def test_no_model_fails_fast(tmp_path, capsys):
    src = tmp_path / "drone.mdzip"
    src.write_bytes(make_mdzip())
    out = tmp_path / "out"
    assert main([str(src), "-o", str(out)]) == 2  # BASE-020
    err = capsys.readouterr().err
    assert "--no-llm" in err and "--env" in err and "OPENAI_MODEL" in err
    assert not out.exists()


def test_env_file_and_preflight(tmp_path, capsys, caplog):
    caplog.set_level(logging.INFO)
    env = tmp_path / "test.env"
    env.write_text("OPENAI_MODEL=file-model\nOPENAI_API_KEY=sk-secret-123\nOPENAI_BASE_URL=http://127.0.0.1:9/v1\n")
    os.environ["OPENAI_MODEL"] = "shell-model"  # already set, so the file's value is not used
    src = tmp_path / "drone.mdzip"
    src.write_bytes(make_mdzip())
    out = tmp_path / "out"
    # Nothing listens on port 9: the preflight check fails before any parsing (BASE-020).
    assert main([str(src), "-o", str(out), "--env", str(env), "--llm-retries", "0", "--llm-timeout", "5", "-v"]) == 5
    err = capsys.readouterr().err
    assert "shell-model" in err and "127.0.0.1:9" in err
    assert "loaded OPENAI_API_KEY, OPENAI_BASE_URL from" in caplog.text and "not loaded: OPENAI_MODEL" in caplog.text
    assert "sk-secret-123" not in err + caplog.text
    assert not out.exists()
    assert logging.getLogger("httpx").getEffectiveLevel() == logging.WARNING  # quiet below -vv (BASE-018)


REPLAY = Path(__file__).parent / "fixtures" / "llm-replay.sqlite"


@pytest.mark.skipif(not REPLAY.exists(), reason="no recorded LLM fixture (scripts/record_llm_fixture.py)")
@pytest.mark.parametrize("sample", ["fixture", "Package_Delivery_Drone.mdzip"])
def test_replay_recorded_llm(tmp_path, sample):
    """Real model answers, recorded by scripts/record_llm_fixture.py, replayed offline
    (BASE-022R5). A ReplayMiss here means a prompt or the input changed: record again."""
    import sqlite3

    if sample == "fixture":
        src = tmp_path / "drone.mdzip"
        src.write_bytes(make_mdzip())
    else:
        src = SAMPLES_DIR / sample
        if not src.exists():
            pytest.skip("sample not fetched (scripts/fetch_samples.py --small)")
    db = sqlite3.connect(f"file:{REPLAY}?mode=ro", uri=True)
    model = db.execute("SELECT model FROM responses LIMIT 1").fetchone()[0]
    db.close()
    out = tmp_path / "out"
    assert main([str(src), "-o", str(out), "--no-render", "--text-model", model, "--llm-replay", str(REPLAY)]) == 0
    check_invariants(out)
    report = json.loads((out / "run.json").read_text())["llm"]
    assert report["incomplete"] == [] and set(report["outcomes"]) - {"truncated_input"} == {"replayed"}
    gen = [c for c in map(json.loads, (out / "chunks.jsonl").open()) if c["metadata"]["kind"].startswith("generated:")]
    assert gen and all(c["metadata"]["provenance"]["derivation"]["model"] == model for c in gen)


def test_progress_heartbeats_and_log_file(tmp_path, fake_openai, monkeypatch, capsys):
    monkeypatch.setattr(FakeOpenAI, "delay", 0.1)
    src = tmp_path / "drone.mdzip"
    src.write_bytes(make_mdzip())
    log_file = tmp_path / "run.log"
    # Not a terminal, default verbosity: heartbeat lines still reach the console (BASE-018).
    assert main([str(src), "-o", str(tmp_path / "out"), "--vision-model", "m", "--heartbeat", "0.05",
                 "--log-file", str(log_file)]) == 0
    err = capsys.readouterr().err
    assert re.search(r"drone\.mdzip: LLM: \d requests? of 3 requests \(\d+%\)", err)
    assert "drone.mdzip: LLM: 3 requests in" in err and "found 1 project" not in err  # -v lines stay hidden
    logged = log_file.read_text()
    assert "DEBUG" in logged and "LLM m answered for sha256:" in logged and "found 1 project" in logged


def test_llm_concurrency(tmp_path, fake_openai, monkeypatch):
    monkeypatch.setattr(FakeOpenAI, "delay", 0.1)
    monkeypatch.setattr(FakeOpenAI, "max_inflight", 0)
    src = tmp_path / "drone.mdzip"
    src.write_bytes(make_mdzip())
    trees = []
    for n in (1, 3):
        out = tmp_path / f"out{n}"
        assert main([str(src), "-o", str(out), "--vision-model", "m", "--cache-dir", str(tmp_path / f"store{n}"),
                     "--llm-concurrency", str(n)]) == 0
        trees.append(tree(out))
    assert FakeOpenAI.max_inflight >= 2  # requests overlapped (BASE-019R4)...
    assert trees[0] == trees[1]  # ...and the output is the same as a sequential run


def test_interrupt_and_resume(tmp_path, fake_openai, monkeypatch, capsys):
    """A run stopped part-way continues where it stopped, and ends with the same output as a
    run that was never interrupted (plan RI-07)."""
    src = tmp_path / "drone.mdzip"
    src.write_bytes(make_mdzip())
    ref = tmp_path / "ref"
    assert main([str(src), "-o", str(ref), "--vision-model", "m", "--no-preflight"]) == 0
    monkeypatch.setattr(FakeOpenAI, "interrupt_at", 2)  # Ctrl-C during the second LLM request
    out = tmp_path / "out"
    assert main([str(src), "-o", str(out), "--vision-model", "m", "--no-preflight"]) == 130
    assert "Continue with: cameo-ingest run -o" in capsys.readouterr().err
    assert json.loads((out / "run.json").read_text())["outcome"] == "interrupted"
    assert json.loads((out / "manifest.json").read_text())["projects"] == []  # nothing half-published
    [work] = (out / "by-sha256/.work").iterdir()
    sketch = (work / "diagrams/Drone_BDD.png").stat().st_mtime_ns  # drawn before the interruption
    monkeypatch.setattr(FakeOpenAI, "interrupt_at", None)
    assert main(["run", "-o", str(out), "--no-preflight"]) == 0  # the tree remembers the model
    assert json.loads((out / "run.json").read_text())["llm"]["outcomes"] == {"answered": 2, "cached": 1}
    assert (project_dir(out) / "diagrams/Drone_BDD.png").stat().st_mtime_ns == sketch  # reused, not redrawn
    assert tree(out) == tree(ref)


def test_status_and_prune(tmp_path, capsys):
    a, b = tmp_path / "a.mdzip", tmp_path / "b.mdzip"
    a.write_bytes(make_mdzip())
    b.write_bytes(make_mdzip(MODEL.replace("name='Requirements'", "name='Needs'")))
    out = tmp_path / "out"
    assert main([str(a), str(b), "-o", str(out), "--no-llm", "--no-render"]) == 0
    b.unlink()
    assert main(["run", "-o", str(out)]) == 0
    capsys.readouterr()
    assert main(["status", "-o", str(out), "--json"]) == 0
    s = json.loads(capsys.readouterr().out)
    assert s["inputs"]["counts"] == {"done": 1, "missing": 1} and s["projects"]["counts"] == {"written": 2}
    assert s["inputs"]["problems"] == [{"path": str(b), "status": "missing", "error": None}]
    assert s["latest_run"]["outcome"] == "finished"
    assert main(["prune", "-o", str(out), "--dry-run"]) == 0
    assert "would remove 1 missing input(s) and 1 project(s)" in capsys.readouterr().out
    assert len(list((out / "by-sha256").glob("[0-9a-f]*"))) == 2
    assert main(["prune", "-o", str(out)]) == 0
    assert [p["name"] for p in json.loads((out / "manifest.json").read_text())["projects"]] == ["a.mdzip"]
    assert len(list((out / "by-sha256").glob("[0-9a-f]*"))) == 1
    capsys.readouterr()
    assert main(["status", "-o", str(out)]) == 0
    assert "inputs: 1 done\nprojects: 1 written\n" in capsys.readouterr().out


def test_ledger(tmp_path):
    out = run(tmp_path, "drone.mdzip", make_mdzip())
    proj = project_dir(out)
    ledger = (proj / "LEDGER.md").read_text()
    assert "**R-1**" in ledger and "The drone shall fly 30 min." in ledger
    assert "satisfied by: Battery" in ledger and "refined by: Drone" in ledger
    assert "Drone BDD" in ledger and "SysML Block Definition Diagram" in ledger
    assert f"by-sha256/{proj.name}/LEDGER.md" in (out / "INDEX.md").read_text()

    chunks = [json.loads(line) for line in (out / "chunks.jsonl").open()]
    kinds = {c["metadata"]["kind"] for c in chunks}
    assert {"ledger:projects", "ledger:packages", "ledger:diagrams", "ledger:requirements",
            "ledger:elements"} <= kinds
    req = next(c for c in chunks if c["metadata"]["kind"] == "ledger:requirements")
    # Self-describing header, no link noise, and ids row-for-row for the application.
    assert "Model::Requirements" in req["text"] and "drone.mdzip" in req["text"]
    assert "](" not in req["text"]
    assert req["metadata"]["element_ids"] == ["r1"]
    assert req["metadata"]["provenance"]["xmi_id"] == "p2"


def test_ledger_natural_sort_and_split():
    from cameo_ingest.ledger import _natural_key

    ids = ["REQ.1.10", "REQ.1.2", "REQ.1", "REQ.2"]
    assert sorted(ids, key=_natural_key) == ["REQ.1", "REQ.1.2", "REQ.1.10", "REQ.2"]
