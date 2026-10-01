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
    from cameo_ingest.evaluation.synthetic import QUESTIONS, make_mdzip

    src = tmp_path / "kois.mdzip"
    src.write_bytes(make_mdzip())
    assert main([str(src), "-o", str(tmp_path / "out"), "--no-llm", "--no-render"]) == 0
    chunks = [json.loads(line) for line in (tmp_path / "out" / "chunks.jsonl").open()]
    assert len({q["fact"] for q in QUESTIONS}) == 14 and len(QUESTIONS) == 28
    for q in QUESTIONS:
        texts = [c["text"] for c in chunks if c["metadata"].get("element_id") in q["answers"]]
        assert any(q["evidence"] in t for t in texts), (q["id"], q["evidence"])


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
