import csv
import io
import json
import zipfile
from pathlib import Path

import pytest

from cameo_ingest.cli import main

MODEL = """<?xml version='1.0' encoding='UTF-8'?>
<xmi:XMI xmlns:xmi='http://www.omg.org/spec/XMI/20131001' xmlns:uml='http://www.omg.org/spec/UML/20131001'
  xmlns:sysml='http://www.omg.org/spec/SysML/20181001/SysML'>
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
  </packagedElement>
  <packagedElement xmi:type='uml:Package' xmi:id='p2' name='Requirements'>
   <packagedElement xmi:type='uml:Class' xmi:id='r1' name='Endurance'/>
   <packagedElement xmi:type='uml:Abstraction' xmi:id='s1' client='b2' supplier='r1'/>
  </packagedElement>
 </uml:Model>
 <sysml:Block xmi:id='st1' base_Class='b1'/>
 <sysml:Block xmi:id='st2' base_Class='b2'/>
 <sysml:Requirement xmi:id='st3' base_Class='r1' Id='R-1'
   Text='&lt;html&gt;&lt;body&gt;&lt;p&gt;The drone &lt;b&gt;shall&lt;/b&gt; fly 30 min.&lt;/p&gt;&lt;/body&gt;&lt;/html&gt;'/>
 <sysml:Satisfy xmi:id='st4' base_Abstraction='s1'/>
</xmi:XMI>
"""

LAYOUT = """<?xml version='1.0' encoding='UTF-8'?>
<mdOwnedViews>
 <mdElement elementClass='Class' xmi:id='v1'><elementID xmi:idref='b1'/><geometry>10, 10, 100, 60</geometry></mdElement>
 <mdElement elementClass='Class' xmi:id='v2'><elementID xmi:idref='b2'/><geometry>200, 10, 100, 60</geometry></mdElement>
 <mdElement elementClass='Association' xmi:id='v3'><linkFirstEndID xmi:idref='v1'/><linkSecondEndID xmi:idref='v2'/>
  <geometry>110, 40; 200, 40; </geometry></mdElement>
</mdOwnedViews>
"""


def make_mdzip() -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        z.writestr("com.nomagic.magicdraw.uml_model.model", MODEL)
        z.writestr("BINARY-1", LAYOUT)
        z.writestr("Records.properties", "#Compatibility entry\n")
    return buf.getvalue()


def run(tmp_path: Path, name: str, data: bytes) -> Path:
    src = tmp_path / name
    src.write_bytes(data)
    out = tmp_path / "out"
    assert main([str(src), "-o", str(out), "--meta", "program=test", "--no-llm"]) == 0
    return out


def test_mdzip_end_to_end(tmp_path):
    out = run(tmp_path, "drone.mdzip", make_mdzip())
    proj = out / "drone.mdzip"
    reqs = list(csv.DictReader((proj / "tables/requirements.csv").open()))
    assert [(r["req_id"], r["text"]) for r in reqs] == [("R-1", "The drone shall fly 30 min.")]
    assert "Satisfy_in" in reqs[0]["relationships"]

    rels = list(csv.DictReader((proj / "tables/relationships.csv").open()))
    assert {(r["kind"], r["source"], r["target"]) for r in rels} >= {
        ("Satisfy", "Model::Structure::Battery", "Model::Requirements::Endurance")}

    dia = (proj / "diagrams/Drone_BDD.md").read_text()
    assert "SysML Block Definition Diagram" in dia
    assert "Drone" in dia and "Battery" in dia and "[Association]" in dia
    assert (proj / "diagrams/Drone_BDD.png").exists()

    pkg = (proj / "packages/Model__Structure.md").read_text()
    assert "A delivery drone." in pkg and "battery" in pkg and "[1..2]" in pkg


def test_provenance_everywhere(tmp_path):
    out = run(tmp_path, "drone.mdzip", make_mdzip())
    manifest = json.loads((out / "manifest.json").read_text())
    assert manifest["run"]["source"]["metadata"] == {"program": "test"}
    for md in out.rglob("*.md"):
        text = md.read_text()
        assert text.startswith("---\n") and "provenance:" in text.split("\n---\n")[0], md
    for f in out.rglob("*.csv"):
        rows = list(csv.DictReader(f.open()))
        assert all(r.get("trace", "").startswith("sha256:") for r in rows), f
    chunks = [json.loads(line) for line in (out / "chunks.jsonl").open()]
    assert chunks
    for c in chunks:
        p = c["metadata"]["provenance"]
        assert p["source_sha256"] == manifest["run"]["source"]["sha256"]
        assert p["locator"].startswith("sha256:")
    req = next(c for c in chunks if c["metadata"]["kind"] == "requirement")
    assert req["metadata"]["provenance"]["xmi_id"] == "r1"
    assert req["metadata"]["provenance"]["line"]


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


SAMPLES = sorted((Path(__file__).parent.parent / "samples").glob("*.mdzip"))


@pytest.mark.parametrize("sample", [s for s in SAMPLES if s.stat().st_size < 5_000_000], ids=lambda p: p.name)
def test_public_samples(tmp_path, sample):
    out = tmp_path / "out"
    assert main([str(sample), "-o", str(out), "--no-llm", "--no-render"]) == 0
    assert (out / "manifest.json").exists()


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
    assert calls and calls[0][0] == "gemma-4"
    dia = (out / "drone.mdzip/diagrams/Drone_BDD.md").read_text()
    assert "generated by gemma-4; not part of the source model" in dia
    chunks = [json.loads(line) for line in (out / "chunks.jsonl").open()]
    manifest = json.loads((out / "manifest.json").read_text())
    assert manifest["run"]["llm"]["vision_model"] == "gemma-4"
    assert "api_key" not in json.dumps(manifest).lower()
    gen = [c for c in chunks if c["metadata"]["kind"].startswith("generated:")]
    assert gen and all(c["metadata"]["provenance"]["derivation"]["method"] == "llm" for c in gen)
    extracted = [c for c in chunks if not c["metadata"]["kind"].startswith("generated:")]
    assert not any("gemma-4" in c["text"] for c in extracted)


def test_ledger(tmp_path):
    out = run(tmp_path, "drone.mdzip", make_mdzip())
    ledger = (out / "drone.mdzip/LEDGER.md").read_text()
    assert "**R-1**" in ledger and "The drone shall fly 30 min." in ledger
    assert "satisfied by: Battery" in ledger
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
