"""The fictional projects (plan RE-10): they ingest, and their answer keys hold in the output."""

import json

import pytest

from cameo_ingest.cli import main
from cameo_ingest.evaluation.fiction import PROJECTS
from cameo_ingest.evaluation.synthetic import holds

# Kinds that may quote a fact without being about it: listings, summaries, diagrams.
QUOTING = ("ledger", "generated", "project", "diagram", "package", "index", "trace")


@pytest.mark.parametrize("prefix", sorted(PROJECTS))
@pytest.mark.parametrize("style", ["plain", "markdown"])
def test_answer_key_holds(tmp_path, prefix, style):
    """Each question's evidence is in a chunk of an answering element (in both chunk styles),
    and in no chunk of an element that neither answers nor relates to it, so that grading by
    construction credits only the right windows."""
    project = PROJECTS[prefix]()
    src = tmp_path / project.file_name
    src.write_bytes(project.mdzip())
    assert project.mdzip() == src.read_bytes()  # the same bytes every time: the same project token
    out = tmp_path / "out"
    assert main([str(src), "-o", str(out), "--no-llm", "--no-render", "--chunk-style", style]) == 0
    chunks = [json.loads(line) for line in (out / "chunks.jsonl").open()]
    questions = project.questions()
    assert len({q["id"] for q in questions}) == len(questions)
    for q in questions:
        per = q["evidence_by_element"]
        answering = [c for c in chunks if c["metadata"].get("element_id") in q["answers"]
                     and (holds(q["evidence"], c["text"]) or holds(per.get(c["metadata"]["element_id"], []), c["text"]))]
        assert answering, (q["id"], q["evidence"], per)
        for element, phrases in per.items():
            assert any(holds(phrases, c["text"]) for c in chunks if c["metadata"].get("element_id") == element), \
                (q["id"], element)
        strays = [c["title"] for c in chunks if holds(q["evidence"], c["text"])
                  and c["metadata"].get("element_id") not in q["answers"] + q["related"]
                  and not c["metadata"]["kind"].startswith(QUOTING)]
        assert not strays, (q["id"], strays)


def test_fiction_renders_what_cameo_models_hold(tmp_path):
    """What the fiction exercises reads in full on the pages: a transition's trigger and guard,
    a flow's guard, a note on what it annotates, an unnamed requirement by its id and text."""
    project = PROJECTS["rwt"]()
    src = tmp_path / project.file_name
    src.write_bytes(project.mdzip())
    out = tmp_path / "out"
    assert main([str(src), "-o", str(out), "--no-llm", "--no-render"]) == 0
    pages = "\n".join(p.read_text() for p in out.glob("by-sha256/*/packages/*.md"))
    assert "Transition: Awaiting Backwash → Backwashing — Backwash Permit" in pages
    assert "Filtering → Awaiting Backwash — \\[head loss above 2.4 m" in pages
    assert "— \\[residual below 0.8 mg/L\\]" in pages
    assert "Verify: verifies [RWT-REG-002: The works shall" in pages
    assert "(Class)" not in pages
    crossing = PROJECTS["fvx"]()
    src = tmp_path / crossing.file_name
    src.write_bytes(crossing.mdzip())
    assert main([str(src), "-o", str(tmp_path / "fvx"), "--no-llm", "--no-render"]) == 0
    chunk = next(c for c in map(json.loads, (tmp_path / "fvx" / "chunks.jsonl").open())
                 if c["metadata"].get("element_id") == "_fvx_audio_b")
    assert "Notes:\n- Willow Lane: under the noise agreement" in chunk["text"]


def test_questions_across_the_rival_proposals(tmp_path):
    """The three Riverbend proposals share a file name, in different folders. Each question across
    them has a part of its answer in each model, and the index across models (CROSSREF.md, index:id
    chunks) gathers the parts of an id-led question in one entry."""
    from cameo_ingest.evaluation.fiction import ACROSS

    srcs = []
    for prefix in ("rwt", "hal", "aqu", "fvx"):
        project = PROJECTS[prefix]()
        src = tmp_path / "in" / project.path
        src.parent.mkdir(parents=True, exist_ok=True)
        src.write_bytes(project.mdzip())
        srcs.append(str(src))
    out = tmp_path / "out"
    assert main([*srcs, "-o", str(out), "--no-llm", "--no-render"]) == 0
    chunks = [json.loads(line) for line in (out / "chunks.jsonl").open()]
    names = {c["metadata"]["content"]: c["metadata"]["project"] for c in chunks if c["metadata"].get("project")}
    assert list(names.values()).count("Riverbend_Water_Treatment_Works.mdzip") == 3  # three projects, one file name
    for q in ACROSS():
        for group in q["evidence_groups"]:
            assert any(holds(group, c["text"]) for c in chunks if c["metadata"]["kind"] != "index:id"), (q["id"], group)
    entry = [c for c in chunks if c["metadata"]["kind"] == "index:id" and c["metadata"]["term"] == "RWT-REG-003"]
    q = next(q for q in ACROSS() if q["id"] == "across-x02-literal")
    assert entry and all(any(holds(g, c["text"]) for c in entry) for g in q["evidence_groups"])
    assert "## RWT-REG-003, in 3 models" in (out / "CROSSREF.md").read_text()
    # A thread holds an answer along a derivation, whole: here, Halvorsen's requirement and its test.
    q = next(q for q in ACROSS() if q["id"] == "within-w03-literal")
    threads = [c for c in chunks if c["metadata"]["kind"] == "trace:thread"]
    assert any(all(holds(g, c["text"]) for g in q["evidence_groups"]) for c in threads)
