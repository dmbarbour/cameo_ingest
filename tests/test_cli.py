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
    project_dir,
    provenance,
    run,
    tree,
)

from cameo_ingest.cli import main


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
        assert main(["add", "-o", str(out), str(tree), "-vv"]) == 0
    assert "looking for models under" in caplog.text
    assert "candidate: " in caplog.text and "drone.mdzip (ZIP)" in caplog.text
    assert "found 1 candidate(s)" in caplog.text and "2 file(s) skipped by type" in caplog.text
    assert "report.docx" not in caplog.text


def test_destination_from_the_environment(tmp_path, monkeypatch, capsys):
    """Without -o, the output tree is $CAMEO_INGEST_DEST, which may come from an --env file."""
    src = tmp_path / "drone.mdzip"
    src.write_bytes(make_mdzip())
    monkeypatch.delenv("CAMEO_INGEST_DEST", raising=False)
    assert main([str(src), "--no-llm", "--no-render"]) == 2
    assert "CAMEO_INGEST_DEST" in capsys.readouterr().err
    monkeypatch.setenv("CAMEO_INGEST_DEST", str(tmp_path / "dest"))
    assert main([str(src), "--no-llm", "--no-render"]) == 0
    assert (tmp_path / "dest" / "manifest.json").is_file()
    assert main(["status"]) == 0
    monkeypatch.delenv("CAMEO_INGEST_DEST")
    env = tmp_path / "settings.env"
    env.write_text(f"CAMEO_INGEST_DEST={tmp_path / 'from-env'}\n")
    try:
        assert main([str(src), "--env", str(env), "--no-llm", "--no-render"]) == 0
        assert (tmp_path / "from-env" / "manifest.json").is_file()
    finally:
        os.environ.pop("CAMEO_INGEST_DEST", None)  # set by the --env file, not by monkeypatch


def test_tree_rules_and_missing_inputs(tmp_path, capsys):
    foreign = tmp_path / "foreign"
    foreign.mkdir()
    (foreign / "notes.txt").write_text("mine")
    src = tmp_path / "drone.mdzip"
    src.write_bytes(make_mdzip())
    assert main([str(src), "-o", str(foreign), "--no-llm"]) == 2  # never write into an unrelated directory
    assert main(["run", "-o", str(tmp_path / "nothing")]) == 2
    assert "not a cameo-ingest output tree" in capsys.readouterr().err
    out = tmp_path / "out"
    assert main([str(src), "-o", str(out), "--no-llm", "--no-render"]) == 0
    src.unlink()  # the input disappears: its project stays (plan decision 3)
    assert main(["run", "-o", str(out)]) == 0
    [record] = provenance(out).values()
    assert record["status"] == "written" and record["sightings"][0]["missing"]
    assert "(input missing)" in (out / "INDEX.md").read_text()


def test_options_change_rewrites_projects(tmp_path, monkeypatch, fake_chat):
    """Output made with other options or another tool version is written again, and files
    the new version doesn't produce disappear with the old directory (plan RI-06)."""
    src = tmp_path / "drone.mdzip"
    src.write_bytes(make_mdzip())
    out = tmp_path / "out"
    assert main([str(src), "-o", str(out), "--no-llm"]) == 0
    proj = project_dir(out)
    assert (proj / "diagrams/Drone_BDD.png").exists()
    assert main(["run", "-o", str(out)]) == 0
    assert json.loads((out / "run.json").read_text())["projects"]["written"] == 0  # up to date
    assert main(["run", "-o", str(out), "--no-render"]) == 0
    assert json.loads((out / "run.json").read_text())["projects"]["written"] == 1
    assert not (proj / "diagrams/Drone_BDD.png").exists() and (proj / "README.md").exists()
    import dataclasses

    from cameo_ingest import prompts, runner

    # A new prompt template version counts as an option change (FU-014).
    later = dataclasses.replace(prompts.PACKAGE_SUMMARY, version=prompts.PACKAGE_SUMMARY.version + 1)
    monkeypatch.setitem(prompts.CURRENT, "package-summary", later)
    assert main(["run", "-o", str(out), "--text-model", "m", "--no-calibrate"]) == 0
    assert json.loads((out / "run.json").read_text())["projects"]["written"] == 1
    monkeypatch.setitem(prompts.CURRENT, "package-summary", prompts.PACKAGE_SUMMARY)
    assert main(["run", "-o", str(out)]) == 0
    assert json.loads((out / "run.json").read_text())["projects"]["written"] == 1
    assert main(["run", "-o", str(out)]) == 0
    assert json.loads((out / "run.json").read_text())["projects"]["written"] == 0
    monkeypatch.setattr(runner, "TOOL", "cameo-ingest/99")
    assert main(["run", "-o", str(out)]) == 0
    assert json.loads((out / "run.json").read_text())["projects"]["written"] == 1


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


def test_progress_heartbeats_and_log_file(tmp_path, fake_chat, monkeypatch, capsys):
    monkeypatch.setattr(FakeChat, "delay", 0.1)
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


def test_interrupt_and_resume(tmp_path, fake_chat, monkeypatch, capsys):
    """A run stopped part-way continues where it stopped, and ends with the same output as a
    run that was never interrupted (plan RI-07)."""
    src = tmp_path / "drone.mdzip"
    src.write_bytes(make_mdzip())
    ref = tmp_path / "ref"
    assert main([str(src), "-o", str(ref), "--vision-model", "m", "--no-calibrate", "--no-preflight"]) == 0
    monkeypatch.setattr(FakeChat, "interrupt_at", 2)  # Ctrl-C during the second LLM request
    out = tmp_path / "out"
    assert main([str(src), "-o", str(out), "--vision-model", "m", "--no-calibrate", "--no-preflight"]) == 130
    assert "Continue with: cameo-ingest run -o" in capsys.readouterr().err
    assert json.loads((out / "run.json").read_text())["outcome"] == "interrupted"
    assert json.loads((out / "manifest.json").read_text())["projects"] == []  # nothing half-published
    [work] = (out / "by-sha256/.work").iterdir()
    sketch = (work / "diagrams/Drone_BDD.png").stat().st_mtime_ns  # drawn before the interruption
    monkeypatch.setattr(FakeChat, "interrupt_at", None)
    assert main(["run", "-o", str(out), "--no-preflight"]) == 0  # the tree remembers the model
    assert json.loads((out / "run.json").read_text())["llm"]["outcomes"] == {"answered": 2, "cached": 1}
    assert (project_dir(out) / "diagrams/Drone_BDD.png").stat().st_mtime_ns == sketch  # reused, not redrawn
    assert tree(out) == tree(ref)


def test_status_and_prune(tmp_path, capsys):
    a, b = tmp_path / "a.mdzip", tmp_path / "b.mdzip"
    a.write_bytes(make_mdzip())
    b.write_bytes(make_mdzip(MODEL.replace("name='Requirements'", "name='Needs'")))
    out = tmp_path / "out"
    assert main([str(a), str(b), "-o", str(out), "--no-llm", "--no-render"]) == 0
    b.unlink()
    assert main(["run", "-o", str(out)]) == 0
    capsys.readouterr()
    assert main(["status", "-o", str(out), "--json"]) == 0
    s = json.loads(capsys.readouterr().out)
    assert s["inputs"]["counts"] == {"done": 1, "missing": 1} and s["projects"]["counts"] == {"written": 2}
    assert s["inputs"]["problems"] == [{"path": str(b), "status": "missing", "error": None}]
    assert s["latest_run"]["outcome"] == "finished"
    assert main(["prune", "-o", str(out), "--dry-run"]) == 0
    assert "would remove 1 missing input(s) and 1 project(s)" in capsys.readouterr().out
    assert len(list((out / "by-sha256").glob("[0-9a-f]*"))) == 2
    assert main(["prune", "-o", str(out)]) == 0
    assert [p["name"] for p in json.loads((out / "manifest.json").read_text())["projects"]] == ["a.mdzip"]
    assert len(list((out / "by-sha256").glob("[0-9a-f]*"))) == 1
    capsys.readouterr()
    assert main(["status", "-o", str(out)]) == 0
    assert "inputs: 1 done\nprojects: 1 written\n" in capsys.readouterr().out


def test_markdown_chunk_style_retired(tmp_path, caplog):
    """A tree that stored the retired Markdown chunk style runs on with plain chunks (plan RA-02)."""
    from cameo_ingest.state import State

    out = run(tmp_path, "drone.mdzip", make_mdzip())
    st = State(out)
    st.save_settings({**st.settings(), "chunk_style": "markdown"})
    st.close()
    assert main(["run", "-o", str(out)]) == 0
    assert "Markdown chunk style is retired" in caplog.text
    st = State(out)
    assert "chunk_style" not in st.settings()
    st.close()
    assert not list((out / "rag" / "text").rglob("*.md")) and list((out / "rag" / "text").rglob("*.txt"))
    with pytest.raises(SystemExit):
        main([str(tmp_path / "drone.mdzip"), "-o", str(tmp_path / "again"), "--chunk-style", "markdown"])
