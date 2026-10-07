"""Splitting models into subjects (plan SB): version families, each diagram once, and every
candidate split covering every diagram."""

from collections import Counter

import pytest

pytest.importorskip("numpy")


def test_families_and_splits(tmp_path):
    from helpers import cli

    from cameo_ingest.evaluation.fiction import PROJECTS
    from cameo_ingest.evaluation.fiction.versions import VERSIONS
    from cameo_ingest.evaluation.subjects import SPLITS, families, measures, target

    projects = [PROJECTS[p]() for p in ("pct", "kois", "rwt", "hal", "aqu")]
    projects += [VERSIONS[v][1]() for v in ("kestrel-later", "port-calder-fork")]
    for p in projects:
        src = tmp_path / "in" / p.path
        src.parent.mkdir(parents=True, exist_ok=True)
        src.write_bytes(p.mdzip())
    out = tmp_path / "out"
    assert cli([str(tmp_path / "in"), "-o", str(out), "--no-llm", "--no-render"]) == 0

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
