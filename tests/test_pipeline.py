import csv
import io
import json
import re
import zipfile
from collections import Counter
from pathlib import Path

import pytest
from PIL import Image

from cameo_ingest.cli import main

csv.field_size_limit(1 << 30)  # documentation columns in large models exceed the default

# Two names that share their first 140 characters, longer than the anchor's name part.
LONG = "Gravity calibration duration scenario for the operational blackbox entries " * 2

MODEL = """<?xml version='1.0' encoding='UTF-8'?>
<xmi:XMI xmlns:xmi='http://www.omg.org/spec/XMI/20131001' xmlns:uml='http://www.omg.org/spec/UML/20131001'
  xmlns:sysml='http://www.omg.org/spec/SysML/20181001/SysML'
  xmlns:MagicDraw_Profile='http://www.omg.org/spec/UML/20131001/MagicDrawProfile'
  xmlns:StandardProfile='http://www.omg.org/spec/UML/20131001/StandardProfile'>
 <xmi:Documentation><xmi:exporter>MagicDraw UML</xmi:exporter><xmi:exporterVersion>2024x</xmi:exporterVersion></xmi:Documentation>
 <uml:Model xmi:type='uml:Model' xmi:id='m1' name='Model'>
  <packagedElement xmi:type='uml:Package' xmi:id='p1' name='Structure'>
   <packagedElement xmi:type='uml:Class' xmi:id='b1' name='Drone'>
    <ownedComment xmi:type='uml:Comment' xmi:id='c1' body='A delivery drone.'><annotatedElement xmi:idref='b1'/></ownedComment>
    <ownedAttribute xmi:type='uml:Property' xmi:id='a1' name='battery' aggregation='composite' type='b2'>
     <lowerValue xmi:type='uml:LiteralInteger' xmi:id='a1l' value='1'/>
     <upperValue xmi:type='uml:LiteralUnlimitedNatural' xmi:id='a1u' value='2'/>
    </ownedAttribute>
    <xmi:Extension extender='MagicDraw UML 2024x'><modelExtension>
     <ownedDiagram xmi:type='uml:Diagram' xmi:id='d1' name='Drone BDD' ownerOfDiagram='b1'>
      <xmi:Extension extender='MagicDraw UML 2024x'><diagramRepresentation>
       <diagram:DiagramRepresentationObject xmlns:diagram='http://www.nomagic.com/ns/magicdraw/core/diagram/1.0'
          type='SysML Block Definition Diagram' umlType='Class Diagram'>
        <diagramContents><binaryObject streamContentID='BINARY-1'/></diagramContents>
       </diagram:DiagramRepresentationObject>
      </diagramRepresentation></xmi:Extension>
     </ownedDiagram>
    </modelExtension></xmi:Extension>
   </packagedElement>
   <packagedElement xmi:type='uml:Class' xmi:id='b2' name='Battery'/>
   <packagedElement xmi:type='uml:Class' xmi:id='long1' name='LONG alpha'/>
   <packagedElement xmi:type='uml:Class' xmi:id='long2' name='LONG beta'/>
  </packagedElement>
  <packagedElement xmi:type='uml:Package' xmi:id='p2' name='Requirements'>
   <packagedElement xmi:type='uml:Class' xmi:id='r1' name='Endurance'/>
   <packagedElement xmi:type='uml:Abstraction' xmi:id='s1' client='b2' supplier='r1'/>
   <packagedElement xmi:type='uml:Abstraction' xmi:id='rf1' client='b1' supplier='r1'/>
   <xmi:Extension extender='MagicDraw UML 2024x'><modelExtension>
    <ownedDiagram xmi:type='uml:Diagram' xmi:id='d2' name='Req Table' ownerOfDiagram='p2'>
     <xmi:Extension extender='MagicDraw UML 2024x'><diagramRepresentation>
      <diagram:DiagramRepresentationObject xmlns:diagram='http://www.nomagic.com/ns/magicdraw/core/diagram/1.0'
         type='Requirement Table' umlType='Class Diagram'>
       <diagramContents><binaryObject/></diagramContents>
      </diagram:DiagramRepresentationObject>
     </diagramRepresentation></xmi:Extension>
    </ownedDiagram>
   </modelExtension></xmi:Extension>
  </packagedElement>
 </uml:Model>
 <sysml:Block xmi:id='st1' base_Class='b1'/>
 <sysml:Block xmi:id='st2' base_Class='b2'/>
 <sysml:Requirement xmi:id='st3' base_Class='r1' Id='R-1'
   Text='&lt;html&gt;&lt;body&gt;&lt;p&gt;The drone &lt;b&gt;shall&lt;/b&gt; fly 30 min.&lt;/p&gt;&lt;/body&gt;&lt;/html&gt;'/>
 <sysml:Satisfy xmi:id='st4' base_Abstraction='s1'/>
 <StandardProfile:Refine xmi:id='st5' base_Abstraction='rf1'/>
 <MagicDraw_Profile:DiagramInfo xmi:id='st6' base_Diagram='d1' Author='tester'/>
 <MagicDraw_Profile:DiagramTable xmi:id='st7' base_Diagram='d2' displayMode='List' additionalElements='r1 b1'>
  <columnIds>QPROP:Element:name</columnIds>
 </MagicDraw_Profile:DiagramTable>
</xmi:XMI>
""".replace("LONG", LONG)

# The XML declaration is the one TMT uses; it pushes the root tag past byte 64 (BASE-013).
LAYOUT = """<?xml version='1.0' encoding='UTF-8' standalone='no'?>
<mdOwnedViews>
 <mdElement elementClass='Class' xmi:id='v1'><elementID xmi:idref='b1'/><geometry>10, 10, 100, 60</geometry></mdElement>
 <mdElement elementClass='Class' xmi:id='v2'><elementID xmi:idref='b2'/><geometry>200, 10, 100, 60</geometry></mdElement>
 <mdElement elementClass='Association' xmi:id='v3'><linkFirstEndID xmi:idref='v1'/><linkSecondEndID xmi:idref='v2'/>
  <geometry>110, 40; 200, 40; </geometry></mdElement>
</mdOwnedViews>
"""


def png(color: str) -> bytes:
    buf = io.BytesIO()
    Image.new("RGB", (16, 16), color).save(buf, "PNG")
    return buf.getvalue()


def make_mdzip(model: str = MODEL) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        z.writestr("com.nomagic.magicdraw.uml_model.model", model)
        z.writestr("BINARY-1", LAYOUT)
        z.writestr("BINARY-img1", png("red"))
        z.writestr("BINARY-img2", png("blue"))
        z.writestr("Records.properties", "#Compatibility entry\n")
    return buf.getvalue()


def run(tmp_path: Path, name: str, data: bytes) -> Path:
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
        dup = [a for a, n in Counter(re.findall(r"\{#([^}]+)\}", text)).items() if n > 1]
        assert not dup, (md, dup[:3])
    for f in out.rglob("*.csv"):
        with f.open(encoding="utf-8", newline="") as fh:
            assert all(r.get("trace", "").startswith("sha256:") for r in csv.DictReader(fh)), f
    chunks = [json.loads(line) for line in (out / "chunks.jsonl").open(encoding="utf-8")]
    dup = [i for i, n in Counter(c["id"] for c in chunks).items() if n > 1]
    assert not dup, dup[:3]
    for c in chunks:  # LLM text only in labelled generated:* chunks (BASE-025)
        if c["metadata"]["provenance"]["derivation"]["method"] == "llm":
            assert c["metadata"]["kind"].startswith("generated:"), c["id"]
            assert "not part of the source model" in c["text"], c["id"]
    # A `base_*` attribute or reference means a stereotype application was read as an element.
    for f in out.glob("*/index/elements.jsonl"):
        for line in f.open(encoding="utf-8"):
            rec = json.loads(line)
            assert not any(n.startswith("base_") for n in [*rec["attrs"], *(r for r, _ in rec["refs"])]), rec["id"]


def test_mdzip_end_to_end(tmp_path):
    out = run(tmp_path, "drone.mdzip", make_mdzip())
    check_invariants(out)
    proj = out / "drone.mdzip"
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
    assert "-long1}" in pkg and "-long2}" in pkg  # anchors keep the id after long names (BASE-003)


def test_provenance_everywhere(tmp_path):
    out = run(tmp_path, "drone.mdzip", make_mdzip())
    manifest = json.loads((out / "manifest.json").read_text())
    assert manifest["run"]["source"]["metadata"] == {"program": "test"}
    chunks = [json.loads(line) for line in (out / "chunks.jsonl").open()]
    assert chunks
    for c in chunks:
        p = c["metadata"]["provenance"]
        assert p["source_sha256"] == manifest["run"]["source"]["sha256"]
        assert p["locator"].startswith("sha256:")
    req = next(c for c in chunks if c["metadata"]["kind"] == "requirement")
    assert req["metadata"]["provenance"]["xmi_id"] == "r1"
    assert req["metadata"]["provenance"]["line"]
    assert "provenance:" in (out / "drone.mdzip/images.md").read_text()  # BASE-024


def test_nested_bundle(tmp_path):
    inner = io.BytesIO()
    with zipfile.ZipFile(inner, "w") as z:
        z.writestr("samples/drone.mdzip", make_mdzip())
    outer = io.BytesIO()
    with zipfile.ZipFile(outer, "w") as z:
        z.writestr("resource.zip", inner.getvalue())
    out = run(tmp_path, "bundle.rdzip", outer.getvalue())
    chunks = [json.loads(line) for line in (out / "chunks.jsonl").open()]
    assert chunks[0]["metadata"]["provenance"]["container"] == ["bundle.rdzip", "resource.zip", "samples/drone.mdzip"]


def test_rejects_non_model(tmp_path):
    src = tmp_path / "x.mdzip"
    src.write_bytes(b"not a zip")
    assert main([str(src), "-o", str(tmp_path / "out")]) == 3


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
    assert [p["dir"] for p in manifest["projects"]] == ["good.mdzip"]
    assert [f["dir"] for f in manifest["failed"]] == ["bad.mdzip"]
    assert "XMLSyntaxError" in manifest["failed"][0]["error"]
    assert "skipping nested member bundle.rdzip!corrupt.mdzip" in caplog.text
    check_invariants(out)


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
        summary = json.loads((out / "manifest.json").read_text())["projects"][0]
        assert {k: summary[k] for k in expected["summary"]} == expected["summary"]
        pages = [p.read_text(encoding="utf-8") for p in out.glob("*/diagrams/*.md")]
        assert sum("**Table / matrix configuration**" in p for p in pages) == expected["table_configs"]
        assert sum("**Shapes (" in p for p in pages) == expected["diagrams_with_shapes"]


def test_llm_enrichment_is_labelled(tmp_path, monkeypatch):
    from cameo_ingest import llm as llm_mod

    calls = []

    def fake_complete(self, model, messages, key_material):
        calls.append((model, messages))
        return "A block definition diagram showing Drone composed of Battery."

    monkeypatch.setattr(llm_mod.LLM, "_complete", fake_complete)
    def fake_init(self, cfg, cache_dir):
        self.cfg, self.calls, self._client = cfg, 0, None

    monkeypatch.setattr(llm_mod.LLM, "__init__", fake_init)
    src = tmp_path / "drone.mdzip"
    src.write_bytes(make_mdzip())
    out = tmp_path / "out"
    assert main([str(src), "-o", str(out), "--vision-model", "gemma-4"]) == 0
    check_invariants(out)  # includes unique chunk ids for the two image descriptions (BASE-002)
    assert calls and calls[0][0] == "gemma-4"
    dia = (out / "drone.mdzip/diagrams/Drone_BDD.md").read_text()
    assert "generated by gemma-4; not part of the source model" in dia
    chunks = [json.loads(line) for line in (out / "chunks.jsonl").open()]
    manifest = json.loads((out / "manifest.json").read_text())
    assert manifest["run"]["llm"]["vision_model"] == "gemma-4"
    assert "api_key" not in json.dumps(manifest).lower()
    gen = [c for c in chunks if c["metadata"]["kind"].startswith("generated:")]
    assert gen and all(c["metadata"]["provenance"]["derivation"]["method"] == "llm" for c in gen)
    assert sum(c["metadata"]["kind"] == "generated:image_description" for c in chunks) == 2
    extracted = [c for c in chunks if not c["metadata"]["kind"].startswith("generated:")]
    assert not any("gemma-4" in c["text"] for c in extracted)


def test_ledger(tmp_path):
    out = run(tmp_path, "drone.mdzip", make_mdzip())
    ledger = (out / "drone.mdzip/LEDGER.md").read_text()
    assert "**R-1**" in ledger and "The drone shall fly 30 min." in ledger
    assert "satisfied by: Battery" in ledger and "refined by: Drone" in ledger
    assert "Drone BDD" in ledger and "SysML Block Definition Diagram" in ledger
    assert "drone.mdzip/LEDGER.md" in (out / "LEDGER.md").read_text()

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
