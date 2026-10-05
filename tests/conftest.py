"""Fixtures for every test module (plan RA-18a)."""

import os

import pytest
from helpers import LLM_ENV, TREE_ENV, FakeChat


@pytest.fixture(autouse=True)
def isolated_env(request, monkeypatch):
    """Tests never see the developer's LLM settings or tree, and --env cannot leak between tests.
    The live tests (`-m llm`) keep the LLM settings: they are the endpoint to test."""
    drop = TREE_ENV + (LLM_ENV if request.node.get_closest_marker("llm") is None else ())
    monkeypatch.setattr(os, "environ", {k: v for k, v in os.environ.items() if k not in drop})


@pytest.fixture
def fake_chat(monkeypatch) -> list[FakeChat]:
    """The endpoint's client replaced by fakes, each one made kept in the list (AR-016R1)."""
    from cameo_ingest import llm

    made: list[FakeChat] = []
    monkeypatch.setattr(llm, "OpenAIChat", lambda cfg: made.append(FakeChat(cfg)) or made[-1])
    return made


@pytest.fixture(scope="session")
def fiction_tree(tmp_path_factory):
    """The six fictional projects, in their folders (three share one file name), ingested once
    per session without the LLM or sketches (plan RA-18c). Read it; don't write to it."""
    from cameo_ingest.cli import main
    from cameo_ingest.evaluation.fiction import PROJECTS

    root = tmp_path_factory.mktemp("fiction")
    for prefix in sorted(PROJECTS):
        project = PROJECTS[prefix]()
        src = root / "in" / project.path
        src.parent.mkdir(parents=True, exist_ok=True)
        src.write_bytes(project.mdzip())
    out = root / "out"
    assert main([str(root / "in"), "-o", str(out), "--no-llm", "--no-render"]) == 0
    return out
