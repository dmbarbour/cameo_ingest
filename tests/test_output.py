"""What an output tree holds: pages, chunks, provenance, rag/, the ledger, reproducibility."""

import csv
import hashlib
import json
import re

from fixture_model import MODEL, make_mdzip
from helpers import (
    check_invariants,
    project_dir,
    provenance,
    run,
    tree,
)

from cameo_ingest.cli import main


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
        if c["metadata"]["kind"] not in ("ledger:projects", "index:id"):  # the tree's own chunks span projects
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


def test_rag_files(tmp_path):
    """rag/text holds every chunk as a .txt file (plain chunks) named by the sha256 of its text,
    ending with its source; rag/meta holds each file's metadata at the same path, with the input
    files, and _sources.json resolves each project's short id to them. --rag-source is set for
    the whole tree; unchanged projects are not written again; --no-rag-files removes the folder."""
    src = tmp_path / "drone.mdzip"
    src.write_bytes(make_mdzip())
    out = tmp_path / "out"
    assert main([str(src), "-o", str(out), "--no-llm", "--no-render", "--meta", "program=X"]) == 0
    chunks = [json.loads(line) for line in (out / "chunks.jsonl").open()]
    rag = out / "rag"
    assert sorted(p.name for p in rag.iterdir()) == ["meta", "text"]
    [folder] = [d.name for d in (rag / "text").iterdir() if d.name != "_tree"]
    assert folder.startswith("drone-")
    files = sorted((rag / "text" / folder).glob("*.txt"))
    tree_kinds = ("ledger:projects", "index:id", "trace:thread")  # assembled over the tree, in _tree
    assert len(files) == len([c for c in chunks if c["metadata"]["kind"] not in tree_kinds])
    assert len(list((rag / "text" / "_tree").glob("*.txt"))) == len([c for c in chunks
                                                                      if c["metadata"]["kind"] in tree_kinds])
    for f in files:
        assert f.stem == hashlib.sha256(f.read_bytes()).hexdigest()
        meta = json.loads((rag / "meta" / folder / f"{f.stem}.json").read_text())
        assert meta["file"] == f.name and meta["trace"] in f.read_text()
    drone = next(f for f in files if f.read_text().startswith("Block Drone in "))
    meta = json.loads((rag / "meta" / folder / f"{drone.stem}.json").read_text())
    assert meta["kind"] == "element" and meta["title"].startswith("Block Drone in ")
    assert f"(project drone [{meta['source_id']}])" in meta["title"]  # a label, not the file name
    assert meta["page"].startswith("by-sha256/") and meta["found_with"] == {"program": ["X"]}
    assert f"\n\nSource: {meta['trace']}\n" in drone.read_text()
    assert drone.read_text().endswith("Found with: program=X\n")
    # Input files: in the metadata, and in _sources.json under the project's short id; never in the text.
    assert meta["source_file"] == str(src.resolve()) and meta["source_files"] == [str(src.resolve())]
    sources = json.loads((rag / "meta" / "_sources.json").read_text())
    assert sources[meta["source_id"]]["files"] == [str(src.resolve())] and folder.endswith(meta["source_id"])
    assert str(tmp_path) not in drone.read_text()
    stamp = drone.stat().st_mtime_ns
    assert main(["run", "-o", str(out)]) == 0
    assert drone.stat().st_mtime_ns == stamp  # not written again
    # --rag-source is set for the whole tree: a run rewrites every file in the new form.
    assert main(["run", "-o", str(out), "--rag-source", "id"]) == 0
    texts = [f.read_text() for f in (rag / "text" / folder).glob("*.txt")]
    assert any(f"Source: [{meta['source_id']}:{meta['chunk_id'][:12]}]" in t for t in texts)
    assert not any("Source: sha256:" in t or "drone.mdzip" in t for t in texts)
    assert main(["run", "-o", str(out), "--no-rag-files"]) == 0
    assert not rag.exists()


def test_tree_switches(tmp_path):
    """Each tree-level switch works alone and with the others, run after run (AR-001)."""
    src = tmp_path / "drone.mdzip"
    src.write_bytes(make_mdzip())
    out = tmp_path / "out"
    assert main([str(src), "-o", str(out), "--no-llm", "--no-render"]) == 0
    for index in (True, False):
        for threads in (True, False):
            for rag in (True, False):
                flags = ["--cross-index" if index else "--no-cross-index", "--threads" if threads else "--no-threads",
                         "--rag-files" if rag else "--no-rag-files"]
                assert main(["run", "-o", str(out), *flags]) == 0, flags
                kinds = {json.loads(line)["metadata"]["kind"] for line in (out / "chunks.jsonl").open()}
                assert (out / "CROSSREF.md").exists() == index, flags
                assert ("index:id" in kinds) == index and (out / "rag").exists() == rag, flags
                assert threads or "trace:thread" not in kinds, flags


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
    assert "Model::Requirements" in req["text"] and "Cameo project drone [" in req["text"]  # its label
    assert "](" not in req["text"]
    assert req["metadata"]["element_ids"] == ["r1"]
    assert req["metadata"]["provenance"]["xmi_id"] == "p2"


def test_ledger_natural_sort_and_split():
    from cameo_ingest.ledger import _natural_key

    ids = ["REQ.1.10", "REQ.1.2", "REQ.1", "REQ.2"]
    assert sorted(ids, key=_natural_key) == ["REQ.1", "REQ.1.2", "REQ.1.10", "REQ.2"]


def test_treediff(tmp_path, capsys):
    """Two runs of one model make the same tree; a changed chunk shows by id, text and kind (plan RA-01)."""
    from cameo_ingest.treediff import compare
    from cameo_ingest.treediff import main as treediff

    src = tmp_path / "drone.mdzip"  # one input: rag/meta names its path
    src.write_bytes(make_mdzip())
    a, b = tmp_path / "a", tmp_path / "b"
    for out in (a, b):
        assert main([str(src), "-o", str(out), "--no-llm"]) == 0
    assert not compare(a, b) and treediff([str(a), str(b)]) == 0
    # Another tool version: masked in the files, and in the manifest's hashes of them.
    for f in [b / "chunks.jsonl", b / "manifest.json"]:
        f.write_text(re.sub(r"cameo-ingest/[0-9.]+", "cameo-ingest/9.9.9", f.read_text()))
    manifest = json.loads((b / "manifest.json").read_text())
    manifest["projects"][0]["files"][0]["sha256"] = "0" * 64
    (b / "manifest.json").write_text(json.dumps(manifest))
    assert not compare(a, b)
    last = json.loads((a / "chunks.jsonl").read_text().splitlines()[-1])["id"]
    chunks = b / "chunks.jsonl"
    lines = chunks.read_text().splitlines()
    first = json.loads(lines[0])
    lines[0] = json.dumps({**first, "text": first["text"] + "\nA new line."})
    lines[1] = json.dumps({**json.loads(lines[1]), "title": "Renamed"})
    chunks.write_text("\n".join(lines[:-1]) + "\n")
    (b / "extra.md").write_text("# New page\n")
    r = compare(a, b)
    assert r.changed == {"chunks": ["chunks.jsonl"]} and r.added == {"pages": ["extra.md"]} and not r.removed
    ch = r.chunks["chunks.jsonl"]
    assert [c[0] for c in ch.text] == [first["id"]] and ch.metadata == [json.loads(lines[1])["id"]]
    assert ch.removed == [last] and not ch.added
    assert treediff([str(a), str(b)]) == 1 and "+A new line." in capsys.readouterr().out
