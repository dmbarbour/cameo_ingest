"""Reading cards for calibrating to the text model (plan TC-03)."""

import re

from cameo_ingest import textcal as tc


def test_cards_are_fixed_and_fit():
    for n in tc.LENGTHS:
        c = tc.card(n, 0)
        assert n - 600 < len(c.text) <= n and c.text == tc.card(n, 0).text  # the same seed, the same card
        per_fifth = [sum(e.fifth == f for e in c.elements) for f in range(tc.FIFTHS)]
        assert max(per_fifth) - min(per_fifth) <= 2, per_fifth  # elements spread evenly
        words = [e.word for e in c.elements]
        assert len(set(words)) == len(words)
        figures = [e.fact[1] for e in c.elements if e.fact]
        assert len({f.split()[0] for f in figures}) == len(figures)  # each figure once
        for i, e in enumerate(c.elements):  # an element is named where it sits, and by its neighbours only
            assert c.text.index(e.text) == e.start
            naming = [j for j, o in enumerate(c.elements) if re.search(rf"\b{e.word}\b", o.text)]
            assert naming[0] == i and naming[-1] - i <= 2, (e.name, naming)
    assert tc.card(12_000, 0).text != tc.card(12_000, 1).text


def test_scoring_is_exact():
    c = tc.card(12_000, 2)
    asked = tc.questions(c)
    assert sorted(e.fifth for e in asked) == list(range(tc.FIFTHS))
    replies = "\n".join(f"Q{i}: {e.fact[1]}" for i, e in enumerate(asked, 1))
    assert tc.score_facts(c, replies) == {"right": [1] * 5, "posed": [1] * 5}
    wrong = replies.replace(f"Q1: {asked[0].fact[1]}", "Q1: not stated")
    assert sum(tc.score_facts(c, wrong)["right"]) == 4 and tc.score_facts(c, None)["right"] == [0] * 5
    first, last = c.elements[0], c.elements[-1]
    s = tc.score_summary(c, f"The part models the {first.name.lower()} and the {last.word} array.")
    assert s["named"][0] == 1 and s["named"][-1] == 1 and sum(s["named"]) == 2
    assert sum(s["present"]) == len(c.elements)
    values = tc.summary_values(c)
    assert values["SECTIONS"] == c.text and "{{" not in tc.FACTS.render(tc.facts_values(c))


def test_summary_by_length():
    results = [{"length": 6_000, "asked": True, "probe": "summary", "named": [2, 1, 1, 1, 2], "present": [4] * 5},
               {"length": 6_000, "asked": True, "probe": "facts", "right": [1, 1, 0, 1, 1], "posed": [1] * 5},
               {"length": 6_000, "asked": False, "probe": "facts", "right": [0] * 5, "posed": [1] * 5}]
    [s] = tc.summarize(results)
    assert s["named"] == [0.5, 0.25, 0.25, 0.25, 0.5] and s["middle_over_ends"] == 0.5
    assert s["right"] == [1, 1, 0, 1, 1] and s["right_all"] == 0.8  # a card not asked isn't scored
