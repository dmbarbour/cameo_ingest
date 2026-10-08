"""Type hierarchies for search (plan TH)."""

import json

from fixture_model import EXTERNAL, LAYOUT_EXTERNAL, MODEL_EXTERNAL, make_mdzip
from helpers import check_invariants, ingest, project_dir

from cameo_ingest import rootfiles
from cameo_ingest.state import State


def gen(key: str, general: str) -> str:
    target = f"<general href='{general}'/>" if "#" in general else ""
    attr = "" if "#" in general else f" general='{general}'"
    return f"<generalization xmi:type='uml:Generalization' xmi:id='g_{key}'{attr}>{target}</generalization>"


def kind(key: str, name: str, *generals: str, doc: str = "") -> str:
    comment = (f"<ownedComment xmi:type='uml:Comment' xmi:id='c_{key}' body='{doc}'>"
               f"<annotatedElement xmi:idref='{key}'/></ownedComment>") if doc else ""
    gens = "".join(gen(f"{key}{i}", g) for i, g in enumerate(generals))
    return f"<packagedElement xmi:type='uml:Class' xmi:id='{key}' name='{name}'>{comment}{gens}</packagedElement>\n"


KINDS = (kind("det", "Detector", doc="Senses vehicles at the stop line. It reports to the controller.")
         + kind("loop", "Loop Detector", "det", doc="An inductive loop cut into the road.")
         + kind("video", "Video Detector", "det")
         + kind("radar", "Radar Detector", "det")
         + kind("sensor", "Sensor")
         + kind("doppler", "Doppler Radar", "radar", "sensor")
         + kind("run1", "Calibration Run", "video") + kind("run2", "Calibration Run", "video")
         + kind("m1", "Hub Motor", "Lib.mdzip#_lib_motor") + kind("m2", "Wheel Motor", "Lib.mdzip#_lib_motor"))


def model() -> str:
    anchor = "<packagedElement xmi:type='uml:Class' xmi:id='b2' name='Battery'/>"
    assert MODEL_EXTERNAL.count(anchor) == 1
    return MODEL_EXTERNAL.replace(anchor, anchor + "\n" + KINDS)


def test_hierarchies(tmp_path):
    """Each kind once, under its first general, level by level, with its kind word and the first
    sentence of its documentation; a second general named; alike leaves on one line; a general
    outside the project roots the kinds that specialize it; chunks unless a developer leaves them out."""
    out = ingest(tmp_path, ("drone.mdzip", make_mdzip(model(), LAYOUT_EXTERNAL, EXTERNAL)))
    check_invariants(out)
    proj = project_dir(out)
    page = (proj / "HIERARCHIES.md").read_text()
    assert "## kinds of Detector, in drone [" in page and "], 7 kinds, 2 levels" in page
    lines = page.split("## kinds of Detector")[1].split("##")[0].splitlines()
    tree = [ln.split(" [")[0] + (ln.split("]", 1)[1] if "]" in ln else "") for ln in lines if ln.lstrip().startswith("- ")]
    assert tree == [
        "- Detector (Class): Senses vehicles at the stop line.",
        "  - Loop Detector (Class): An inductive loop cut into the road.",
        "  - Radar Detector (Class)",
        "    - Doppler Radar (Class); also a kind of Sensor",
        "  - Video Detector (Class)",
        "    - Calibration Run (Class) (2 kinds of this name)"], tree
    assert "## kinds of Brushless Motor (outside this project), in drone [" in page and "2 kinds, 1 level" in page
    assert "kinds of Sensor" not in page  # two kinds only: Sensor and Doppler Radar
    records = [json.loads(line) for line in (proj / "index/hierarchies.jsonl").open()]
    assert {r["title"] for r in records} == {"Detector", "Brushless Motor (outside this project)"}

    chunks = [json.loads(line) for line in (out / "chunks.jsonl").open()]
    [det] = [c for c in chunks if c["metadata"]["kind"] == "index:hierarchy" and "kinds of Detector" in c["text"]]
    assert det["text"].startswith("Hierarchy: kinds of Detector, in drone [")
    assert "- Doppler Radar (Class); also a kind of Sensor" in det["text"] and "[" not in det["text"].split("\n", 1)[1]
    assert det["metadata"]["element_id"] == "det" and "doppler" in det["metadata"]["element_ids"]

    state = State(out)
    rootfiles.rebuild(state, out, rootfiles.Assembly(hierarchies=False))  # as scripts/assemble_tree.py does
    state.close()
    assert not any(json.loads(line)["metadata"]["kind"] == "index:hierarchy" for line in (out / "chunks.jsonl").open())
    assert (proj / "HIERARCHIES.md").is_file()  # the page, either way
