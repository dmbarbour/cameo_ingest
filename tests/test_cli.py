"""The command line and output trees: rules, settings, progress, interrupts, status."""

import io
import json
import logging
import os
import re
import zipfile

import pytest
from fixture_model import MODEL, make_mdzip
from helpers import (
    FakeChat,
    check_invariants,
    cli,
    project_dir,
    provenance,
    run,
    tree,
)


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
    assert cli([str(src), "-o", str(out), "--no-llm", "--no-render"]) == 4
    manifest = json.loads((out / "manifest.json").read_text())
    assert [p["name"] for p in manifest["projects"]] == ["good.mdzip"]
    assert [f["name"] for f in manifest["failed"]] == ["bad.mdzip"]
    assert "XMLSyntaxError" in manifest["failed"][0]["error"]
    assert "skipping nested member bundle.rdzip!corrupt.mdzip" in caplog.text
    check_invariants(out)


def test_adding_a_directory_reports_its_walk(tmp_path, caplog):
    """Adding a directory walks it with progress lines and a debug line per candidate; Office
    files (ZIP archives too), other known non-model types and hidden directories are skipped
    without being read."""
    import zipfile

    tree = tmp_path / "share"
    (tree / "deep/er").mkdir(parents=True)
    (tree / ".git").mkdir()
    (tree / "deep/er/drone.mdzip").write_bytes(make_mdzip())
    (tree / ".git/drone.mdzip").write_bytes(make_mdzip())
    with zipfile.ZipFile(tree / "report.docx", "w") as z:
        z.writestr("word/document.xml", "<w:document/>")
    (tree / "notes.txt").write_text("not a model")
    out = tmp_path / "out"
    with caplog.at_level(logging.DEBUG, logger="cameo_ingest"):
        assert cli(["add", "-o", str(out), str(tree), "-vv"]) == 0
    assert "looking for models under" in caplog.text
    assert "candidate: " in caplog.text and "drone.mdzip (ZIP)" in caplog.text
    assert "found 1 candidate(s)" in caplog.text and "2 file(s) skipped by type" in caplog.text
    assert "report.docx" not in caplog.text


def test_which_tree(tmp_path, monkeypatch, caplog):
    """Without -o, the tree is $CAMEO_INGEST_TREE, else ./ingest_tree (plan CF-01);
    $CAMEO_INGEST_DEST is retired, with a notice."""
    src = tmp_path / "drone.mdzip"
    src.write_bytes(make_mdzip())
    monkeypatch.chdir(tmp_path)
    assert cli([str(src), "--no-llm", "--no-render"]) == 0
    assert (tmp_path / "ingest_tree" / "manifest.json").is_file()
    assert cli(["status"]) == 0
    monkeypatch.setenv("CAMEO_INGEST_TREE", str(tmp_path / "chosen"))
    assert cli([str(src), "--no-llm", "--no-render"]) == 0
    assert (tmp_path / "chosen" / "manifest.json").is_file()
    assert cli([str(src), "-o", str(tmp_path / "given"), "--no-llm", "--no-render"]) == 0  # -o wins
    assert (tmp_path / "given" / "manifest.json").is_file()
    monkeypatch.delenv("CAMEO_INGEST_TREE")
    monkeypatch.setenv("CAMEO_INGEST_DEST", str(tmp_path / "old"))
    assert cli(["status"]) == 0 and not (tmp_path / "old").exists()
    assert "CAMEO_INGEST_DEST is retired" in caplog.text


def test_tree_rules_and_missing_inputs(tmp_path, capsys):
    foreign = tmp_path / "foreign"
    foreign.mkdir()
    (foreign / "notes.txt").write_text("mine")
    src = tmp_path / "drone.mdzip"
    src.write_bytes(make_mdzip())
    assert cli([str(src), "-o", str(foreign), "--no-llm"]) == 2  # never write into an unrelated directory
    assert cli(["run", "-o", str(tmp_path / "nothing")]) == 2
    assert "not a cameo-ingest output tree" in capsys.readouterr().err
    out = tmp_path / "out"
    assert cli([str(src), "-o", str(out), "--no-llm", "--no-render"]) == 0
    src.unlink()  # the input disappears: its project stays (plan decision 3)
    assert cli(["run", "-o", str(out)]) == 0
    [record] = provenance(out).values()
    assert record["status"] == "written" and record["sightings"][0]["missing"]
    assert "(input missing)" in (out / "INDEX.md").read_text()


def test_options_change_rewrites_projects(tmp_path, monkeypatch, fake_chat):
    """Output made with other options or another tool version is written again, and files
    the new version doesn't produce disappear with the old directory (plan RI-06)."""
    src = tmp_path / "drone.mdzip"
    src.write_bytes(make_mdzip())
    out = tmp_path / "out"
    assert cli([str(src), "-o", str(out), "--no-llm"]) == 0
    proj = project_dir(out)
    assert (proj / "diagrams/Drone_BDD.png").exists()
    assert cli(["run", "-o", str(out)]) == 0
    assert json.loads((out / "run.json").read_text())["projects"]["written"] == 0  # up to date
    assert cli(["run", "-o", str(out), "--no-render"]) == 0
    assert json.loads((out / "run.json").read_text())["projects"]["written"] == 1
    assert not (proj / "diagrams/Drone_BDD.png").exists() and (proj / "README.md").exists()
    import dataclasses

    from cameo_ingest import prompts, runner

    # A new prompt template version counts as an option change (FU-014).
    in_use = prompts.CURRENT["package-summary"]
    later = dataclasses.replace(in_use, version=in_use.version + 100)
    monkeypatch.setitem(prompts.CURRENT, "package-summary", later)
    assert cli(["run", "-o", str(out), "--text-model", "m", "--no-calibrate"]) == 0
    assert json.loads((out / "run.json").read_text())["projects"]["written"] == 1
    monkeypatch.setitem(prompts.CURRENT, "package-summary", in_use)
    assert cli(["run", "-o", str(out)]) == 0
    assert json.loads((out / "run.json").read_text())["projects"]["written"] == 1
    assert cli(["run", "-o", str(out)]) == 0
    assert json.loads((out / "run.json").read_text())["projects"]["written"] == 0
    monkeypatch.setattr(runner, "TOOL", "cameo-ingest/99")
    assert cli(["run", "-o", str(out)]) == 0
    assert json.loads((out / "run.json").read_text())["projects"]["written"] == 1


def test_no_model_fails_fast(tmp_path, capsys):
    """A tree that uses the LLM but names no model stops at once, and says which `config`
    commands set one (BASE-020, plan CF)."""
    src = tmp_path / "drone.mdzip"
    src.write_bytes(make_mdzip())
    out = tmp_path / "out"
    assert cli([str(src), "-o", str(out)]) == 2
    err = capsys.readouterr().err
    assert "config set text-model NAME" in err and "config set llm off" in err and "OPENAI_BASE_URL" in err
    assert not out.exists()


def test_preflight(tmp_path, capsys, caplog):
    """The endpoint and key come from OPENAI_BASE_URL and OPENAI_API_KEY only; an endpoint that
    doesn't answer stops the run before any parsing (BASE-020), and the key is never shown."""
    os.environ["OPENAI_BASE_URL"] = "http://127.0.0.1:9/v1"  # nothing listens on port 9
    os.environ["OPENAI_API_KEY"] = "sk-secret-123"
    src = tmp_path / "drone.mdzip"
    src.write_bytes(make_mdzip())
    out = tmp_path / "out"
    assert cli(["config", "-o", str(out), "set", "text-model", "shell-model"]) == 0
    assert cli([str(src), "-o", str(out), "-v"]) == 5
    err = capsys.readouterr().err
    assert "shell-model" in err and "127.0.0.1:9" in err and "config test" in err
    assert "sk-secret-123" not in err + caplog.text
    assert not (out / "manifest.json").exists()
    assert logging.getLogger("httpx").getEffectiveLevel() == logging.WARNING  # quiet below -vv (BASE-018)


def test_progress_heartbeats_and_log_file(tmp_path, fake_chat, monkeypatch, capsys):
    monkeypatch.setattr(FakeChat, "delay", 0.1)
    src = tmp_path / "drone.mdzip"
    src.write_bytes(make_mdzip())
    log_file = tmp_path / "run.log"
    # Not a terminal, default verbosity: heartbeat lines still reach the console (BASE-018).
    assert cli([str(src), "-o", str(tmp_path / "out"), "--vision-model", "m", "--heartbeat", "0.05",
                 "--log-file", str(log_file)]) == 0
    err = capsys.readouterr().err
    assert re.search(r"drone\.mdzip: LLM: \d requests? of 3 requests \(\d+%\)", err)
    assert "drone.mdzip: LLM: 3 requests in" in err and "found 1 project" not in err  # -v lines stay hidden
    logged = log_file.read_text()
    assert "DEBUG" in logged and "LLM m answered for sha256:" in logged and "found 1 project" in logged


def test_interrupt_and_resume(tmp_path, fake_chat, monkeypatch, capsys):
    """A run stopped part-way continues where it stopped, and ends with the same output as a
    run that was never interrupted (plan RI-07)."""
    src = tmp_path / "drone.mdzip"
    src.write_bytes(make_mdzip())
    ref = tmp_path / "ref"
    assert cli([str(src), "-o", str(ref), "--vision-model", "m", "--no-calibrate", "--no-preflight"]) == 0
    monkeypatch.setattr(FakeChat, "interrupt_at", 2)  # Ctrl-C during the second LLM request
    os.environ["CAMEO_INGEST_CACHE"] = str(tmp_path / "store-out")  # not the reference's answers
    out = tmp_path / "out"
    assert cli([str(src), "-o", str(out), "--vision-model", "m", "--no-calibrate", "--no-preflight"]) == 130
    assert "Continue with: cameo-ingest run -o" in capsys.readouterr().err
    assert json.loads((out / "run.json").read_text())["outcome"] == "interrupted"
    assert json.loads((out / "manifest.json").read_text())["projects"] == []  # nothing half-published
    [work] = (out / "by-sha256/.work").iterdir()
    sketch = (work / "diagrams/Drone_BDD.png").stat().st_mtime_ns  # drawn before the interruption
    monkeypatch.setattr(FakeChat, "interrupt_at", None)
    assert cli(["run", "-o", str(out), "--no-preflight", "--no-calibrate"]) == 0  # the tree remembers the model
    assert json.loads((out / "run.json").read_text())["llm"]["outcomes"] == {"answered": 2, "cached": 1}
    assert (project_dir(out) / "diagrams/Drone_BDD.png").stat().st_mtime_ns == sketch  # reused, not redrawn
    assert tree(out) == tree(ref)


def test_status_and_prune(tmp_path, capsys):
    a, b = tmp_path / "a.mdzip", tmp_path / "b.mdzip"
    a.write_bytes(make_mdzip())
    b.write_bytes(make_mdzip(MODEL.replace("name='Requirements'", "name='Needs'")))
    out = tmp_path / "out"
    assert cli([str(a), str(b), "-o", str(out), "--no-llm", "--no-render"]) == 0
    b.unlink()
    assert cli(["run", "-o", str(out)]) == 0
    capsys.readouterr()
    assert cli(["status", "-o", str(out), "--json"]) == 0
    s = json.loads(capsys.readouterr().out)
    assert s["inputs"]["counts"] == {"done": 1, "missing": 1} and s["projects"]["counts"] == {"written": 2}
    assert s["inputs"]["problems"] == [{"path": str(b), "status": "missing", "error": None}]
    assert s["latest_run"]["outcome"] == "finished"
    assert cli(["prune", "-o", str(out), "--dry-run"]) == 0
    assert "would remove 1 missing input(s) and 1 project(s)" in capsys.readouterr().out
    assert len(list((out / "by-sha256").glob("[0-9a-f]*"))) == 2
    assert cli(["prune", "-o", str(out)]) == 0
    assert [p["name"] for p in json.loads((out / "manifest.json").read_text())["projects"]] == ["a.mdzip"]
    assert len(list((out / "by-sha256").glob("[0-9a-f]*"))) == 1
    capsys.readouterr()
    assert cli(["status", "-o", str(out)]) == 0
    assert "inputs: 1 done\nprojects: 1 written\n" in capsys.readouterr().out


def test_markdown_chunk_style_retired(tmp_path, caplog):
    """A tree that stored the retired Markdown chunk style runs on with plain chunks (plan RA-02)."""
    from cameo_ingest.state import State

    out = run(tmp_path, "drone.mdzip", make_mdzip())
    st = State(out)
    st.save_settings({**st.settings(), "chunk_style": "markdown"})
    st.close()
    assert cli(["run", "-o", str(out)]) == 0
    assert "Markdown chunk style is retired" in caplog.text
    st = State(out)
    assert "chunk_style" not in st.settings()
    st.close()
    assert not list((out / "rag" / "text").rglob("*.md")) and list((out / "rag" / "text").rglob("*.txt"))
    with pytest.raises(SystemExit):
        cli([str(tmp_path / "drone.mdzip"), "-o", str(tmp_path / "again"), "--chunk-style", "markdown"])


def test_config(tmp_path, capsys):
    """`config` shows, sets and unsets the tree's settings, each reversible; it can start a tree
    before its first input (plan CF-02)."""
    from cameo_ingest.state import State

    out = tmp_path / "tree"
    assert cli(["config", "-o", str(out)]) == 0
    assert "no tree yet" in capsys.readouterr().out and not out.exists()
    for key, value, expect in (("llm", "off", "llm = off"), ("text-model", "google/gemma-4-31B-it", "= google/gemma-4"),
                               ("rag-source", "id", "rag-source = id"), ("concurrency", "8", "concurrency = 8"),
                               ("render", "no", "render = off")):
        assert cli(["config", "-o", str(out), "set", key, value]) == 0
        assert expect in capsys.readouterr().out
    st = State(out)
    assert st.settings() == {"no_llm": True, "text_model": "google/gemma-4-31B-it", "rag_source": "id",
                             "llm_concurrency": 8, "render": False}
    st.close()
    assert cli(["config", "-o", str(out), "set", "llm", "on"]) == 0  # either way
    assert cli(["config", "-o", str(out), "unset", "text-model"]) == 0
    assert cli(["config", "-o", str(out), "unset", "render"]) == 0
    shown = capsys.readouterr().out
    assert cli(["config", "-o", str(out), "show"]) == 0
    shown = capsys.readouterr().out
    assert "llm           on                 (default)" in shown and "text-model    none" in shown
    assert "concurrency   8" in shown and "rag-source    id" in shown
    for bad in (["set", "llm", "maybe"], ["set", "concurrency", "0"], ["set", "rag-source", "path"],
                ["set", "colour", "red"], ["unset", "colour"]):
        assert cli(["config", "-o", str(out), *bad]) == 2, bad
    assert "the settings are llm, text-model" in capsys.readouterr().err
    # A configured tree then ingests as configured.
    src = tmp_path / "drone.mdzip"
    src.write_bytes(make_mdzip())
    assert cli(["config", "-o", str(out), "set", "llm", "off"]) == 0
    assert cli([str(src), "-o", str(out), "--no-render"]) == 0


def test_config_test_and_models(tmp_path, monkeypatch, capsys, caplog):
    """`config test` checks that each model answers and the vision model reads a drawn number;
    `config models` lists the endpoint's models, those the tree uses marked; a model whose
    creation time changes is noted (plan CF-03)."""
    from cameo_ingest import cli as cli_module
    from cameo_ingest.checks import CARD_NUMBER

    class Endpoint:
        created = 1700000000
        reads = True

        def models(self):
            return [("acme/text", self.created), ("acme/vision", 1700000001), ("acme/embed", None)]

        def complete(self, model, messages, temperature):
            if isinstance(messages[0]["content"], list):  # the card
                return CARD_NUMBER if self.reads else "I can't see images."
            return "Ready."

    endpoint = Endpoint()
    monkeypatch.setattr(cli_module, "make_client", lambda cfg: endpoint)
    out = tmp_path / "tree"
    assert cli(["config", "-o", str(out), "test"]) == 2
    assert "config set text-model" in capsys.readouterr().err
    assert cli(["config", "-o", str(out), "set", "text-model", "acme/text"]) == 0
    assert cli(["config", "-o", str(out), "set", "vision-model", "acme/vision"]) == 0
    capsys.readouterr()
    assert cli(["config", "-o", str(out), "test"]) == 0
    report = capsys.readouterr().out
    assert "ok   the text model acme/text answers" in report and "ok   the vision model acme/vision reads" in report
    endpoint.reads = False
    assert cli(["config", "-o", str(out), "test"]) == 5
    assert "FAIL the vision model acme/vision reads an image" in capsys.readouterr().out
    endpoint.created = 1800000000
    cli(["config", "-o", str(out), "test"])
    assert "acme/text at this endpoint reports another creation time" in caplog.text
    assert cli(["config", "-o", str(out), "models"]) == 0
    listing = capsys.readouterr().out
    assert "acme/text  [text model]" in listing and "acme/vision  [vision model]" in listing and "acme/embed" in listing
    assert cli(["config", "-o", str(out), "models", "vis"]) == 0
    assert "acme/text" not in capsys.readouterr().out


def test_config_interactive(tmp_path, monkeypatch, capsys):
    """`config -i` asks for each setting in turn, finds models by part of their names, tests them,
    and saves only the changes, and only when told to; the input ending saves nothing (plan CF-06)."""
    from cameo_ingest import cli as cli_module
    from cameo_ingest.checks import CARD_NUMBER
    from cameo_ingest.state import State

    class Endpoint:
        def __init__(self):
            self.blind = {"acme/text"}  # models that take no images

        def models(self):
            return [("acme/text", 1), ("acme/vision", 2), ("acme/embed", 3)]

        def complete(self, model, messages, temperature):
            if isinstance(messages[0]["content"], list):
                return "I can't see images." if model in self.blind else CARD_NUMBER
            return "Ready."

    endpoint = Endpoint()
    monkeypatch.setattr(cli_module, "make_client", lambda cfg: endpoint)
    monkeypatch.setenv("OPENAI_API_KEY", "test-key")
    out = tmp_path / "tree"

    def session(*replies: str) -> int:
        queue = list(replies)

        def answer(prompt=""):
            if not queue:
                raise EOFError
            return queue.pop(0)
        monkeypatch.setattr("builtins.input", answer)
        return cli(["config", "-o", str(out), "-i"])

    def settings() -> dict:
        st = State(out)
        try:
            return st.settings()
        finally:
            st.close()

    # LLM on; "acme" lists three, 1 picks the first; "vis" finds one, which Enter takes; render off;
    # a bad count asked again; saved; no calibration now.
    assert session("", "acme", "1", "vis", "", "n", "", "x", "4", "", "n") == 0
    text = capsys.readouterr().out
    assert "  1. acme/text" in text and "  3. acme/embed" in text
    assert "ok   the vision model acme/vision reads an image" in text
    assert "is a whole number" in text and "render: on -> off" in text and "the part size, to acme/text" in text
    assert settings() == {"text_model": "acme/text", "vision_model": "acme/vision", "render": False, "llm_concurrency": 4}

    # Keep everything: no changes, nothing to save, nothing asked about saving.
    assert session("", "", "", "n", "", "", "n") == 0
    assert "No changes." in capsys.readouterr().out

    # The text model as the vision model fails its check, and is chosen again.
    assert session("", "", "same", "y", "", "acme/vision", "", "", "", "n") == 0
    text = capsys.readouterr().out
    assert "FAIL the vision model acme/text" in text and "No changes." in text
    endpoint.blind = set()
    assert session("", "", "same", "n", "", "", "", "n") == 0
    assert "vision-model: acme/vision -> the text model" in capsys.readouterr().out
    assert "vision_model" not in settings()

    # Declining to save, and the input ending, save nothing.
    assert session("n", "y", "y", "n") == 0
    assert "llm: on -> off" in capsys.readouterr().out and "no_llm" not in settings()
    assert session("n", "y") == 130
    assert settings()["text_model"] == "acme/text" and "no_llm" not in settings()
    assert cli(["config", "-o", str(out), "-i", "show"]) == 2
    assert cli(["config", "-o", str(out), "set", "max-calls", "0"]) == 0  # counts what a run would ask
    assert cli(["config", "-o", str(out), "set", "concurrency", "0"]) == 2
