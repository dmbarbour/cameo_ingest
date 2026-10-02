"""The state database of an output tree (plan RI-01)."""

import json

import pytest

from cameo_ingest.state import State, StateError


def test_task_list(tmp_path):
    st = State(tmp_path)
    a, b = tmp_path / "a.mdzip", tmp_path / "b.mdzip"
    assert st.add_input(a, {"program": "X"}) and st.add_input(b, {})
    assert not st.add_input(a, {"program": "X"})  # already listed
    [row] = st.inputs("pending")[:1]
    st.update_input(row["id"], status="done", sha256="h1")
    assert [r["path"] for r in st.inputs("pending")] == [str(b)]
    st.add_input(a, {"program": "Y"})  # new metadata: to be processed again
    assert {r["path"] for r in st.inputs("pending")} == {str(a), str(b)}
    assert json.loads(st.inputs()[0]["metadata"]) == {"program": "Y"}


def test_sightings_follow_the_current_input_version(tmp_path):
    st = State(tmp_path)
    st.add_input(tmp_path / "bundle.zip", {})
    inp = st.inputs()[0]["id"]
    st.update_input(inp, sha256="v1")
    assert st.record_sighting("c1", "x.mdzip", "zip", 10, inp, "v1", ("inner.zip", "x.mdzip"))
    assert not st.record_sighting("c1", "other.mdzip", "zip", 10, inp, "v1", ())  # known content, second place
    assert st.content("c1")["name"] == "x.mdzip"  # the first name sticks
    assert [json.loads(s["chain"]) for s in st.sightings("c1")] == [["inner.zip", "x.mdzip"], []]
    st.update_input(inp, sha256="v2")  # the file changed: its old sightings are history
    assert st.sightings("c1") == []
    status = st.db.execute("SELECT status, sightings FROM project_status").fetchone()
    assert tuple(status) == ("pending", 0)


def test_publish_is_atomic(tmp_path):
    st = State(tmp_path)
    st.add_input(tmp_path / "a.mdzip", {})
    st.record_sighting("c1", "a.mdzip", "zip", 1, 1, "v1", ())
    st.set_project("c1", "working", tool="t", options_hash="o")
    with pytest.raises(ValueError), st.tx():
        st.set_project("c1", "written")
        raise ValueError("interrupted")
    assert st.project("c1")["status"] == "working"  # rolled back
    st.publish("c1", "t", "o", {"elements": 3}, [("README.md", "h"), ("LEDGER.md", "g")])
    assert st.project("c1")["status"] == "written"
    assert [tuple(f) for f in st.files("c1")] == [("LEDGER.md", "g"), ("README.md", "h")]
    assert [r["name"] for r in st.written()] == ["a.mdzip"]


def test_lock_settings_and_schema(tmp_path):
    st = State(tmp_path)
    st.lock()
    other = State(tmp_path)
    with pytest.raises(StateError, match="another cameo-ingest run"):
        other.lock()
    st.unlock()
    other.lock()  # free again
    other.save_settings({"text_model": "m", "render": True})
    assert State(tmp_path).settings() == {"render": True, "text_model": "m"}
    st.db.execute("UPDATE meta SET value = '99' WHERE key = 'schema_version'")
    with pytest.raises(StateError, match="newer cameo-ingest"):
        State(tmp_path)


def test_settings_and_options():
    """Settings with their defaults in one place; a tree remembers only what differs from them,
    and a project's options hash as before they were typed (AR-013)."""
    import pytest

    from cameo_ingest.config import MODULES, ProjectOptions, TreeSettings, parse_modules
    from cameo_ingest.provenance import sha256_text

    s = TreeSettings.from_stored({"threads": False, "chunk_style": "markdown", "text_model": None})
    assert s.threads is False and s.cross_index is True and s.stored() == {"threads": False}
    assert parse_modules(None) == MODULES and parse_modules("0:1:2") == (0, 1, 2)
    with pytest.raises(ValueError):
        parse_modules("25:6")
    o = ProjectOptions.of(s, None, None, None)
    assert o.templates == () and o.hash() == sha256_text(json.dumps(o.as_dict(), sort_keys=True))[:16]
