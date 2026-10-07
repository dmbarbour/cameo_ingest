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
