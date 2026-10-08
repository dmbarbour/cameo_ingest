"""The fictional projects (plan RE-10): they ingest, and their answer keys hold in the output."""

import hashlib
import json

import pytest

from cameo_ingest.evaluation.fiction import PROJECTS
from cameo_ingest.evaluation.grading import Corpus, Question, holds

# Kinds that may quote a fact without being about it: listings, summaries, diagrams.
QUOTING = ("ledger", "generated", "project", "diagram", "package", "index", "trace")


def chunks_of(tree) -> list[dict]:
    return [json.loads(line) for line in (tree / "chunks.jsonl").open()]


def project_of(tree, project):
    """The fictional project's directory in the tree, by its content (three share a file name)."""
    return tree / "by-sha256" / hashlib.sha256(project.mdzip()).hexdigest()


class W:
    """A chunk as a window to grade."""

    def __init__(self, c: dict):
        self.id, self.text, self.kind = c["id"], c["text"], c["metadata"]["kind"]
        self.element_id = c["metadata"].get("element_id")


@pytest.mark.parametrize("prefix", sorted(PROJECTS))
def test_answer_key_holds(fiction_tree, prefix):
    """Each question's evidence is in a chunk of an answering element, and in no chunk of an
    element that neither answers nor relates to it, so that grading by construction credits only
    the right windows."""
    project = PROJECTS[prefix]()
    assert project.mdzip() == PROJECTS[prefix]().mdzip()  # the same bytes every time: the same project token
    chunks = chunks_of(fiction_tree)
    questions = project.questions()
    assert len({q["id"] for q in questions}) == len(questions)
    windows = [W(c) for c in chunks]
    corpus = Corpus(windows)
    for q in questions:
        per = q["evidence_by_element"]
        grades = Question.of(q).grades(corpus)  # as the evaluation grades it (AR-005)
        answering = [i for i, g in grades.items() if g == 2 and windows[i].element_id in q["answers"]]
        assert answering, (q["id"], q["evidence"], per)
        for element, phrases in per.items():
            assert any(corpus.holds(phrases, i) for i, w in enumerate(windows) if w.element_id == element), \
                (q["id"], element)
        strays = [chunks[i]["title"] for i, g in grades.items() if g == 2
                  and windows[i].element_id not in q["answers"] + q["related"] and not windows[i].kind.startswith(QUOTING)]
        assert not strays, (q["id"], strays)


def test_fiction_renders_what_cameo_models_hold(fiction_tree):
    """What the fiction exercises reads in full on the pages: a transition's trigger and guard,
    a flow's guard, a note on what it annotates, an unnamed requirement by its id and text."""
    pages = "\n".join(p.read_text() for p in project_of(fiction_tree, PROJECTS["rwt"]()).glob("packages/*.md"))
    assert "Transition: Awaiting Backwash → Backwashing — Backwash Permit" in pages
    assert "Filtering → Awaiting Backwash — \\[head loss above 2.4 m" in pages
    assert "— \\[residual below 0.8 mg/L\\]" in pages
    assert "Verify: verifies [RWT-REG-002: The works shall" in pages
    assert "(Class)" not in pages
    # A DOORS import's id once: the id in its text, and the Id tag as a database number (AR-010R3).
    assert "- **Requirement ID:** RWT-REG-001\n- **Database number:** 16001" in pages
    ledger = (project_of(fiction_tree, PROJECTS["rwt"]()) / "LEDGER.md").read_text()
    assert "- [RWT-REG-001](" in ledger and "(database number: 16001;" in ledger and "**16001**" not in ledger
    chunk = next(c for c in chunks_of(fiction_tree) if c["metadata"].get("element_id") == "_fvx_audio_b"
                 and c["metadata"]["kind"] == "element")
    assert "Notes:\n- Willow Lane: under the noise agreement" in chunk["text"]


def test_questions_across_the_rival_proposals(fiction_tree):
    """The three Riverbend proposals share a file name, in different folders. Each question across
    them has a part of its answer in each model, and the index across models (CROSSREF.md, index:id
    chunks) gathers the parts of an id-led question in one entry."""
    from cameo_ingest.evaluation.fiction import ACROSS

    out = fiction_tree
    chunks = chunks_of(out)
    names = {c["metadata"]["content"]: c["metadata"]["project"] for c in chunks if c["metadata"].get("project")}
    assert list(names.values()).count("Riverbend_Water_Treatment_Works.mdzip") == 3  # three projects, one file name
    corpus = Corpus([W(c) for c in chunks])  # each chunk's text flattened once (CQ-022)
    for q in ACROSS():
        for k, group in enumerate(q["evidence_groups"]):
            held = [i for i in range(len(chunks)) if corpus.holds(group, i)]
            assert any(chunks[i]["metadata"]["kind"] != "index:id" for i in held), (q["id"], group)
            if "group_elements" not in q:
                continue
            # A part is a relationship: held by a chunk of an element it relates, and by no other
            # element's chunk (AR-006).
            elements = q["group_elements"][k]
            assert any(chunks[i]["metadata"].get("element_id") in elements for i in held), (q["id"], k)
            strays = [chunks[i]["title"] for i in held if not chunks[i]["metadata"]["kind"].startswith(QUOTING)
                      and chunks[i]["metadata"].get("element_id") not in elements]
            assert not strays, (q["id"], k, strays)
    entry = [c for c in chunks if c["metadata"]["kind"] == "index:id" and c["metadata"]["term"] == "RWT-REG-003"]
    q = next(q for q in ACROSS() if q["id"] == "across-x02-literal")
    assert entry and all(any(holds(g, c["text"]) for c in entry) for g in q["evidence_groups"])
    assert "## RWT-REG-003, in 3 models" in (out / "CROSSREF.md").read_text()
    # A thread holds an answer along a derivation, whole: here, Halvorsen's requirement and its test.
    q = next(q for q in ACROSS() if q["id"] == "within-w03-literal")
    threads = [c for c in chunks if c["metadata"]["kind"] == "trace:thread"]
    assert any(all(holds(g, c["text"]) for g in q["evidence_groups"]) for c in threads)


def test_threads_live_with_their_project(fiction_tree):
    """A project's threads are made with it (THREADS.md, index/threads.jsonl) and, the tree's
    setting on, join its chunks and its rag/ folder, not the tree's (AR-014R2). A part after the
    first starts with its first line's ancestors, so that it says what its lines derive from
    (AR-027R2)."""
    crossing = project_of(fiction_tree, PROJECTS["fvx"]())
    assert (crossing / "THREADS.md").is_file() and (crossing / "index" / "threads.jsonl").read_text()
    threads = [c for c in chunks_of(fiction_tree) if c["metadata"]["kind"] == "trace:thread"
               and c["metadata"]["content"] == f"sha256:{crossing.name}"]
    assert threads and all(c["metadata"]["file"].startswith(f"by-sha256/{crossing.name}/THREADS.md#thread-")
                           for c in threads)
    folder = next(d for d in (fiction_tree / "rag" / "meta").iterdir() if d.name.endswith(crossing.name[:8]))
    in_folder = {json.loads(m.read_text())["chunk_id"] for m in folder.glob("*.json")}
    assert {c["id"] for c in threads} <= in_folder
    parts = [c for c in threads if c["metadata"].get("parts", 1) > 1 and c["metadata"]["part"] > 1]
    assert parts, "a thread long enough to split"
    for c in parts:
        body = c["text"].split("\n\n", 1)[1]
        assert body.startswith("- ") and body.splitlines()[0].endswith(" (continued)"), body[:200]


def test_where_questions(fiction_tree):
    """Each question about where something is described (plan GS-04) is answered by chunks of
    its behavior or package and its diagram, which grading credits, and by nothing else."""
    from cameo_ingest.evaluation.fiction import where

    chunks = chunks_of(fiction_tree)
    windows = [W(c) for c in chunks]
    corpus = Corpus(windows)
    questions = where()
    assert len({q["id"] for q in questions}) == len(questions) == 12
    for q in questions:
        grades = Question.of(q).grades(corpus)
        assert {windows[i].element_id for i, g in grades.items() if g == 2} == set(q["answers"]), q["id"]
        assert {windows[i].element_id for i, g in grades.items() if g == 1} == set(q["related"]), q["id"]
