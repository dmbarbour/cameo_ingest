"""Versions of a model, found by shared element ids, and projects removed from a tree (plan PV)."""

import io
import json
import sqlite3
import zipfile

from helpers import cli, ingest, tree

from cameo_ingest.fingerprint import parse_java_date
from cameo_ingest.state import SCHEMA_VERSION, State


def model(name: str, ids: list[str], saved: str | None = "Thu Nov 02 11:39:23 PDT 2023") -> bytes:
    """A small Cameo project: one package of classes with these ids, saved at `saved` (as
    Records.properties says it), or without a save time."""
    classes = "".join(f"<packagedElement xmi:type='uml:Class' xmi:id='{i}' name='C {i}'/>" for i in ids)
    xmi = (f"<?xml version='1.0' encoding='UTF-8'?><xmi:XMI xmlns:xmi='http://www.omg.org/spec/XMI/20131001' "
           f"xmlns:uml='http://www.omg.org/spec/UML/20131001'><uml:Model xmi:type='uml:Model' xmi:id='m_{name}' "
           f"name='{name}'><packagedElement xmi:type='uml:Package' xmi:id='p_{name}' name='Things'>{classes}"
           f"</packagedElement></uml:Model></xmi:XMI>")
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        def put(entry: str, text: str) -> None:
            z.writestr(zipfile.ZipInfo(entry, date_time=(2024, 5, 6, 7, 8, 9)), text)
        put("com.nomagic.magicdraw.uml_model.model", xmi)
        if saved:
            put("Records.properties", f"#Compatibility entry\n#{saved}\n")
    return buf.getvalue()


BASE = [f"_base_{k}" for k in range(100)]


def test_save_times():
    assert parse_java_date("#Compatibility entry\n#Thu Nov 02 11:39:23 PDT 2023\nX=Y") == (
        "2023-11-02T11:39:23-07:00", "Thu Nov 02 11:39:23 PDT 2023")
    assert parse_java_date("#Sun Oct 26 20:33:19 CET 2025\n")[0] == "2025-10-26T20:33:19+01:00"
    assert parse_java_date("#Mon Jan 05 01:02:03 XYZT 2026\n") == (
        "2026-01-05T01:02:03", "Mon Jan 05 01:02:03 XYZT 2026")
    assert parse_java_date("no date here") == (None, None)


def test_groups_versions_forks_and_templates(tmp_path, capsys):
    """A model saved twice is grouped, newest first, with a remove command for the older; a fork
    is grouped with a warning and left out of that command; a model made from a template is
    only related."""
    out = tmp_path / "out"
    inputs = [
        ("plant/v1/plant.mdzip", model("Plant", BASE, "Mon Jan 08 10:00:00 PST 2024")),
        ("plant/v2/plant.mdzip", model("Plant", BASE + [f"_v2_{k}" for k in range(30)],
                                       "Tue Mar 05 10:00:00 PST 2024")),
        ("fork/a.mdzip", model("Rig", [f"_rig_{k}" for k in range(100)] + [f"_a_{k}" for k in range(20)],
                               "Mon Jan 08 10:00:00 CET 2024")),
        ("fork/b.mdzip", model("Rig", [f"_rig_{k}" for k in range(100)] + [f"_b_{k}" for k in range(30)],
                               "Fri Feb 02 10:00:00 CET 2024")),
        ("template.mdzip", model("Template", [f"_t_{k}" for k in range(30)], None)),
        ("derived.mdzip", model("Derived", [f"_t_{k}" for k in range(30)] + [f"_d_{k}" for k in range(500)])),
    ]
    for rel, data in inputs:
        (tmp_path / rel).parent.mkdir(parents=True, exist_ok=True)
        (tmp_path / rel).write_bytes(data)
    assert cli(["add", "-o", str(out), str(tmp_path / "plant"), str(tmp_path / "fork"),
                 str(tmp_path / "template.mdzip"), str(tmp_path / "derived.mdzip")]) == 0
    assert cli(["scan", "-o", str(out)]) == 0
    capsys.readouterr()
    assert cli(["groups", "-o", str(out), "--csv", str(tmp_path / "groups.csv")]) == 0
    report = capsys.readouterr().out
    assert "2 group(s) of likely versions" in report
    plant = report[report.index("## Group 2: plant.mdzip"):]
    assert plant.index("Tue Mar 05") < plant.index("Mon Jan 08")  # newest first
    assert "100% shared, 0% only here" in plant
    assert "## Group 1: b.mdzip" in report and "has 16% of its elements that the newest lacks" in report
    assert "Template" not in report.split("## Related")[0] and "template.mdzip" in report.split("## Related")[1]
    st = State(out)
    rows = {r["name"]: r for r in st.catalog()}
    older = next(r["sha256"] for r in st.catalog()
                 if r["saved_raw"] and r["saved_raw"].startswith("Mon Jan 08 10:00:00 PST"))
    fork_a = rows["a.mdzip"]["sha256"]
    st.close()
    command = report.split("```sh\n")[1].split("\n")[0]
    assert older[:12] in command and fork_a[:12] not in command  # a fork is for the maintainer to check
    assert rows["template.mdzip"]["saved_from"] == "zip"  # no Records.properties: the zip's dates stand in
    lines = (tmp_path / "groups.csv").read_text().splitlines()
    assert lines[0].startswith("group,rank,token") and len(lines) == 1 + 4


def test_removed_projects_stay_out(tmp_path, capsys):
    """`remove` deletes a project's output and keeps it out of later runs while its input
    remains; `restore` lets the next run build it again; nothing else in the tree changes."""
    out = ingest(tmp_path, ("old.mdzip", model("Old", BASE)), ("new.mdzip", model("New", BASE + ["_x"])))
    before = tree(out)
    st = State(out)
    old = next(r["sha256"] for r in st.catalog() if r["name"] == "old.mdzip")
    st.close()
    assert cli(["remove", "-o", str(out), old[:10]]) == 0
    assert not (out / "by-sha256" / old).exists()
    assert cli(["run", "-o", str(out), "--no-llm"]) == 0  # the input is still there
    assert not (out / "by-sha256" / old).exists()
    assert old not in (out / "chunks.jsonl").read_text() and "old.mdzip" not in json.dumps(
        json.loads((out / "manifest.json").read_text())["projects"])
    assert "old.mdzip `sha256:" in (out / "INDEX.md").read_text() and "removed" in (out / "INDEX.md").read_text()
    capsys.readouterr()
    assert cli(["status", "-o", str(out)]) == 0 and "1 removed" in capsys.readouterr().out
    assert cli(["remove", "-o", str(out), "sha256:" + old[:8]]) == 2  # already removed: no match
    assert cli(["restore", "-o", str(out), old[:8]]) == 0
    assert cli(["run", "-o", str(out), "--no-llm"]) == 0
    assert tree(out) == before


def test_a_tree_from_before_opens(tmp_path):
    """A state file of schema 1 gains the new tables, and its status view learns of removals."""
    st = State(tmp_path)
    st.db.execute("DROP VIEW project_status")
    st.db.execute("CREATE VIEW project_status AS SELECT c.sha256, c.name, COALESCE(p.status, 'pending') AS status, "
                  "p.error, p.updated, 0 AS sightings FROM contents c "
                  "LEFT JOIN projects p ON p.content_sha256 = c.sha256")
    st.db.execute("UPDATE meta SET value = '1' WHERE key = 'schema_version'")
    st.db.execute("INSERT INTO contents VALUES ('ab' || hex(zeroblob(31)), 'x.mdzip', 'zip', 1, 'now')")
    st.close()
    st = State(tmp_path)
    sha = st.catalog()[0]["sha256"]
    st.remove([(sha, "x.mdzip")])
    assert st.catalog()[0]["status"] == "removed"
    assert st.db.execute("SELECT value FROM meta WHERE key = 'schema_version'").fetchone()[0] == str(SCHEMA_VERSION)
    st.close()
    assert sqlite3.connect(tmp_path / "state.sqlite").execute("SELECT count(*) FROM removed").fetchone() == (1,)


def test_scan_reports_what_it_is_on(tmp_path, caplog, monkeypatch):
    """A scan counts bytes, and its status lines name the input and the step, so that a long
    file, or one that arrives slowly, doesn't look stuck."""
    import logging
    import time

    from cameo_ingest.config import ProjectOptions
    from cameo_ingest.llm import EnrichmentSession, LLMConfig
    from cameo_ingest.progress import Progress
    from cameo_ingest.runner import Runner

    src = tmp_path / "slow.mdzip"
    src.write_bytes(model("Slow", BASE))
    out = tmp_path / "out"
    assert cli(["add", "-o", str(out), str(src)]) == 0
    original = Runner._read

    def slow(self, path, ph):
        time.sleep(0.6)
        return original(self, path, ph)

    monkeypatch.setattr(Runner, "_read", slow)
    st = State(out)
    runner = Runner(st, out, EnrichmentSession(LLMConfig(None, None, None), out / ".cache", None), ProjectOptions(),
                    Progress(heartbeat=0.2, bars=False))
    with caplog.at_level(logging.INFO, logger="cameo_ingest"):
        runner.scan()
    st.close()
    beats = [r.getMessage() for r in caplog.records if "now: reading slow.mdzip" in r.getMessage()]
    assert beats and "scanning 1 input: 0.0 MB of 0.0 MB" in beats[0] and "(0.0 MB, 1/1)" in beats[0]
    assert any("found 1 project(s) in slow.mdzip, 1 not seen before" in r.getMessage() for r in caplog.records)
