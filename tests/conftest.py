"""Fixtures for every test module (plan RA-18a)."""

import os

import pytest
from helpers import LLM_ENV, TREE_ENV, FakeChat


@pytest.fixture(autouse=True)
def isolated_env(request, monkeypatch, tmp_path):
    """Tests never see the developer's LLM settings, tree or LLM store, and --env cannot leak
    between tests: each test has a store of its own (`helpers.store_db`). The live tests
    (`-m llm`) keep the LLM settings: they are the endpoint to test."""
    drop = TREE_ENV + (LLM_ENV if request.node.get_closest_marker("llm") is None else ())
    env = {k: v for k, v in os.environ.items() if k not in drop}
    env["CAMEO_INGEST_CACHE"] = str(tmp_path / "llm-store")
    monkeypatch.setattr(os, "environ", env)


@pytest.fixture
def fake_chat(monkeypatch) -> list[FakeChat]:
    """The endpoint's client replaced by fakes, each one made kept in the list (AR-016R1)."""
    from cameo_ingest import llm

    made: list[FakeChat] = []
    monkeypatch.setattr(llm, "OpenAIChat", lambda cfg: made.append(FakeChat(cfg)) or made[-1])
    return made


@pytest.fixture(scope="session")
def lineage_tree(tmp_path_factory):
    """The lineage cases (`evaluation.fiction.lineage.corpus`: versions, a copy, a tender with two
    bids, two models sharing a library) under `in/`, ingested once per session without the LLM or
    sketches (CQ-022). Read it; don't write to it."""
    from helpers import ingest

    from cameo_ingest.evaluation.fiction.lineage import corpus

    return ingest(tmp_path_factory.mktemp("lineage"), *((f"in/{c.path}", c.mdzip) for c in corpus()),
                  args=("--no-llm", "--no-render"), out="tree")


@pytest.fixture(scope="session")
def fiction_tree(tmp_path_factory):
    """The seven fictional projects, in their folders (three share one file name), ingested once
    per session without the LLM or sketches (plan RA-18c). Read it; don't write to it."""
    from helpers import cli, write_inputs

    from cameo_ingest.evaluation.fiction import PROJECTS

    root = tmp_path_factory.mktemp("fiction")
    inputs = write_inputs(root / "in", *((p.path, p.mdzip()) for p in (PROJECTS[k]() for k in sorted(PROJECTS))))
    out = root / "out"
    assert cli([str(inputs), "-o", str(out), "--no-llm", "--no-render"]) == 0
    return out
