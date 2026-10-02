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


def test_search_and_measures():
    """BM25 ranks the document with the query's rare words first; fusion keeps what both
    rankings agree on; the measures read graded relevance (plan RE-05)."""
    pytest.importorskip("numpy")  # the optional eval group
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


def test_plain_chunk_text():
    """The plain chunk style (plan RE-08): links to labels, no traces or marks, meaning before
    details (apart when long), parts that repeat their heading, readable requirement titles."""
    from cameo_ingest import plain as pl
    from cameo_ingest.text import requirement_title

    md = ("## «Requirement» (unnamed)\n\n- **Kind:** Class\n- **Qualified name:** `M::P::Q::R`\n"
          "- **Requirement ID:** 16890\n\n**Requirement text:**\n\n> [REQ-1-OAD-0468] Tip/tilt error budget\n\n"
          "**Tagged values:**\n- «TMT_Requirement» Rationale = \\[CR163\\] latest results\n\n"
          "**Relationships:**\n- Satisfy: [Drone](../p.md#drone-b1) satisfies this\n\n"
          "<sub>trace: `sha256:x!e#r@L1`</sub>\n")
    meaning, details = pl.section(md, "Requirement X in P (project p)")
    assert meaning == [("Requirement X in P (project p)\n\nRequirement ID: 16890\n"
                       "Requirement text: [REQ-1-OAD-0468] Tip/tilt error budget\n"
                       "Relationships:\n- Satisfy: Drone satisfies this\n"
                       "Tagged values:\n- «TMT_Requirement» Rationale = [CR163] latest results")] and not details
    long_values = md.replace("latest results", "latest results " + "word " * 250 + "\n- Note = " + "word " * 250)
    meaning, details = pl.section(long_values, "Requirement X in P (project p)")
    assert meaning[0].endswith("Drone satisfies this") and len(details) == 2
    assert details[0].startswith("Requirement X in P (project p), details (part 1 of 2)\n\nTagged values:\n")
    # Parts are budgeted in estimated tokens: ids make more tokens per character than prose.
    assert pl.tokens("The pump lifts water.") < pl.tokens("_2021x_2_1b400495_1742239490487") < 40
    assert requirement_title(None, "16890", "[REQ-1-OAD-0468] Tip/tilt error budget") == \
        "REQ-1-OAD-0468: Tip/tilt error budget"
    assert requirement_title("Endurance", "R-1", "The drone shall fly.") == "Endurance (R-1)"
    assert pl.where("A::B::C::D", "x.mdzip") == "in B::C::D (project x.mdzip)"
    long = pl.parts("H", "\n".join(f"line {i} " + "word " * 20 for i in range(40)), budget=300)
    assert len(long) > 2 and all(p.startswith("H (part ") and pl.tokens(p) <= 300 for p in long)
    cut = pl.parts("H", "x" * 3000, budget=300)  # a line too long for any part is cut into parts that fit
    assert len(cut) > 1 and all(pl.tokens(p) <= 300 for p in cut) and sum(p.count("x") for p in cut) == 3000
    nested = pl.parts("H", "- root\n" + "\n".join(f"  - child {i} " + "word " * 20 for i in range(12)), budget=150)
    assert len(nested) > 2 and all(p.split("\n\n", 1)[1].startswith("  - child") for p in nested[1:])  # nesting kept
    # Only emit's markup goes; model text keeps its operators, quotes and '#' lines (AR-003).
    md = ("### Constraint Mass\n\n- **Kind:** Constraint\n\n**Documentation:**\n\n#1 priority is safety.\n"
          "> 5 bar: trip\nx**2 + y**2 < r**2\n\n**Requirement text:**\n\n> > 5 bar: trip\n\n"
          "**Specification (OCL2.0):**\n\n```\nself.mass <= 2 * self.tare * 1.5\n```\n\n"
          "**Members:**\n- *part* Property **pump\\*2** : [Pump](p.md#pump)\n\n"
          "**Table / matrix configuration** (rows are computed by Cameo):\n- «DiagramTable» scope = P\n\n"
          "**Summary** _(rule-based; not part of the source model)_:\n\nIt weighs *little*.\n")
    header, bs = pl.blocks(md)
    assert header == ["- **Kind:** Constraint"]
    assert [n for n, _ in bs] == ["Documentation", "Requirement text", "Specification (OCL2.0)", "Members",
                                  "Table / matrix configuration", "Summary"], bs
    meaning, _ = pl.section(md, "Constraint Mass (project p)")
    assert meaning == [("Constraint Mass (project p)\n\nDocumentation:\n#1 priority is safety.\n> 5 bar: trip\n"
                        "x**2 + y**2 < r**2\nRequirement text: > 5 bar: trip\n"
                        "Specification (OCL2.0): self.mass <= 2 * self.tare * 1.5\n"
                        "Table / matrix configuration:\n- «DiagramTable» scope = P\nSummary: It weighs *little*.\n"
                        "Members:\n- part Property pump*2 : Pump")], meaning
    assert pl.plain("- **16001** [R-1](l.md#r) — “a * b * c”") == "- 16001 R-1 — “a * b * c”"


def test_panel_consensus():
    """Two judges' grade where they agree; the tie-breaker's where they don't, or the lower."""
    from cameo_ingest.evaluation.judge import consensus, kappa

    js = [{"set": "s", "qid": q, "unit": "u", "judge": j, "grade": g}
          for q, j, g in [("q1", "A", 2), ("q1", "B", 2), ("q2", "A", 2), ("q2", "B", 0), ("q2", "C", 1),
                          ("q3", "A", 1), ("q3", "B", 2), ("q4", "A", 0)]]
    assert consensus(js, ("A", "B"), "C") == {("s", "q1", "u"): 2, ("s", "q2", "u"): 1, ("s", "q3", "u"): 1,
                                              ("s", "q4", "u"): 0}
    assert kappa([0, 1, 2, 2], [0, 1, 2, 2]) == 1.0 and kappa([0, 0], [1, 1]) == 0.0
