"""The public sample models (scripts/fetch_samples.py); the large ones with `pytest -m slow`."""

import hashlib
import json
from pathlib import Path

import pytest
from helpers import (
    SAMPLES_DIR,
    check_invariants,
    provenance,
)

from cameo_ingest.cli import main

SAMPLES = sorted(SAMPLES_DIR.glob("*.mdzip")) + sorted(SAMPLES_DIR.glob("resource_bundles/*.zip"))


SMALL = 5_000_000  # larger samples only run with `pytest -m slow`


SAF_CONTENTS = 8  # the .mdzip files in the SAF_Plugin bundle; the standalone copies add none


# Counts that changed when BASE-001, BASE-003 and BASE-013 were fixed; a change is a regression
# or a deliberate improvement, to be checked either way (BASE-007R2).
PINNED = {
    "Package_Delivery_Drone.mdzip": {
        "summary": {"elements": 839, "diagrams": 11, "stereotype_applications": 238, "relationships": 281,
                    "requirements": 42},
        "table_configs": 0, "computed_tables": 1, "matrices": 1, "diagrams_with_shapes": 9, "tables_with_rows": 0,
    },
    "TMT.mdzip": {  # slow
        "summary": {"elements": 71093, "diagrams": 1346, "stereotype_applications": 22551, "relationships": 7947,
                    "requirements": 4284},
        # Tables computed (plan CT); the configuration of tables, matrices and maps not computed; those with a
        # row list but no columns, as saved (BASE-013).
        "table_configs": 64, "computed_tables": 37, "matrices": 4, "diagrams_with_shapes": 1171, "tables_with_rows": 3,
    },
}


@pytest.mark.parametrize("sample", [
    pytest.param(s, id=s.name, marks=() if s.stat().st_size < SMALL else pytest.mark.slow) for s in SAMPLES])
def test_samples(tmp_path, sample):
    out = tmp_path / "out"
    assert main([str(sample), "-o", str(out), "--no-llm", "--no-render"]) == 0
    check_invariants(out)
    expected = PINNED.get(sample.name)
    if expected:
        summary = json.loads((out / "manifest.json").read_text())["projects"][0]["summary"]
        assert {k: summary[k] for k in expected["summary"]} == expected["summary"]
        pages = [p.read_text(encoding="utf-8") for p in out.glob("by-sha256/*/diagrams/*.md")]
        assert sum("**Table / matrix configuration**" in p for p in pages) == expected["table_configs"]
        assert sum("**Rows (" in p for p in pages) == expected["computed_tables"]  # plan CT
        assert sum("**Matrix:**" in p for p in pages) == expected["matrices"]  # described, not computed
        assert sum("**Shapes (" in p for p in pages) == expected["diagrams_with_shapes"]
        assert sum("**Elements shown when last saved (" in p for p in pages) == expected["tables_with_rows"]
        check_edge_directions(sample)
        check_sketches(sample)


def check_edge_directions(sample: Path) -> None:
    """Every drawn edge that shows a model relationship between the shapes (or pins) at its
    ends runs from the relationship's source to its target (FU-001)."""
    from cameo_ingest import diagram_graph as dg
    from cameo_ingest import semantics as sem
    from cameo_ingest.archive import discover
    from cameo_ingest.pipeline import load_layouts, parse_project

    proj = next(discover(sample.read_bytes(), sample.name))
    ix = parse_project(proj)
    rels = {r.id: r for r in sem.relationships(ix)}
    flows = sem.item_flows(ix)
    checked = 0
    for layout in load_layouts(proj, ix).values():
        for lk in dg.build(ix, layout, rels, flows).links:
            rel = rels.get(lk.view.element or "")
            if rel is None or not lk.directed or lk.source is None or lk.target is None:
                continue
            ends = (lk.source.element, lk.target.element)
            if {rel.source, rel.target} == set(ends):
                assert ends == (rel.source, rel.target), (rel.metaclass, lk.view.view_id)
                checked += 1
    assert checked


def check_sketches(sample: Path) -> None:
    """Every diagram can be drawn (FU-016), as PNG and as well-formed SVG whose shapes name their
    elements (KX-05), and every large one split into modules that each can be drawn, covering all
    its shapes once (plan DV)."""
    from xml.etree import ElementTree

    from cameo_ingest import diagram_graph as dg
    from cameo_ingest import semantics as sem
    from cameo_ingest import sketch
    from cameo_ingest.archive import discover
    from cameo_ingest.partition import partition
    from cameo_ingest.pipeline import load_layouts, parse_project
    from cameo_ingest.sketch_svg import render_svg

    proj = next(discover(sample.read_bytes(), sample.name))
    ix = parse_project(proj)
    rels = {r.id: r for r in sem.relationships(ix)}
    flows = sem.item_flows(ix)
    split = 0
    for dia_id, layout in load_layouts(proj, ix).items():
        g = dg.build(ix, layout, rels, flows)
        sketch.render_png(ix, g, dia_id)
        svg = render_svg(ix, g, dia_id)
        if svg is not None:
            keys = {e.get("data-k") for e in ElementTree.fromstring(svg).iter("{http://www.w3.org/2000/svg}g")}
            assert keys >= {n.view.element for n in g.nodes if n.view.rect and n.view.element}, dia_id
        part = partition(g)
        if part is None:
            continue
        split += 1
        assert sorted(k for m in part.modules for k in m.shapes) == [n.num for n in g.nodes], dia_id
        assert sketch.overview_png(ix, part, dia_id)
        assert all(sketch.module_png(ix, part, m.num, dia_id) for m in part.modules)
    assert split


SAF = [SAMPLES_DIR / "resource_bundles/SAF_Plugin_2026-09-16.zip",
       *(SAMPLES_DIR / n for n in ("SAF_FFDS.mdzip", "SAF_Blank.mdzip", "SAF_Profile.mdzip"))]


@pytest.mark.slow
@pytest.mark.skipif(not all(p.exists() for p in SAF), reason="samples not fetched (scripts/fetch_samples.py)")
def test_bundle_and_standalone_copies_share_projects(tmp_path):
    """BASE-017's evidence: three standalone samples are byte-identical to members of the
    SAF_Plugin bundle. Each is one project, seen twice."""
    out = tmp_path / "out"
    assert main([*map(str, SAF), "-o", str(out), "--no-llm", "--no-render"]) == 0
    check_invariants(out)
    records = provenance(out)
    for f in SAF[1:]:
        paths = [s["path"] for s in records[f"sha256:{hashlib.sha256(f.read_bytes()).hexdigest()}"]["sightings"]]
        assert sorted(Path(p).name for p in paths) == sorted([f.name, SAF[0].name])
    assert len(records) == len(list((out / "by-sha256").glob("[0-9a-f]*"))) == SAF_CONTENTS


@pytest.mark.slow
@pytest.mark.skipif(not (SAMPLES_DIR / "TMT.mdzip").exists(), reason="samples not fetched (scripts/fetch_samples.py)")
def test_versions_among_the_samples(tmp_path, capsys):
    """Among all the samples, `groups` finds one group, TMT and TMT-2024x (different project ids,
    88% of their element ids shared), newest first (plan PV)."""
    out = tmp_path / "out"
    assert main(["add", "-o", str(out), str(SAMPLES_DIR)]) == 0
    assert main(["scan", "-o", str(out)]) == 0
    capsys.readouterr()
    assert main(["groups", "-o", str(out)]) == 0
    report = capsys.readouterr().out
    assert "1 group(s) of likely versions" in report and "## Related" not in report
    group = report.split("## Group 1: ")[1]
    assert group.startswith("TMT-2024x.mdzip") and group.index("TMT-2024x.mdzip") < group.index("| TMT.mdzip")
    assert "98% shared" in group and "Check:" not in group
