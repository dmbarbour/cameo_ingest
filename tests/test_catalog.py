"""The catalog, and the workbook made from it for people to search without tools (plan KX)."""

import hashlib
import json

import xlsx
from fixture_model import make_mdzip
from helpers import ingest, project_dir

from cameo_ingest.catalog import ProjectCatalog
from cameo_ingest.cli import main
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
    out = ingest(tmp_path, ("drone.mdzip", make_mdzip()), args=("--vision-model", "m", "--text-model", "m", "--no-preflight"))
    recs = [json.loads(line) for line in (project_dir(out) / "index" / "catalog.jsonl").open()]
    summaries = [r for r in recs if r["type"] == "summary"]
    assert summaries and all(r["model"] == "m" and r["text"] and r["of"][0] == r["key"] for r in summaries)
    assert {r["label"] for r in summaries} >= {"Diagram description", "Summary"}


def test_workbook_from_the_tree(fiction_tree, tmp_path, capsys):
    """`export --workbook` writes every sheet from the tree's catalogs, with each item's source,
    and the same bytes each time (KX-03, KX-06)."""
    book = tmp_path / "catalog.xlsx"
    assert main(["export", "-o", str(fiction_tree), "--workbook", str(book)]) == 0
    assert f"wrote {book}" in capsys.readouterr().out
    sheets = xlsx.sheets(book)
    assert list(sheets) == ["About", "Find", "Search", "Requirements", "Identifiers", "Elements", "Relationships",
                            "Diagrams", "Summaries", "Projects"]
    req = sheets["Requirements"]
    row = dict(zip(req[0], next(r for r in req if r[0] == "KOIS-R2"), strict=False))
    assert row["Satisfied by"] == "Brine Valve K7" and row["Derived from"] == "Leak Shutdown (KOIS-R5)"
    assert row["Source"].endswith("Kestrel_Orchard_Irrigation.mdzip")
    rwt = hashlib.sha256(PROJECTS["rwt"]().mdzip()).hexdigest()[:8]  # three proposals share the id
    doors = dict(zip(req[0], next(r for r in req if r[0] == "RWT-REG-001" and rwt in r[4]), strict=False))
    assert doors["Database number"] == "16001"
    assert len(sheets["Projects"]) == 1 + len(PROJECTS)
    ids = [r for r in sheets["Identifiers"][1:] if r[0] == "RWT-REG-003"]
    assert len({r[1] for r in ids}) == 3  # the id in all three Riverbend proposals
    find = sheets["Find"][6][0]
    assert isinstance(find, xlsx.Formula) and "FILTER(Search!$A$2:$H$" in find
    again = tmp_path / "again.xlsx"
    assert main(["export", "-o", str(fiction_tree), "--workbook", str(again)]) == 0
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
    assert main(["export", "-o", str(out), "--workbook", str(tmp_path / "c.xlsx")]) == 0
    assert "drone.mdzip; `run` makes them again" in capsys.readouterr().err
