"""The fictional projects (plan RE-10): they ingest, and their answer keys hold in the output."""

import json

import pytest

from cameo_ingest.cli import main
from cameo_ingest.evaluation.fiction import PROJECTS
from cameo_ingest.evaluation.synthetic import holds

# Kinds that may quote a fact without being about it: listings, summaries, diagrams.
QUOTING = ("ledger", "generated", "project", "diagram", "package")


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
