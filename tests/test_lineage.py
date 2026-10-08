"""Lineage of models (plan LN): versions, copies, models derived by others, rivals on a shared
root and related models, told apart by who made each side's own ids and when."""

from helpers import cli

from cameo_ingest import lineage
from cameo_ingest.evaluation.fiction.lineage import TRUTH
from cameo_ingest.state import State


def test_lineage_of_the_synthetic_cases(lineage_tree):
    st = State(lineage_tree)
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


def test_families_keep_rivals_apart(lineage_tree, capsys):
    """Families are chains of versions (ADR-0032): Halvorsen's two versions are one family, while
    the customer's tender and the two bids on it stay apart, each with its own diagrams; `groups`
    lists them as kin, with their folders and evidence."""
    import json

    out = lineage_tree
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


def test_a_family_is_named_by_its_newest_written_version(lineage_tree, tmp_path):
    """The exports' lineage facts are over the written projects (CQ-005): when Halvorsen's newest
    version failed, the family is its older, written one, with one version, not a token the
    exports don't hold."""
    import shutil

    out = tmp_path / "tree"
    shutil.copytree(lineage_tree, out)
    st = State(out)
    try:
        where = {r["content_sha256"]: st.sightings(r["content_sha256"])[0]["path"].split("/in/")[1] for r in st.written()}
        newest = next(sha for sha, p in where.items() if p.startswith("lineage/bids/halvorsen/v2/"))
        older = next(sha for sha, p in where.items() if p == "lineage/bids/halvorsen/Riverbend_Water_Treatment_Works.mdzip")
        assert lineage.facts(st)[f"sha256:{older}"]["family"] == f"sha256:{newest}"  # both written
        with st.db:
            st.db.execute("UPDATE projects SET status = 'failed' WHERE content_sha256 = ?", (newest,))
        facts = lineage.facts(st)
    finally:
        st.close()
    assert f"sha256:{newest}" not in facts
    fact = facts[f"sha256:{older}"]
    assert fact["family"] == f"sha256:{older}" and fact["rank"] == 0 and fact["versions"] == 1
