"""Reading models: archives, bundles, XMI details and decompression budgets."""

import hashlib
import io
import json
import zipfile

from fixture_model import make_mdzip
from helpers import (
    check_invariants,
    cli,
    project_dir,
    provenance,
    run,
)


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


def test_rejects_non_model(tmp_path):
    src = tmp_path / "x.mdzip"
    src.write_bytes(b"not a zip")
    assert cli([str(src), "-o", str(tmp_path / "out"), "--no-llm"]) == 3


def test_decompression_budget(tmp_path, monkeypatch):
    from cameo_ingest import archive

    monkeypatch.setattr(archive, "MAX_TOTAL_BYTES", 1000)
    src = tmp_path / "drone.mdzip"
    src.write_bytes(make_mdzip())
    out = tmp_path / "out"
    assert cli([str(src), "-o", str(out), "--no-llm", "--no-render"]) == 4
    failed = json.loads((out / "manifest.json").read_text())["failed"]
    assert "exceeds 1,000 decompressed bytes" in failed[0]["error"]


def test_long_tagged_values():
    """Hex-encoded images are described, other long values cut (FU-020)."""
    from cameo_ingest.text import shown_value

    svg = " ".join(f"{b:x}" for b in b'<?xml version="1.0"?>\n<svg xmlns="x">' + b"a" * 5000)
    assert shown_value(svg) == "(SVG image, 5,037 bytes, hex-encoded; not shown)"
    assert shown_value("x" * 5000).endswith("… (cut; 5,000 characters in all)")
    assert shown_value("a b c") == "a b c"


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


def test_used_objects_list_what_a_table_shows(tmp_path):
    """Cameo writes a diagram's `usedObjects` as href='#id'. A diagram without a layout, such as a
    table, lists them as the elements shown when last saved, and they link back to it; a drawn
    diagram lists what it draws, not what is shown inside shapes (BASE-013)."""
    import csv

    from fixture_model import MODEL

    model = MODEL.replace("<columnIds>QPROP:Element:name</columnIds>", "").replace(  # a table not computed
        "<diagramContents><binaryObject/></diagramContents>",
        "<diagramContents><binaryObject/><usedObjects href='#r1'/><usedObjects href='#b1'/></diagramContents>",
    ).replace(
        "<diagramContents><binaryObject streamContentID='BINARY-1'/></diagramContents>",
        "<diagramContents><binaryObject streamContentID='BINARY-1'/><usedObjects href='#odd'/></diagramContents>",
    )
    assert model.count("usedObjects") == 3
    proj = project_dir(run(tmp_path, "drone.mdzip", make_mdzip(model)))
    shown = {r["name"]: r["elements_shown"] for r in csv.DictReader((proj / "tables/diagrams.csv").open())}
    assert shown == {"Req Table": "2", "Drone BDD": "2"}  # the table's two; the two drawn
    page = (proj / "diagrams/Req_Table.md").read_text()
    assert "**Elements shown when last saved (2):**" in page and "Endurance" in page
    chunks = [json.loads(line) for line in (proj / "index/chunks.jsonl").open()]
    shown_in = {c["metadata"]["element_id"]: c["text"] for c in chunks if "Shown in diagrams" in c["text"]}
    assert "Shown in diagrams: Req Table" in shown_in["r1"]
    assert "Shown in diagrams: Drone BDD, Req Table" in shown_in["b1"]
    assert "odd" not in shown_in  # in the BDD's list, not drawn


def test_names_namespaces_cant_split(tmp_path, caplog):
    """A tag or attribute name with two colons, or a trailing one, is read as written, the model
    in full, and reported; other damage still fails the project (TR-001)."""
    import logging

    from fixture_model import MODEL

    from cameo_ingest.model import ModelIndex
    from cameo_ingest.xmi import ModelReadError, finalize, parse_into

    odd = MODEL.replace(" <sysml:Block xmi:id='st2' base_Class='b2'/>",
                        " <sysml:Block xmi:id='st2' base_Class='b2'/>\n <sysml:Block:Mark xmi:id='st9' base_Class='b2' Note='n'/>"
                        ).replace("name='Drone'>", "name='Drone' sysml:a:b='1' sysml:='2'>")
    ix = ModelIndex()
    parse_into(ix, io.BytesIO(odd.encode()), "model")
    finalize(ix)
    assert ix.elements["b1"].name == "Drone" and "r1" in ix.elements and "d1" in ix.diagrams
    assert ix.stereotypes["st9"].stereotype == "sysml:Block:Mark" and ix.stereotypes["st9"].base == "b2"
    assert [f.split(": ", 1)[1] for f in ix.recovered["model"]] == [
        "Failed to parse QName 'sysml:a:b'", "Failed to parse QName 'sysml:'", "Failed to parse QName 'sysml:Block:Mark'"]

    src = tmp_path / "odd.mdzip"
    src.write_bytes(make_mdzip(odd))
    out = tmp_path / "out"
    with caplog.at_level(logging.WARNING):
        assert cli([str(src), "-o", str(out), "--no-llm", "--no-render"]) == 0
    assert "cannot fingerprint" not in caplog.text and "read as written" in caplog.text
    check_invariants(out)
    assert "**Read with recovery:** 3 name(s)" in (project_dir(out) / "README.md").read_text()
    from contextlib import redirect_stdout
    status = io.StringIO()
    with redirect_stdout(status):
        assert cli(["status", "-o", str(out)]) == 0
    assert "read with recovery: odd.mdzip" in status.getvalue()

    try:
        parse_into(ModelIndex(), io.BytesIO(odd.encode()[:-200]), "model")
        raise AssertionError("a truncated model must fail")
    except ModelReadError as e:
        assert str(e).startswith("damaged XML in model, line")
    bad = tmp_path / "bad.mdzip"
    bad.write_bytes(make_mdzip(odd[:-200]))
    assert cli([str(bad), "-o", str(tmp_path / "bad"), "--no-llm", "--no-render"]) == 4
