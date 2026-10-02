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

from cameo_ingest.cli import main

JS = Path(__file__).parent / "js"
NODE = shutil.which("node")
needs_node = pytest.mark.skipif(NODE is None, reason="Node is not installed")


def blocks(page: Path) -> list[dict]:
    html = page.read_text(encoding="utf-8")
    raw = re.findall(r'<script type="application/octet-stream"[^>]*>([^<]*)</script>', html)
    return [json.loads(gzip.decompress(base64.b64decode(b))) for b in raw]


def node(*args: str) -> str:
    return subprocess.run([NODE, *args], check=True, capture_output=True, text=True, timeout=120).stdout


@pytest.fixture(scope="module")
def page(fiction_tree, tmp_path_factory) -> Path:
    path = tmp_path_factory.mktemp("page") / "search.html"
    assert main(["export", "-o", str(fiction_tree), "--search-page", str(path)]) == 0
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
    assert main(["export", "-o", str(fiction_tree), "--search-page", str(again)]) == 0
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
