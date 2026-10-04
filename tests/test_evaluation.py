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


def test_runs_compared_question_by_question():
    """Two runs are paired by question within each system they share; a change is significant
    only when its interval excludes zero, and the questions found by one run only are named."""
    pytest.importorskip("numpy")  # the eval extra
    from cameo_ingest.evaluation.harness import paired_ci
    from cameo_ingest.evaluation.report import compare, render_comparison

    assert paired_ci([0.5, 1.0], [0.5, 1.0]) == (0.0, 0.0, 0.0)
    change, lo, _ = paired_ci([0.0] * 30, [1.0] * 30)
    assert change == 1.0 and lo > 0

    def row(system, q, hit, mrr):
        return {"system": system, "id": q, "hit@10": hit, "mrr@10": mrr}

    before = [row("bm25", f"q{i}", 0.0, 0.0) for i in range(30)] + [row("old", "q0", 1.0, 1.0)]
    after = ([row("bm25", f"q{i}", 1.0, 0.5) for i in reversed(range(30))]  # another order
             + [row("bm25", "extra", 1.0, 1.0), row("new", "q0", 1.0, 1.0)])
    c = compare(before, after, rounds=500)
    assert (c.questions, c.only_before, c.only_after) == (30, 0, 1)
    assert list(c.changes) == ["bm25"]  # only the systems both ran
    hit, mrr = c.changes["bm25"]  # only the measures the rows have, in MEASURES' order
    assert (hit.measure, hit.before, hit.after, hit.change) == ("hit@10", 0.0, 1.0, 1.0) and hit.significant
    assert mrr.change == 0.5 and len(c.significant()) == 2
    assert c.found["bm25"] == ([], sorted(f"q{i}" for i in range(30)))  # in id order
    text = render_comparison(c, "ref", "new")
    assert "30 questions in both (0 asked only before, 1 only after, left out)" in text
    assert "| hit@10 | 0.000 | 1.000 | +1.000 (+1.000 to +1.000) \\* |" in text

    same = compare(before, before, rounds=500)
    assert not same.significant() and "**Significant changes:** none." in render_comparison(same, "a", "a")


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


class FakeEmbeddings:
    """Stands in for the SDK's client: a vector per text (its length, and 1), returned out of order."""

    def __init__(self):
        self.batches: list[list[str]] = []
        self.embeddings = self

    def create(self, model, input, encoding_format):
        from types import SimpleNamespace

        self.batches.append(list(input))
        data = [SimpleNamespace(index=i, embedding=[float(len(t)), 1.0]) for i, t in enumerate(input)]
        return SimpleNamespace(data=data[::-1], usage=SimpleNamespace(prompt_tokens=len(input)))


def test_embedder_batches_counts_and_caches(tmp_path):
    """Texts are sent in the model's batches, with its prefix, each once; the vectors come back in
    order and normalized, and are cached for the next experiment (AR-017, AR-022R4)."""
    np = pytest.importorskip("numpy")
    from cameo_ingest.evaluation.embed import MODELS, Embedder, EmbeddingCache

    model, cache, client = MODELS["e5-large"], EmbeddingCache(tmp_path / "e.sqlite"), FakeEmbeddings()
    texts = [f"text {'x' * i}" for i in range(40)] + ["text "]  # the last repeats the first
    e = Embedder(model, cache, concurrency=4, client=client)
    out = e.embed(texts, "passage")
    assert sorted(len(b) for b in client.batches) == [8, 32]  # 40 different texts, in batches of 32
    assert all(t.startswith("passage: ") for b in client.batches for t in b)
    assert (e.calls, e.tokens) == (2, 40)
    expected = np.array([[len("passage: " + t), 1.0] for t in texts])
    assert np.allclose(out, expected / np.linalg.norm(expected, axis=1, keepdims=True))
    again = Embedder(model, EmbeddingCache(tmp_path / "e.sqlite"), client=FakeEmbeddings())
    assert np.allclose(again.embed(texts, "passage"), out) and again.calls == 0  # all from the cache
    assert again.embed(["text "], "query").shape == (1, 2) and again.calls == 1  # a query is another text


def test_reranker_scores_through_its_cache(tmp_path):
    from cameo_ingest.evaluation.provider import INFERENCE_API
    from cameo_ingest.evaluation.rerank import Reranker

    posts = []

    def post(url, body, retries):
        posts.append((url, body))
        return {"scores": [float(len(p)) for p in body["documents"]], "input_tokens": 7}

    r = Reranker("qwen3-0.6b", tmp_path / "r.sqlite", batch=2, post=post)
    texts = ["a", "bbb", "cc", "dddd", "e"]
    assert r.rerank("q", [0, 1, 2, 3, 4], texts, depth=4) == [3, 1, 2, 0, 4]  # the top 4, longest first
    assert posts[0][0] == f"{INFERENCE_API}/Qwen/Qwen3-Reranker-0.6B" and (r.calls, r.tokens) == (2, 14)
    again = Reranker("qwen3-0.6b", tmp_path / "r.sqlite", post=post)
    assert again.scores([("q", "bbb"), ("q", "e")]) == [3.0, 1.0] and again.calls == 1  # "e" was not scored


class FakeSession:
    """Stands in for an `EnrichmentSession`: a reply per item (the request's first input), or
    None for no answer."""

    def __init__(self, reply):
        self.reply = reply
        self.asked: list[dict] = []

    def ask(self, template, values, *, project="", inputs=()):
        self.asked.append(values)
        text = self.reply(inputs[0] if inputs else "", values)
        return None if text is None else (text, None)


def test_structural_questions(tmp_path, fiction_tree):
    """Questions from a model's structure, answered by its elements; none about the fictional
    projects, which have questions of their own (AR-021R2, AR-022R4)."""
    from fixture_model import make_mdzip
    from helpers import ingest

    from cameo_ingest.evaluation.grading import Question
    from cameo_ingest.evaluation.questions import structural

    out = ingest(tmp_path, ("drone.mdzip", make_mdzip()), args=("--no-llm", "--no-render"))
    [q] = structural(out)
    assert q["question"] == "Which elements satisfy the requirement Endurance?"
    assert (q["answers"], q["related"]) == (["r1"], ["b2"]) and Question.of(q).rule == "element"
    assert structural(fiction_tree) == []


def test_natural_questions_keep_only_quoted_answers(tmp_path):
    """A written question is kept only when its quote is in its chunk, which is then its answer;
    a reply that isn't JSON, or quotes what the chunk doesn't say, is dropped."""
    from fixture_model import make_mdzip
    from helpers import ingest

    from cameo_ingest.evaluation.questions import natural, sample_chunks

    out = ingest(tmp_path, ("drone.mdzip", make_mdzip()), args=("--no-llm", "--no-render"))
    chunks = sample_chunks(out, 3)
    assert len(chunks) == 3
    first, second, third = (c["id"] for c in chunks)

    def reply(item, values):
        quote = " ".join(values["PASSAGE"].split()[:4])
        return {first: f'Here it is: {{"question": "What is this?", "quote": "{quote}"}} Done.',
                second: '{"question": "What?", "quote": "words the chunk does not hold"}',
                third: "I can't write one."}[item]

    session = FakeSession(reply)
    [q] = natural(out, session, per_project=3, concurrency=1)
    assert (q["id"], q["rule"], q["answer_chunks"], q["question"]) == (f"llm:{first}", "source", [first], "What is this?")
    assert len(session.asked) == 3 and all(v["KIND"] for v in session.asked)


def test_judge_reads_replies():
    """Grades from clean JSON, JSON inside prose, or a broken object with a readable grade; None
    for anything else, or no answer."""
    from cameo_ingest.evaluation.judge import judge, panel

    replies = {"a": '{"grade": 2, "reason": "states it"}', "b": 'Sure. {"grade": 1, "reason": "helps"} Hope so.',
               "c": '{"grade": 0, "reason": "a "quoted" word breaks it"}', "d": "No idea.", "e": None,
               "f": '{"grade": 3}'}
    pairs = [{"question": "Q?", "text": f"passage {u}", "unit": u, "set": "s", "qid": "q1"} for u in replies]
    out = judge(FakeSession(lambda item, _v: replies[item]), pairs, concurrency=2)
    assert [(j["unit"], j["grade"]) for j in out] == [("a", 2), ("b", 1), ("c", 0), ("d", None), ("e", None),
                                                      ("f", None)]
    assert out[0]["reason"] == "states it" and "text" not in out[0]
    judgments = [{**j, "judge": "m1"} for j in out] + [{**j, "judge": "m2", "grade": 2} for j in out]
    assert panel(judgments, "s", ("m1", "m2")) == {"q1": {"a": 2, "b": 1, "c": 0, "d": 2, "e": 2, "f": 2}}
    assert panel(judgments, "other", ("m1", "m2")) == {}


def test_run_record(tmp_path, fiction_tree):
    """A run's record says which units it cut windows from, so that the judges read the same
    text (AR-020R2)."""
    from cameo_ingest.evaluation.records import Run

    run = Run(str(fiction_tree), "questions.jsonl", rag=True, project="_abk_", window=256, overlap=32)
    run.write(tmp_path)
    assert Run.read(tmp_path) == run
    units = run.units()
    assert units and all(u.element_id.startswith("_abk_") for u in units)
    chunks = {u.id: u.text for u in Run(str(fiction_tree), "q", project="_abk_").units()}
    assert set(chunks) == {u.id for u in units}
    for u in units:  # rag/'s files, as a RAG tool reads them: the chunk's text, then its source
        assert u.text.startswith(chunks[u.id]) and "\n\nSource: sha256:" in u.text, u.id
