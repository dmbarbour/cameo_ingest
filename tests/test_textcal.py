"""Reading cards for calibrating to the text model (plan TC-03)."""

import re

from cameo_ingest import textcal as tc


def test_cards_are_fixed_and_fit():
    for n in tc.LENGTHS:
        c = tc.card(n, 0)
        assert 0.85 * n < len(c.text) <= n and c.text == tc.card(n, 0).text  # the same seed, the same card
        per_fifth = [sum(e.fifth == f for e in c.elements) for f in range(tc.FIFTHS)]
        assert max(per_fifth) - min(per_fifth) <= 2, per_fifth  # elements spread evenly
        words = [e.word for e in c.elements]
        assert len(set(words)) == len(words)
        figures = [e.fact[1] for e in c.elements if e.fact]
        assert len({f.split()[0] for f in figures}) == len(figures)  # each figure once
        assert [e.fifth for e in c.elements if e.theme] == list(range(tc.FIFTHS))  # a group's hub in each fifth
        for i, e in enumerate(c.elements):  # an element is named only in its own group: where it sits
            assert c.text.index(e.text) == e.start
            naming = [o for o in c.elements if re.search(rf"\b{e.word}\b", o.text)]
            assert {o.fifth for o in naming} <= {e.fifth - 1, e.fifth, e.fifth + 1}, e.name
            assert e.theme or len(naming) <= 3, (e.name, [o.name for o in naming])
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
    hubs = [e for e in c.elements if e.theme]
    s = tc.score_summary(c, f"The part models the {first.name.lower()} and the {last.word} array, the "
                            f"{hubs[1].name}, and a unit that handles {hubs[3].theme}.")
    assert s["named"][0] >= 1 and s["named"][-1] >= 1 and sum(s["present"]) == len(c.elements)
    assert s["groups"] == [1] * 5 and s["covered"][1] == s["covered"][3] == 1  # by name, or by purpose
    assert s["covered"][2] == 0
    values = tc.summary_values(c)
    assert values["SECTIONS"] == c.text and "{{" not in tc.FACTS.render(tc.facts_values(c))


def test_summary_by_length():
    results = [{"length": 6_000, "asked": True, "probe": "summary", "covered": [2, 1, 1, 1, 2], "groups": [2] * 5,
                "named": [2, 1, 1, 1, 2], "present": [4] * 5},
               {"length": 6_000, "asked": True, "probe": "facts", "right": [1, 1, 0, 1, 1], "posed": [1] * 5},
               {"length": 6_000, "asked": False, "probe": "facts", "right": [0] * 5, "posed": [1] * 5}]
    [s] = tc.summarize(results)
    assert s["covered"] == [1, 0.5, 0.5, 0.5, 1] and s["middle_over_ends"] == 0.5
    assert s["named"] == [0.5, 0.25, 0.25, 0.25, 0.5]
    assert s["right"] == [1, 1, 0, 1, 1] and s["right_all"] == 0.8  # a card not asked isn't scored


class TextReader:
    """A text model that reads only the first `reach` characters of each input: it names a
    reading card's groups, and answers its questions, from what it read. Other requests get a
    fixed answer."""

    replays = False

    def __init__(self, reach: int):
        self.reach, self.cards = reach, 0

    def complete(self, model, messages, temperature):
        text = messages[0]["content"]
        if tc.PACKAGE not in text:
            return "A package of blocks."
        self.cards += 1
        head, body = text.split("\n---\n", 1)
        body = body[:self.reach]
        if "Q1:" not in head:  # the summary probe
            return "This part has the " + ", the ".join(re.findall(r"«Block» (\w+ Station)", body)) + "."
        sections = {s.split("\n", 1)[0]: s for s in body.split("\n\n")}
        answers = []
        for i, attr, name in re.findall(r"^Q(\d): What is the (\w+) of the (.+)\?$", head, re.MULTILINE):
            m = re.search(rf"Property {attr} = (.+)", sections.get(f"«Block» {name}", ""))
            answers.append(f"Q{i}: {m.group(1) if m else 'not stated'}")
        return "\n".join(answers)

    def close(self):
        pass


def reading(monkeypatch, reach: int) -> list[TextReader]:
    from cameo_ingest import llm

    made: list[TextReader] = []
    monkeypatch.setattr(llm, "OpenAIChat", lambda cfg: made.append(TextReader(reach)) or made[-1])
    return made


def test_a_run_guards_the_part_size(tmp_path, monkeypatch, capsys):
    """A text model the tree has no calibration for is calibrated before building (plan TC-08):
    one that reads every card keeps 12,000; one that loses the end of 12,000 characters gets
    6,000, and its projects are made again; a rerun asks nothing."""
    import json

    from fixture_model import make_mdzip
    from helpers import cli, ingest

    reading(monkeypatch, 10**9)
    out = ingest(tmp_path, ("m.mdzip", make_mdzip()), args=("--text-model", "good", "--no-render", "--no-preflight"))
    err = capsys.readouterr().err
    assert "calibrating to good" in err and "calibrated to good: part_chars 12,000" in err
    assert json.loads((out / "run.json").read_text())["options"]["part_chars"] == 12_000
    report = next((out / "calibration").glob("good-text-*")) / "report.md"
    assert "**Part size: 12,000 characters.**" in report.read_text()

    readers = reading(monkeypatch, 9_000)
    assert cli(["run", "-o", str(out), "--text-model", "short"]) == 0
    assert "calibrated to short: part_chars 6,000" in capsys.readouterr().err
    run = json.loads((out / "run.json").read_text())
    assert run["options"]["part_chars"] == 6_000 and run["projects"]["written"] == 1  # made again
    assert sum(r.cards for r in readers) == 2 * tc.GUARD_CARDS * len(tc.GUARD_LENGTHS)

    readers = reading(monkeypatch, 9_000)
    assert cli(["run", "-o", str(out)]) == 0
    assert sum(r.cards for r in readers) == 0  # the record stands
    assert cli(["status", "-o", str(out)]) == 0
    status = capsys.readouterr().out
    assert "calibrated (text): short on " in status and "part_chars 6000" in status


def test_calibrate_text_on_demand(tmp_path, monkeypatch, capsys):
    """`calibrate-text` calibrates the tree's text model when asked, and records it; asked again,
    it answers from the store."""
    import json

    from fixture_model import make_mdzip
    from helpers import cli, ingest

    from cameo_ingest.state import State

    out = ingest(tmp_path, ("m.mdzip", make_mdzip()))
    assert cli(["calibrate-text", "-o", str(out)]) == 2  # no text model
    readers = reading(monkeypatch, 9_000)
    assert cli(["calibrate-text", "-o", str(out), "--text-model", "short", "--no-preflight"]) == 0
    printed = capsys.readouterr().out
    assert "part_chars: 6,000: the model reads 6,000-character inputs evenly, but not 12,000" in printed
    assert "recorded: runs with short use this part size" in printed
    st = State(out)
    assert json.loads(st.calibration("", "short", tc.SUITE_VERSION, "text")["settings"]) == {"part_chars": 6000}
    st.close()
    assert sum(r.cards for r in readers) == 30
    readers = reading(monkeypatch, 9_000)
    assert cli(["calibrate-text", "-o", str(out), "--text-model", "short", "--no-preflight"]) == 0
    assert sum(r.cards for r in readers) == 0  # every card answered from the store
