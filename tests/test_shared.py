"""The same item in several models, and how its copies differ (plan SH)."""

import pytest
from helpers import cli

from cameo_ingest import catalog, lineage, shared
from cameo_ingest.evaluation.fiction.lineage import EDITS, corpus
from cameo_ingest.progress import QUIET
from cameo_ingest.state import State


@pytest.fixture(scope="module")
def bids(tmp_path_factory):
    root = tmp_path_factory.mktemp("bids")
    for c in corpus():
        src = root / "in" / c.path
        src.parent.mkdir(parents=True, exist_ok=True)
        src.write_bytes(c.mdzip)
    out = root / "tree"
    for key, value in (("llm", "off"), ("render", "off")):
        assert cli(["config", "-o", str(out), "set", key, value]) == 0
    assert cli([str(root / "in"), "-o", str(out)]) == 0
    return out


def _find(out):
    st = State(out)
    try:
        facts = lineage.facts(st)
        folder = {f"sha256:{r['content_sha256']}": st.sightings(r["content_sha256"])[0]["path"].split("/in/")[1].rsplit("/", 1)[0]
                  for r in st.written()}
        links = shared.find(lambda: catalog.tree_catalogs(st, out, [], QUIET), shared.related_by(facts))
    finally:
        st.close()
    return links, folder


def test_shared_items_and_their_differences(bids):
    """The customer's items are in each bid, matched by element; what a bid changed is told by
    aspect, and nothing else differs (plan SH-01, SH-02)."""
    links, folder = _find(bids)
    token = {f: t for t, f in folder.items()}
    tender = token["lineage/tender"]
    names = {"prf01": "Design Capacity", "prf02": "Filter Run Length", "llpump": "Low-Lift Pump"}
    st = State(bids)
    try:
        recs = next(c.records for c in catalog.tree_catalogs(st, bids, [], QUIET) if c.header["token"] == tender)
    finally:
        st.close()
    key = {item: next(r["key"] for r in recs if r.get("name", "").startswith(name) and r["type"] != "diagram")
           for item, name in names.items()}
    for where, item, aspect in EDITS:
        lk = next(lk for lk in links[token[where], key[item]] if lk.other.token == tender)
        assert lk.basis == "element" and len(lk.differences) == 1, (where, item, lk.differences)
        assert lk.differences[0].startswith({"text": "text", "name": "name:", "relations": "relationships"}[aspect])
    lk = next(lk for lk in links[token["lineage/bids/halvorsen"], key["prf02"]] if lk.other.token == tender)
    assert "only here: satisfied by" in lk.differences[0]  # the bidder's satisfy, on the customer's requirement
    changed = {(folder[t], k) for (t, k), lks in links.items() if t != tender
               for lk in lks if lk.other.token == tender and lk.differences}
    assert changed == {(where, key[item]) for where, item, _ in EDITS}  # nothing else in the customer's part


def test_name_matches_only_between_related_models(bids):
    """A name matches only between models that lineage relates, and only when it names one item
    in each."""
    links, _ = _find(bids)
    st = State(bids)
    try:
        related = shared.related_by(lineage.facts(st))
    finally:
        st.close()
    names = [(t, lk) for (t, _), lks in links.items() for lk in lks if lk.basis == "name"]
    assert all(related(t, lk.other.token) for t, lk in names)
    assert {lk.basis for lks in links.values() for lk in lks} >= {"element"}


def test_relationships_line_up_by_label_when_ids_differ():
    """A relationship to a re-made element (another id, the same name) is the same relationship."""
    from cameo_ingest.shared import Copy, differences

    def copy(rels):
        return Copy("t", "k", "requirement", "Requirement", "R", "R-1", "x", (), (), tuple(sorted(rels)), (), (), "P")
    a = copy([("Satisfy", "in", "id-1", "Pump", "satisfied by")])
    b = copy([("Satisfy", "in", "id-2", "Pump", "satisfied by")])
    assert differences(a, b) == []
    c = copy([("Satisfy", "in", "id-3", "Valve", "satisfied by")])
    assert differences(a, c) == ["relationships (only here: satisfied by Pump; only there: satisfied by Valve)"]


def test_package_differences_show_where_paths_part():
    from cameo_ingest.shared import _parted

    assert _parted("A::B::IRIS::Imager", "A::B::IFS::Imager") == ("…::B::IRIS::Imager", "…::B::IFS::Imager")
    assert _parted("", "A") == ("(the root)", "A")
