import csv
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
from fixture_model import MODEL, make_mdzip

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
        dup = [a for a, n in Counter(re.findall(r'<a id="([^"]+)"></a>', text)).items() if n > 1]
        assert not dup, (md, dup[:3])
        assert "<unnamed>" not in text and "{#" not in text, md  # placeholders and anchors (BASE-009)
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
    manifest = json.loads((out / "manifest.json").read_text())
    assert manifest["source"]["metadata"] == {"program": "test"}
    chunks = [json.loads(line) for line in (out / "chunks.jsonl").open()]
    assert chunks
    for c in chunks:
        p = c["metadata"]["provenance"]
        assert p["source_sha256"] == manifest["source"]["sha256"]
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


def test_reproducible_output(tmp_path):
    """Same input and options give byte-identical output, apart from the run record, even
    from another directory (BASE-015)."""
    data = make_mdzip()
    trees = []
    for i, d in enumerate(["a", "a", "b"]):
        src = tmp_path / d / "drone.mdzip"
        src.parent.mkdir(exist_ok=True)
        src.write_bytes(data)
        out = tmp_path / f"out{i}"
        assert main([str(src), "-o", str(out), "--meta", "program=test", "--no-llm"]) == 0
        trees.append({str(f.relative_to(out)): f.read_bytes() for f in out.rglob("*") if f.is_file()})
    run_records = [json.loads(t.pop("run.json")) for t in trees]
    assert trees[0] == trees[1] == trees[2]
    assert run_records[0]["run_id"] != run_records[1]["run_id"]
    assert run_records[2]["source_path"].endswith("b/drone.mdzip")
    assert "drone.mdzip/diagrams/Drone_BDD.png" in trees[0]  # rendering is covered too


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


class FakeOpenAI:
    """Stands in for openai.OpenAI: records requests and returns a fixed reply."""

    fail = False  # set on the class to make every request raise
    delay = 0.0  # seconds per request
    inflight = max_inflight = 0
    _lock = threading.Lock()

    def __init__(self, **kwargs):
        self.kwargs = kwargs
        self.requests: list[tuple[str, list]] = []
        self.chat = SimpleNamespace(completions=SimpleNamespace(create=self._create))

    def _create(self, model, messages, **kw):
        self.requests.append((model, messages))
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
    dia = (out / "drone.mdzip/diagrams/Drone_BDD.md").read_text()
    assert "generated by gemma-4; not part of the source model" in dia
    chunks = [json.loads(line) for line in (out / "chunks.jsonl").open()]
    manifest = json.loads((out / "manifest.json").read_text())
    assert manifest["options"]["llm"]["vision_model"] == "gemma-4"
    assert "api_key" not in json.dumps(manifest).lower()
    gen = [c for c in chunks if c["metadata"]["kind"].startswith("generated:")]
    assert gen and all(c["metadata"]["provenance"]["derivation"]["method"] == "llm" for c in gen)
    assert sum(c["metadata"]["kind"] == "generated:image_description" for c in chunks) == 2
    extracted = [c for c in chunks if not c["metadata"]["kind"].startswith("generated:")]
    assert not any("gemma-4" in c["text"] for c in extracted)


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
        trees.append({str(f.relative_to(out)): f.read_bytes() for f in out.rglob("*") if f.is_file()})
    report = json.loads(trees[1].pop("run.json"))["llm"]
    assert report["calls"] == 0 and report["outcomes"] == {"cached": 3}
    # Replay never touches the network; it reproduces the recorded run exactly (BASE-022R5).
    monkeypatch.setattr(FakeOpenAI, "fail", True)
    out = tmp_path / "replayed"
    assert main([str(src), "--vision-model", "m", "--llm-replay", str(store / "llm.sqlite"),
                 "--meta", "program=test", "-o", str(out)]) == 0
    replayed = {str(f.relative_to(out)): f.read_bytes() for f in out.rglob("*") if f.is_file()}
    assert json.loads(replayed.pop("run.json"))["llm"]["outcomes"] == {"replayed": 3}
    assert replayed == trees[1]
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
        trees.append({str(f.relative_to(out)): f.read_bytes() for f in out.rglob("*") if f.is_file()
                      and f.name != "run.json"})
    assert FakeOpenAI.max_inflight >= 2  # requests overlapped (BASE-019R4)...
    assert trees[0] == trees[1]  # ...and the output is the same as a sequential run


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
