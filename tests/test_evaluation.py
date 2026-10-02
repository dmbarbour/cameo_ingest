"""The retrieval evaluation's building blocks (plan RE), offline."""

import re

import pytest

from cameo_ingest.evaluation.windows import windows_by_offsets


def words(text: str) -> list[tuple[int, int]]:
    """A stand-in tokenizer: one token per word."""
    return [m.span() for m in re.finditer(r"\S+", text)]


def test_windows_overlap_and_cover_the_text():
    text = " ".join(f"w{i}" for i in range(25))
    out = windows_by_offsets(text, words(text), size=12, overlap=3)  # 10 words per window
    assert out[0] == " ".join(f"w{i}" for i in range(10))
    assert out[1].startswith("w7 w8 w9 w10")  # 3 words of overlap
    assert out[-1].endswith("w24")
    assert all(len(words(w)) <= 10 for w in out)
    assert windows_by_offsets("short text", words("short text"), size=12, overlap=3) == ["short text"]
    with pytest.raises(ValueError):
        windows_by_offsets(text, words(text), size=12, overlap=10)


def test_synthetic_project_answers_its_questions(tmp_path):
    """Each question of the synthetic project is answered, in the output, by a chunk of one of
    its answer elements that holds the planted fact: the answer key can't drift."""
    import json

    from cameo_ingest.cli import main
    from cameo_ingest.evaluation.grading import holds
    from cameo_ingest.evaluation.synthetic import QUESTIONS, make_mdzip

    src = tmp_path / "kois.mdzip"
    src.write_bytes(make_mdzip())
    assert main([str(src), "-o", str(tmp_path / "out"), "--no-llm", "--no-render"]) == 0
    chunks = [json.loads(line) for line in (tmp_path / "out" / "chunks.jsonl").open()]
    assert len({q["fact"] for q in QUESTIONS}) == 14 and len(QUESTIONS) == 28
    for q in QUESTIONS:
        texts = [c["text"] for c in chunks if c["metadata"].get("element_id") in q["answers"]]
        assert any(holds(q["evidence"], t) for t in texts), (q["id"], q["evidence"])


def test_grading_rules():
    """Each rule of grading by construction, on hand-made windows (AR-005)."""
    from collections import namedtuple

    from cameo_ingest.evaluation.grading import Corpus, Question, holds

    W = namedtuple("W", "id text element_id kind")
    c = Corpus([
        W("c1#w0", "Block Pump: lifts **4,500** cubic metres", "_fic_pump", "element"),
        W("c1#w1", "Block Pump, details: members", "_fic_pump", "element:details"),
        W("c2", "Ledger: Pump — 4,500 cubic metres", "_fic_led", "ledger"),
        W("c3", "Index: FIC-1, in 2 models: 4,500 cubic metres", None, "index:id"),
        W("c4", "Block Tank", "_fic_tank", "element"),
        W("c5", "Another project's 4,500 cubic metres", "_oth_x", "element"),
        W("c6", "[Valve](p.md#v) closes in 340 ms\n<sub>trace: `x`</sub>", "_kois_v", "element"),
    ])
    fact = {"id": "f", "question": "?", "rule": "fact", "prefix": "_fic_", "evidence": ["4,500 cubic metres"],
            "answers": ["_fic_pump"], "related": ["_fic_tank"]}
    # Only windows of the project (or index entries) that hold the fact answer.
    assert Question.of(fact).grades(c) == {0: 2, 1: 1, 2: 2, 3: 2, 4: 1}
    # The judge panel overrides construction where it judged.
    assert Question.of(fact).grades(c, {"c2": 0, "c4": 2}) == {0: 2, 1: 1, 3: 2, 4: 2}
    # Any window of an answering element answers; in a project with planted facts, so does one holding it.
    assert Question.of({**fact, "rule": "element", "prefix": ""}).grades(c) == {0: 2, 1: 2, 4: 1}
    kois = {"id": "k", "question": "?", "rule": "element", "prefix": "_kois_", "answers": ["_kois_k"],
            "evidence": ["Valve closes in 340 ms"]}
    assert Question.of(kois).grades(c) == {6: 2}
    # A written question: its source chunk, the window with the quote first; else its element's chunks.
    written = {"id": "w", "question": "?", "answer_chunks": ["c1"], "quote": "lifts 4,500 cubic metres",
               "source_element": "_fic_pump"}
    assert Question.of(written).rule == "source" and Question.of(written).grades(c) == {0: 2, 1: 1}
    assert Question.of({**written, "answer_chunks": ["elsewhere"]}).grades(c) == {0: 2, 1: 1}
    # An answer in parts: any part answers; coverage counts the parts each window holds.
    parts = Question.of({"id": "p", "question": "?", "evidence_groups": [["4,500 cubic metres"], ["closes in 340 ms"]]})
    g = parts.grades(c)
    assert parts.rule == "parts" and g == {0: 2, 2: 2, 3: 2, 5: 2, 6: 2}
    n, covers = parts.covers(c, g)
    assert n == 2 and covers[0] == {0} and covers[6] == {1}
    assert Question.of(fact).covers(c, Question.of(fact).grades(c)) == (1, {0: {0}, 2: {0}, 3: {0}})
    for bad in ({"evidence_groups": [["x"], []]}, {"rule": "vibes", "answers": ["a"]}, {"rule": "fact", "answers": ["a"]}):
        with pytest.raises(ValueError):
            Question.of({"id": "b", "question": "?", **bad})
    assert holds(["headLossLimit = 2.4"], "**headLossLimit** = `2.4`")
    assert holds([["derives from X", "UV Dose"]], "Thread: what derives from X\n- UV Dose (P-4)")
    assert not holds([["derives from X", "UV Dose"]], "Thread: what derives from Y\n- UV Dose (P-4)")


def test_evaluation_extra(monkeypatch):
    """Without the eval extra, the evaluation says how to install it; grading needs none of it
    (plan RA-04)."""
    import sys

    monkeypatch.setitem(sys.modules, "numpy", None)  # as if not installed
    monkeypatch.delitem(sys.modules, "cameo_ingest.evaluation.harness", raising=False)
    with pytest.raises(ImportError, match=r'install "cameo-ingest\[eval\]"'):
        import cameo_ingest.evaluation.harness
    monkeypatch.delitem(sys.modules, "cameo_ingest.evaluation.grading", raising=False)
    import cameo_ingest.evaluation.grading  # noqa: F401


def test_search_and_measures():
    """BM25 ranks the document with the query's rare words first; fusion keeps what both
    rankings agree on; the measures read graded relevance (plan RE-05)."""
    pytest.importorskip("numpy")  # the eval extra
    from cameo_ingest.evaluation.harness import BM25, fuse, mean_ci, measures, top

    docs = ["the brine valve closes in 340 ms", "the pump station has two pumps", "the valve and the pump"]
    bm = BM25(docs)
    assert top(bm.scores("how fast does the brine valve close"), 3)[0] == 0
    assert fuse([[0, 1, 2], [1, 0, 2]])[:2] in ([0, 1], [1, 0]) and fuse([[2, 0], [2, 1]])[0] == 2
    m = measures([5, 3, 7], {3: 2, 7: 1})
    assert m["hit@1"] == 0 and m["hit@5"] == 1 and m["mrr@10"] == 0.5 and 0 < m["ndcg@10"] < 1
    assert measures([3], {3: 2})["ndcg@10"] == 1.0
    mean, lo, hi = mean_ci([0.0, 1.0, 1.0, 1.0])
    assert mean == 0.75 and lo <= mean <= hi


def test_panel_consensus():
    """Two judges' grade where they agree; the tie-breaker's where they don't, or the lower."""
    from cameo_ingest.evaluation.judge import consensus, kappa

    js = [{"set": "s", "qid": q, "unit": "u", "judge": j, "grade": g}
          for q, j, g in [("q1", "A", 2), ("q1", "B", 2), ("q2", "A", 2), ("q2", "B", 0), ("q2", "C", 1),
                          ("q3", "A", 1), ("q3", "B", 2), ("q4", "A", 0)]]
    assert consensus(js, ("A", "B"), "C") == {("s", "q1", "u"): 2, ("s", "q2", "u"): 1, ("s", "q3", "u"): 1,
                                              ("s", "q4", "u"): 0}
    assert kappa([0, 1, 2, 2], [0, 1, 2, 2]) == 1.0 and kappa([0, 0], [1, 1]) == 0.0


def test_rag_units(fiction_tree):
    """A tree as rag/ presents it: one unit per file, its text ending with the source line, its
    id, element and kind those of a chunk in chunks.jsonl (plan RA-19)."""
    pytest.importorskip("numpy")  # the eval extra
    import json

    from cameo_ingest.evaluation.harness import rag_units

    chunks = {c["id"]: c for c in map(json.loads, (fiction_tree / "chunks.jsonl").open())}
    units = rag_units(fiction_tree)
    assert len(units) == len(list((fiction_tree / "rag" / "text").rglob("*.txt")))
    for u in units:
        c = chunks[u.id]
        assert (u.kind, u.element_id) == (c["metadata"]["kind"], c["metadata"].get("element_id"))
        assert u.text.startswith(c["text"].rstrip()) and "\n\nSource: " in u.text
