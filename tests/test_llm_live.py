"""Tests against a real LLM endpoint (BASE-022). Opt-in: `uv run pytest -m llm`.

The endpoint comes from the environment, or from `.env` at the repository root, loaded the
same way as `--env` (variables already set win). The model is CAMEO_INGEST_TEXT_MODEL or
OPENAI_MODEL, so the same tests run against any endpoint. Without a configured endpoint
the tests are skipped. The API key is never printed.
"""

import json
import os
from pathlib import Path

import pytest
from fixture_model import make_mdzip
from test_pipeline import check_invariants

from cameo_ingest.cli import load_env, main

pytestmark = pytest.mark.llm
ROOT = Path(__file__).resolve().parent.parent
DRONE = ROOT / "samples" / "Package_Delivery_Drone.mdzip"


@pytest.fixture
def live(monkeypatch) -> str:
    """The model to test with; skips the test when no endpoint is configured."""
    monkeypatch.setattr(os, "environ", dict(os.environ))  # nothing loaded here outlives the test
    if (ROOT / ".env").is_file():
        load_env(ROOT / ".env")
    model = os.environ.get("CAMEO_INGEST_TEXT_MODEL") or os.environ.get("OPENAI_MODEL")
    if not model or not (os.environ.get("OPENAI_BASE_URL") or os.environ.get("OPENAI_API_KEY")):
        pytest.skip("no LLM endpoint configured: set OPENAI_BASE_URL / OPENAI_API_KEY and a model, or create .env")
    return model


def llm_report(out: Path) -> dict:
    return json.loads((out / "run.json").read_text())["llm"]


def test_live_enrichment(tmp_path, live):
    src = tmp_path / "drone.mdzip"
    src.write_bytes(make_mdzip())
    args = [str(src), "--text-model", live, "--cache-dir", str(tmp_path / "store"), "--llm-concurrency", "4"]
    out = tmp_path / "out"
    assert main([*args, "-o", str(out)]) == 0
    check_invariants(out)  # includes: LLM text only in labelled generated:* chunks
    # A diagram, two embedded images and one package summary, all answered.
    assert llm_report(out)["outcomes"] == {"answered": 4}
    kinds = {json.loads(line)["metadata"]["kind"] for line in (out / "chunks.jsonl").open()}
    assert {"generated:diagram_description", "generated:image_description", "generated:summary"} <= kinds
    # The same run again is answered from the store, without a single call.
    assert main([*args, "-o", str(tmp_path / "again")]) == 0
    report = llm_report(tmp_path / "again")
    assert report["calls"] == 0 and report["outcomes"] == {"cached": 4}


def test_live_bad_model(tmp_path, live, capsys):
    src = tmp_path / "drone.mdzip"
    src.write_bytes(make_mdzip())
    bad = "cameo-ingest/no-such-model"
    # The preflight check stops the run before parsing...
    assert main([str(src), "-o", str(tmp_path / "a"), "--text-model", bad]) == 5
    assert bad in capsys.readouterr().err
    # ...and without it, failures are logged, enrichment is switched off, and the ingest succeeds.
    out = tmp_path / "b"
    assert main([str(src), "-o", str(out), "--text-model", bad, "--no-preflight", "--llm-retries", "0"]) == 0
    report = llm_report(out)
    assert report["disabled_after_failures"] and report["outcomes"] == {"failed": 3, "skipped_disabled": 1}


@pytest.mark.skipif(not DRONE.exists(), reason="sample not fetched (scripts/fetch_samples.py --small)")
def test_live_sample(tmp_path, live):
    out = tmp_path / "out"
    # A call budget caps the cost of the run.
    assert main([str(DRONE), "-o", str(out), "--text-model", live, "--llm-max-calls", "8",
                 "--llm-concurrency", "4"]) == 0
    check_invariants(out)
    gen = [c for c in map(json.loads, (out / "chunks.jsonl").open()) if c["metadata"]["kind"].startswith("generated:")]
    assert len(gen) >= 6
    assert all(c["metadata"]["provenance"]["derivation"]["model"] == live for c in gen)
