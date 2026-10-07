"""The search page: one self-contained file that searches the catalog in a browser (plan KX-04).
Its engine is JavaScript, tested with Node where Node is installed."""

import base64
import gzip
import json
import re
import shutil
import subprocess
from pathlib import Path

import pytest
from helpers import cli

JS = Path(__file__).parent / "js"
NODE = shutil.which("node")
needs_node = pytest.mark.skipif(NODE is None, reason="Node is not installed")


def blocks(page: Path) -> list[dict]:
    html = page.read_text(encoding="utf-8")
    raw = re.findall(r'<script type="application/octet-stream" data-project=[^>]*>([^<]*)</script>', html)
    return [json.loads(gzip.decompress(base64.b64decode(b))) for b in raw]


def node(*args: str) -> str:
    return subprocess.run([NODE, *args], check=True, capture_output=True, text=True, timeout=120).stdout


@pytest.fixture(scope="module")
def page(fiction_tree, tmp_path_factory) -> Path:
    path = tmp_path_factory.mktemp("page") / "search.html"
    assert cli(["export", "-o", str(fiction_tree), "--search-page", str(path)]) == 0
    return path


def test_page_holds_the_catalog(page, fiction_tree, tmp_path):
    """One block per model, with the items, their full text and relations, and nothing left
    in the template unfilled; the same bytes each time."""
    html = page.read_text(encoding="utf-8")
    assert "{{" not in html and "<title>Model search</title>" in html
    data = blocks(page)
    assert len(data) == 7 and all(d["project"]["sources"] for d in data)
    kois = next(d for d in data if d["project"]["name"] == "Kestrel_Orchard_Irrigation.mdzip")
    r2 = next(i for i in kois["items"] if i["k"] == "_kois_r2")
    assert r2["id"] == "KOIS-R2" and "Requirement text: Brine Valve K7" in r2["c"]
    assert ["Satisfy", "in", "satisfied by", "_kois_k7", "Brine Valve K7"] in r2["r"]
    part = next(i for i in kois["items"] if i["k"] == "_kois_kois__p_brine_valve_k7")
    assert part["l"][0] == "_kois_kois" and "c" not in part  # a member borrows its owner's text, not a copy
    assert not any(i["t"] == "relationship" for d in data for i in d["items"])
    again = tmp_path / "again.html"
    assert cli(["export", "-o", str(fiction_tree), "--search-page", str(again)]) == 0
    assert again.read_bytes() == page.read_bytes()


@needs_node
def test_engine():
    assert node(str(JS / "engine.js")).strip() == "ok"


@needs_node
def test_engine_ranks_as_the_evaluation(tmp_path):
    """The page's BM25 gives the scores of the retrieval evaluation's (harness.BM25)."""
    np = pytest.importorskip("numpy")
    from cameo_ingest.evaluation.harness import BM25

    texts = ["The focal length shall be 450 m.", "REQ-1-OAD-1050 Focal length and plate scale",
             "Brine Valve K7 closes within 340 milliseconds of a leak signal.", "Pump Station: pumps Otter and Heron.",
             "A valve, a valve, a valve.", ""]
    queries = ["focal length", "REQ-1-OAD-1050", "valve leak", "otter"]
    case = tmp_path / "case.json"
    case.write_text(json.dumps({"texts": texts, "queries": queries}))
    got = json.loads(node(str(JS / "bm25.js"), str(case)))
    bm = BM25(texts)
    for q, scores in zip(queries, got, strict=True):
        assert np.allclose(scores, bm.scores(q), rtol=1e-5, atol=1e-6), q


@needs_node
def test_page_searches_in_node(page):
    """The page's own blocks unpack (DecompressionStream) and index, and find an id."""
    out = json.loads(node(str(JS / "page.js"), str(page), "RWT-REG-001"))
    assert out["projects"] == 7 and out["items"] > 500
    assert any("RWT-REG-001" in n for n in out["names"])


CHROME = next((p for p in map(shutil.which, ("google-chrome", "google-chrome-stable", "chromium", "chromium-browser",
                                              "msedge")) if p), None)


@needs_node
@pytest.mark.skipif(CHROME is None, reason="no Chrome, Chromium or Edge")
def test_page_in_a_browser(tmp_path):
    """In headless Chrome: the page loads and searches; a diagram's SVG sketch shows its shapes
    with their full names as tooltips; a click on a shape opens its element, Back returns, and a
    click on the sketch zooms it; no script errors."""
    from helpers import ingest

    from cameo_ingest.evaluation.fiction import PROJECTS

    kois = PROJECTS["kois"]()
    out = ingest(tmp_path, (kois.file_name, kois.mdzip()))  # sketches drawn
    page = tmp_path / "search.html"
    assert cli(["export", "-o", str(out), "--search-page", str(page), "--sketches", "svg"]) == 0
    doc = [i["k"] for i in blocks(page)[0]["items"]].index("_kois_d_req")
    seen = json.loads(node(str(JS / "browser.js"), CHROME, str(tmp_path / "profile"), str(page), str(doc), "_kois_k7",
                           "valve closing"))
    assert seen["ready"].startswith("42 items from 1 model"), seen
    assert "found" in seen["search"] and seen["first"] == "Valve Closing Time (KOIS-R2)"
    assert seen["linked"] >= 13  # the diagram's 7 requirements and 6 blocks, each linked
    assert seen["tooltip"].endswith("Brine Valve K7")
    assert seen["heading"] == "Brine Valve K7" and seen["hash"].startswith("#d")
    assert seen["zoomed"] is True and seen["errors"] == []
    assert seen["models"] == 1 and seen["views"] >= 1 and seen["subjects"] >= 1 and seen["opened"] >= 1  # browsing
    assert seen["tags"] >= 13 and "Full text" in seen["fullText"]  # "[n]" links (TR-005); no RAG wording (TR-006)
    assert not any("RAG" in h for h in seen["fullText"])
    assert seen["chooserClosed"] is True  # until asked for
    assert seen["chooser"] == 1 and seen["button"].startswith("Models: all 1")  # the model chooser (plan LN-07)


@needs_node
def test_subjects_in_the_page(page):
    """The families' subjects travel with the page; results group by subject, best first, every
    result in one group (plan SB-07c)."""
    assert node(str(JS / "subjects.js")).strip() == "ok"
    html = page.read_text(encoding="utf-8")
    assert 'data-subjects="1"' in html and 'id="grouped"' in html
    out = json.loads(node(str(JS / "subjects.js"), str(page), "signal"))
    assert out["families"] >= 1 and out["hits"] == out["grouped"] and out["groups"] > 1 and out["ordered"]


@needs_node
def test_model_chooser():
    """Models grouped by lineage (versions under the newest, kin together), by folder, by name or
    by date, each with a note on its lineage (plan LN-07)."""
    assert node(str(JS / "chooser.js")).strip() == "ok"
