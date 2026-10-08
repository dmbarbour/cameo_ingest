"""Topics across models (plan SB CP4): subjects joined across families, by words and shared
elements, or by the LLM; every subject placed or left unsorted, never guessed."""

import json
from collections import Counter

from cameo_ingest import topics
from cameo_ingest.topics import Subject


def _subject(family, n, label, words, elements=()):
    return Subject(f"sha256:{family}/{n}", f"{family}.mdzip", label, words, [f"{family}-d{n}"], [label],
                   f"{label} {words}", set(elements))


def corpus():
    """Three models, each with a requirements, a power and a software subject in its own idiom;
    the bid shares the tender's power elements."""
    out = []
    for fam, idiom in (("tender", "pumphouse"), ("bid", "pumphouse"), ("telescope", "dome")):
        shared = ["_pump", "_motor"] if fam in ("tender", "bid") else []
        out += [_subject(fam, 0, "Requirements", f"{idiom} stakeholder requirements needs shall"),
                _subject(fam, 1, "Power", f"{idiom} power supply voltage battery", shared),
                _subject(fam, 2, "Software", f"{idiom} software control loop code")]
    return out


def test_words_join_across_models_only():
    subs = corpus()
    sim = topics.similarity(subs)
    assert sim and all(topics._family(subs[i]) != topics._family(subs[j]) for i, j in sim)
    # "pumphouse" is two families' word, but no pair within a family is joined by it
    links = topics.shared(subs)
    assert set(links) == {(1, 4)} and links[1, 4] == 1.0
    split = topics.split_words(subs, k=3)
    assert set(split) == set(range(len(subs)))
    by_label = Counter((subs[i].label, t) for i, t in split.items())
    assert len(by_label) == 3  # each kind of subject one topic, across the three models
    view = topics.words_view(subs)
    assert len(view["topics"]) == topics.target(9) == 2 and not view["unsorted"]  # merged down to about sqrt(n/2)
    assert all(len({s.rpartition("/")[2] for s in t["subjects"]}) < 3 for t in view["topics"])  # kinds kept together
    assert topics.words_view(subs) == view  # the same every time


class FakeLLM:
    """Proposes three topics and places each subject by its label; `fail`: "propose", or the n-th
    batch (from 1) goes unanswered."""

    def __init__(self, fail=None):
        self.fail = fail
        self.asked = Counter()

    def ask(self, template, values, **_):
        self.asked[template.id] += 1
        if template.id == "topics-propose":
            if self.fail == "propose":
                return ("Sorry.", None)
            assert "Requirements, tender.mdzip" in values["SUBJECTS"]
            return (json.dumps({"topics": [{"label": x, "holds": x.lower()} for x in ("Requirements", "Power", "Software")]}), None)
        if self.fail == self.asked[template.id]:
            return None
        lines = values["SUBJECTS"].splitlines()
        order = {"Requirements": 1, "Power": 2, "Software": 3}
        return (json.dumps({line.split(". ")[0]: order[line.split(". ")[1].split(" (")[0]] for line in lines}), None)


def test_the_llms_topics_and_its_failures(monkeypatch):
    subs = corpus()
    view = topics.llm_view(FakeLLM(), subs)
    assert [t["label"] for t in view["topics"]] == ["Requirements", "Power", "Software"]
    assert all(len(t["subjects"]) == 3 for t in view["topics"]) and not view["unsorted"]
    assert topics.llm_view(FakeLLM(fail="propose"), subs) is None
    monkeypatch.setattr(topics, "BATCH", 4)
    assert [len(b) for b in topics.batches(subs)] == [3, 3, 3]  # a family's subjects together
    assert topics.requests(subs) == 4
    view = topics.llm_view(FakeLLM(fail=2), subs)
    assert len(view["unsorted"]) == 3 and sum(len(t["subjects"]) for t in view["topics"]) == 6


def test_topics_in_the_page():
    """Members become (family, subject) indexes into the page's families; a family not in the
    page is left out, and a topic left empty with it."""
    from cameo_ingest.searchpage import page_subjects, page_topics

    def fam(token, name):
        return {"name": name, "tokens": [token], "default": "ways-1", "diagrams": {f"{token}-d": [0]},
                "views": [{"id": "ways-1", "kind": "llm", "title": "By part",
                           "subjects": [{"label": "A", "diagrams": [f"{token}-d"]}, {"label": "B", "diagrams": []}]}]}

    families = [fam("sha256:z", "Zed"), fam("sha256:a", "Ay"), fam("sha256:gone", "Gone")]
    pids = {"sha256:z": 0, "sha256:a": 1}
    page_fams = page_subjects(families, pids, {})
    assert [f["n"] for f in page_fams] == ["Ay", "Zed"]
    topics = {"default": "llm", "views": [
        {"id": "llm", "kind": "llm", "title": "Topics", "topics": [
            {"label": "One", "holds": "ones", "subjects": ["sha256:z/0", "sha256:a/1", "sha256:gone/0"]},
            {"label": "Gone only", "subjects": ["sha256:gone/1"]}], "unsorted": ["sha256:a/0"]},
        {"id": "words", "kind": "words", "title": "Words", "topics": [{"label": "w", "subjects": ["sha256:a/0"]}], "unsorted": []}]}
    got = page_topics(topics, families, page_fams, pids)
    assert got == {"dv": "llm", "v": [
        {"id": "llm", "t": "Topics", "kd": "llm", "s": [{"l": "One", "h": "ones", "m": [[1, 0], [0, 1]]}], "u": [[0, 0]]},
        {"id": "words", "t": "Words", "kd": "words", "s": [{"l": "w", "m": [[0, 0]]}]}]}
    assert page_topics({"views": []}, families, page_fams, pids) is None
