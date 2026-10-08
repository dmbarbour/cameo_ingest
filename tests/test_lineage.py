"""Lineage of models (plan LN): versions, copies, models derived by others, rivals on a shared
root and related models, told apart by who made each side's own ids and when."""

from helpers import cli

from cameo_ingest import lineage
from cameo_ingest.evaluation.fiction.lineage import TRUTH, corpus
from cameo_ingest.state import State


def test_lineage_of_the_synthetic_cases(tmp_path):
    for c in corpus():
        src = tmp_path / "in" / c.path
        src.parent.mkdir(parents=True, exist_ok=True)
        src.write_bytes(c.mdzip)
    out = tmp_path / "tree"
    assert cli(["config", "-o", str(out), "set", "llm", "off"]) == 0
    assert cli(["add", "-o", str(out), str(tmp_path / "in")]) == 0
    assert cli(["scan", "-o", str(out)]) == 0  # fingerprints are enough: nothing built
    st = State(out)
    try:
        pairs = lineage.pairs(st)
        where = {sha: st.sightings(sha)[0]["path"].split("/in/")[1] for p in pairs for sha in (p.a.sha, p.b.sha)}
    finally:
        st.close()
    got = {(where[p.a.sha], where[p.b.sha]): p for p in pairs}
    assert len(got) == len(TRUTH)
    for a, b, kind in TRUTH:
        p = got.get((a, b)) or got.get((b, a))
        assert p is not None and p.kind == kind, (a, b, kind, p and (p.kind, p.why))
        if kind in ("version", "derived"):
            assert (where[p.a.sha], where[p.b.sha]) == (a, b)  # the older first
    rivals = got["lineage/bids/halvorsen/Riverbend_Water_Treatment_Works.mdzip",
                 "lineage/bids/aquila/Riverbend_Water_Treatment_Works.mdzip"]
    assert "rivals on a shared root" in rivals.why and rivals.folder.endswith("lineage/bids")


def test_families_keep_rivals_apart(tmp_path, capsys):
    """Families are chains of versions (ADR-0032): Halvorsen's two versions are one family, while
    the customer's tender and the two bids on it stay apart, each with its own diagrams; `groups`
    lists them as kin, with their folders and evidence."""
    import json

    for c in corpus():
        src = tmp_path / "in" / c.path
        src.parent.mkdir(parents=True, exist_ok=True)
        src.write_bytes(c.mdzip)
    out = tmp_path / "tree"
    assert cli(["config", "-o", str(out), "set", "llm", "off"]) == 0
    assert cli(["config", "-o", str(out), "set", "render", "off"]) == 0
    assert cli([str(tmp_path / "in"), "-o", str(out)]) == 0
    fams = json.loads((out / "subjects.json").read_text())["families"]
    riverbend = sorted(len(f["tokens"]) for f in fams if f["name"] == "Riverbend_Water_Treatment_Works.mdzip")
    assert riverbend == [1, 1, 2]  # the tender, Aquila's bid, Halvorsen's two versions
    capsys.readouterr()
    assert cli(["groups", "-o", str(out)]) == 0
    report = capsys.readouterr().out
    kin = report.split("## Built on one another, kept apart")[1].split("## Related")[0]
    assert kin.count("**Rivals on a shared root:**") == 2 and kin.count("**Derived by others:**") == 3
    assert "in " in kin and "lineage/bids/aquila" in kin


def test_the_older_is_older_in_utc():
    """Saves in different time zones are ordered by the instant, not the text (CQ-001): 11:39 at
    UTC-7 is 18:39 UTC, after 15:00 at UTC+1 (14:00 UTC), though it sorts first as text."""
    from array import array

    from cameo_ingest.fingerprint import NO_MAKER

    def model(sha, saved):
        n = 40
        return lineage.Model(sha, sha, saved, [f"/{sha}/m.mdzip"], array("q", range(n)), [],
                             array("i", [NO_MAKER] * n), array("i", [0] * n))

    west, east = model("a", "2023-11-02T11:39:23-07:00"), model("b", "2023-11-02T15:00:00+01:00")
    for x, y in ((west, east), (east, west)):
        p = lineage.compare(x, y)
        assert (p.a.sha, p.b.sha) == ("b", "a")
