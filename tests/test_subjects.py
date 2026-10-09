"""Splitting models into subjects (plan SB): version families, each diagram once, and every
candidate split covering every diagram."""

import json
from collections import Counter
from types import SimpleNamespace

import pytest

from cameo_ingest import discovery


def test_families_and_splits(tmp_path):
    pytest.importorskip("numpy")  # the study's word clusters
    from helpers import cli, write_inputs

    from cameo_ingest.evaluation.fiction import PROJECTS
    from cameo_ingest.evaluation.fiction.versions import VERSIONS
    from cameo_ingest.evaluation.subjects import SPLITS, families, measures, target

    projects = [PROJECTS[p]() for p in ("pct", "kois", "rwt", "hal", "aqu")]
    projects += [VERSIONS[v][1]() for v in ("kestrel-later", "port-calder-fork")]
    inputs = write_inputs(tmp_path / "in", *((p.path, p.mdzip()) for p in projects))
    out = tmp_path / "out"
    assert cli([str(inputs), "-o", str(out), "--no-llm", "--no-render"]) == 0

    fams = {f.tokens[0]: f for f in families(out)}
    sizes = Counter(len(f.tokens) for f in fams.values())
    assert sizes == Counter({2: 2, 1: 3})  # Kestrel and its later save, Port Calder and its fork; three rivals apart
    fork = next(f for f in fams.values() if f.name == "Eastport_Traffic_Signals.mdzip")
    assert fork.copies > len(fork.items)  # the diagrams both hold, once
    assert all(it.versions for it in fork.items.values()) and any(len(it.versions) == 2 for it in fork.items.values())
    assert sum(1 for it in fork.items.values() if it.shows) > len(fork.items) // 2
    k = target(len(fork.items))
    for name, split in SPLITS.items():
        s = split(fork, k)
        assert set(s) == set(fork.items), name
        assert 1 <= measures(s)["groups"] <= max(k, 2) + 2, (name, measures(s))


class FakeLLM:
    """Answers subject requests: three ways of two subjects, and each batch's diagrams put in turn
    in subject 1 and 2. `fail` names what goes unanswered: "propose", or the n-th batch (from 1)."""

    def __init__(self, fail=None):
        self.cfg = SimpleNamespace(text_model="acme/text")
        self.fail = fail
        self.asked = Counter()
        self.batch = 0

    def ask(self, template, values, **_):
        self.asked[template.id] += 1
        if template.id == "subjects-propose":
            if self.fail == "propose":
                return ("I can't help with that.", None)
            ways = [{"principle": p, "subjects": [{"label": f"{p} one", "holds": "x"}, {"label": f"{p} two", "holds": "y"}]}
                    for p in ("By part", "By activity", "By concern")]
            return (json.dumps({"ways": ways}), None)
        if template.id == "topics-propose":
            return (json.dumps({"topics": [{"label": "Topic one", "holds": "x"}, {"label": "Topic two", "holds": "y"}]}), None)
        if template.id == "topics-assign":
            n = values["SUBJECTS"].count("\n") + 1
            return (json.dumps({str(i): 1 + i % 2 for i in range(1, n + 1)}), None)
        self.batch += 1
        if self.fail == self.batch:
            return None
        n = values["DIAGRAMS"].count("\n") + 1
        return (json.dumps({str(i): 1 + i % 2 for i in range(1, n + 1)}), None)


@pytest.fixture(scope="module")
def versions_tree(tmp_path_factory):
    from helpers import cli, write_inputs

    from cameo_ingest.evaluation.fiction import PROJECTS
    from cameo_ingest.evaluation.fiction.versions import VERSIONS

    root = tmp_path_factory.mktemp("versions")
    projects = (PROJECTS["pct"](), PROJECTS["kois"](), VERSIONS["port-calder-fork"][1]())
    inputs = write_inputs(root / "in", *((p.path, p.mdzip()) for p in projects))
    out = root / "out"
    assert cli([str(inputs), "-o", str(out), "--no-llm", "--no-render"]) == 0
    return out


def _update(out, llm=None, ask_again=True):
    from cameo_ingest import subjects
    from cameo_ingest.state import State

    st = State(out)
    try:
        counts = subjects.update(st, out, llm, ask_again=ask_again)
    finally:
        st.close()
    data = json.loads((out / discovery.FILE).read_text())
    return counts, {r["name"]: r for r in data["families"]}


BATCHES = 3  # the fork's 88 diagrams, in batches of up to 30 cut by package


def test_subjects_and_their_fallbacks(versions_tree, tmp_path):
    """ADR-0031: without the LLM, shared elements first; with it, its ways; a failed proposal or
    batch falls back, never guessing; a small family has packages only; an unchanged family keeps
    its subjects when no session is at hand."""
    import shutil

    from cameo_ingest import subjects

    out = tmp_path / "tree"
    shutil.copytree(versions_tree, out)
    fork = "Eastport_Traffic_Signals.mdzip"

    counts, fams = _update(out)
    assert counts["families"] == 2  # Port Calder and its fork, one family; Kestrel alone
    f = fams[fork]
    assert len(f["tokens"]) == 2 and f["ways"] == "not asked" and f["default"] == "shared"
    assert [v["id"] for v in f["views"]] == ["shared", "packages"]
    for v in f["views"]:  # every diagram once in each view
        keys = [k for s in v["subjects"] for k in s["diagrams"]]
        assert sorted(keys) == sorted(f["diagrams"]), v["id"]
    assert any(len(versions) == 2 for versions in f["diagrams"].values())
    small = fams["Kestrel_Orchard_Irrigation.mdzip"]
    assert small["ways"] == "too few diagrams" and [v["id"] for v in small["views"]] == ["packages"]
    topics = subjects.load_topics(out)  # across the two families: by words, with no LLM
    assert topics["ways"] == "not asked" and [v["id"] for v in topics["views"]] == ["words"]
    every = sorted(f"{r['tokens'][0]}/{n}" for r in fams.values()
                   for n, _ in enumerate(next(v for v in r["views"] if v["id"] == r["default"])["subjects"]))
    assert sorted(i for t in topics["views"][0]["topics"] for i in t["subjects"]) == every

    llm = FakeLLM()
    counts, fams = _update(out, llm)
    f = fams[fork]
    assert f["ways"] == "found" and [v["id"] for v in f["views"]] == ["ways-1", "ways-2", "ways-3", "packages"]
    assert f["views"][0]["title"] == "By part" and f["views"][0]["subjects"][0]["label"] == "By part one"
    assert llm.asked["subjects-propose"] == 1 and llm.asked["subjects-assign"] == 3 * BATCHES

    again = FakeLLM()
    _, kept = _update(out, again)  # complete and unchanged: nothing asked
    assert kept[fork] == f and not again.asked
    topics = subjects.load_topics(out)
    assert topics["ways"] == "found" and [v["id"] for v in topics["views"]] == ["llm", "words"]
    assert sorted(t["label"] for t in topics["views"][0]["topics"]) == ["Topic one", "Topic two"]
    assert llm.asked["topics-propose"] == 1
    _, kept = _update(out)  # no session (`remove`, `prune`): kept
    assert kept[fork] == f

    (out / discovery.FILE).unlink()
    _, fams = _update(out, FakeLLM(fail="propose"))
    assert fams[fork]["ways"] == "failed" and fams[fork]["default"] == "shared"

    (out / discovery.FILE).unlink()
    _, fams = _update(out, FakeLLM(fail=1))
    f = fams[fork]
    unsorted = f["views"][1]["unsorted"]
    assert f["ways"] == "incomplete" and f["default"] == "shared" and unsorted  # over 5% unsorted
    assert all(k not in s["diagrams"] for s in f["views"][1]["subjects"] for k in unsorted)  # never a guess
    held = FakeLLM()
    _, fams = _update(out, held, ask_again=False)  # `config set ask-again off`: kept as it is (RN-007)
    assert fams[fork]["ways"] == "incomplete" and not held.asked
    retry = FakeLLM()
    _, fams = _update(out, retry)  # an incomplete family is asked again
    assert fams[fork]["ways"] == "found" and retry.asked["subjects-assign"]


def test_batches_follow_packages(versions_tree):
    from cameo_ingest import subjects
    from cameo_ingest.state import State

    st = State(versions_tree)
    try:
        f = next(f for f in subjects.families(st, versions_tree) if len(f.items) >= subjects.MIN_ITEMS)
    finally:
        st.close()
    parts = subjects.batches(f)
    assert sorted(k for b in parts for k in b) == sorted(f.items)
    assert all(0 < len(b) <= subjects.BATCH for b in parts)
    by_pkg = Counter(f.items[k].package for k in f.items)
    for pkg, n in by_pkg.items():  # a package under a batch's size is never cut
        if n < subjects.BATCH:
            assert sum(1 for b in parts if any(f.items[k].package == pkg for k in b)) == 1, pkg


def test_a_run_writes_subjects(tmp_path, fake_chat, capsys):
    """`run` asks for the families' ways after building; an answer that can't be read is a failed
    proposal, so the fallback is shown first, and `status` says so (ADR-0031)."""
    from helpers import cli

    from cameo_ingest.evaluation.fiction import PROJECTS

    p = PROJECTS["pct"]()
    src = tmp_path / p.path
    src.write_bytes(p.mdzip())
    out = tmp_path / "out"
    assert cli([str(src), "-o", str(out), "--text-model", "acme/text", "--no-render", "--no-calibrate"]) == 0
    asked = [m for m in fake_chat[0].requests if "Propose 3 different ways" in json.dumps(m[1])]
    assert len(asked) == 1  # the fake's answer isn't JSON
    run = json.loads((out / "run.json").read_text())
    assert run["subjects"] == {"families": 1, "failed": 1, "topics": "too few models"}
    [rec] = json.loads((out / "subjects.json").read_text())["families"]
    assert rec["default"] == "shared" and rec["ways"] == "failed"
    capsys.readouterr()
    assert cli(["status", "-o", str(out)]) == 0
    assert "subjects: 1 family of versions (1 failed); a run asks again" in capsys.readouterr().out
