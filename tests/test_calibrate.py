"""Calibrating sketches to the vision model: the command, its recommendations, the record a run
uses, and the sketch settings they change (plans VC, VA)."""

import base64
import functools
import hashlib
import json

from fixture_model import make_mdzip
from helpers import ingest

from cameo_ingest.calibrate import SUITE_VERSION, recommend
from cameo_ingest.cli import main
from cameo_ingest.config import IMAGE_PIXELS, ProjectOptions, TreeSettings
from cameo_ingest.eyechart import Drawn, drawings, perfect, reading, render
from cameo_ingest.sketch import SketchStyle
from cameo_ingest.state import SCHEMA_VERSION, State

MODEL = "acme/eye-vl"


@functools.cache
def known_cards() -> dict[str, Drawn]:
    """Both suites' cards, the drawn ones in the fonts the tests' readers call for: 8 px for a
    reader that reads every size, 13 px (the default) for one that reads none."""
    cards = {c.id: c for name in ("quick", "standard") for c in reading(name, IMAGE_PIXELS)}
    for name in ("quick", "standard"):
        for font in (8, 13):
            cards.update({c.id: c for c in drawings(name, IMAGE_PIXELS, SketchStyle(font))})
    return {hashlib.sha256(d.png).hexdigest(): d for d in map(render, cards.values())}


class EyeReader:
    """A vision model that knows each card's truth and answers as `policy(card, drawn)` says: a
    dict as JSON, or a string. Any other request (a sketch to describe) gets a fixed answer."""

    replays = False

    def __init__(self, policy):
        self.policy = policy
        self.requests = 0

    def complete(self, model, messages, temperature):
        self.requests += 1
        content = messages[0]["content"]
        images = [p for p in content if p["type"] == "image_url"] if isinstance(content, list) else []
        png = base64.b64decode(images[0]["image_url"]["url"].split(",", 1)[1]) if images else b""
        drawn = known_cards().get(hashlib.sha256(png).hexdigest())
        if drawn is None:
            return "A block definition diagram showing Drone composed of Battery."
        answer = self.policy(drawn.card, drawn)
        return answer if isinstance(answer, str) else json.dumps(answer)

    def close(self):
        pass


def reader(monkeypatch, policy) -> list[EyeReader]:
    from cameo_ingest import llm

    made: list[EyeReader] = []
    monkeypatch.setattr(llm, "OpenAIChat", lambda cfg: made.append(EyeReader(policy)) or made[-1])
    return made


def calibrate(out, *flags, suite="quick") -> int:
    return main(["calibrate-vision", "-o", str(out), "--suite", suite, "--vision-model", MODEL, "--no-preflight",
                 *flags])


def run_with_model(out, *flags) -> int:
    return main(["run", "-o", str(out), "--vision-model", MODEL, "--no-preflight", *flags])


def options(out) -> dict:
    return json.loads((out / "run.json").read_text())["options"]


def sketches(out) -> dict:
    return {p.relative_to(out): p.read_bytes() for p in out.glob("by-sha256/*/diagrams/*.png")}


def record(out):
    state = State(out)
    try:
        return state.calibration("", MODEL, SUITE_VERSION)
    finally:
        state.close()


def test_a_calibration_is_recorded_and_runs_use_it(tmp_path, monkeypatch, capsys):
    """A perfect reader: the smallest sizes tested, whatever the tree used; the budget, a cost for a
    model reading at native resolution, as configured. The standard suite's calibration is recorded,
    and runs with that model draw to it; runs without a vision model draw to the defaults."""
    out = ingest(tmp_path, ("m.mdzip", make_mdzip()))
    before = sketches(out)
    readers = reader(monkeypatch, lambda card, drawn: perfect(drawn))
    assert calibrate(out, suite="standard") == 0
    (dest,) = (out / "calibration").iterdir()
    assert dest.name.startswith("acme_eye-vl-")
    results = json.loads((dest / "results.json").read_text())
    assert len(results["cards"]) == 80 and len(list((dest / "cards").glob("*.png"))) == 80
    assert all(c["score"] == 1.0 for c in results["cards"])
    expected = {"image_pixels": IMAGE_PIXELS, "sketch_font_px": 8, "sketch_arrow_px": 6.0, "sketch_line_px": 1,
                "diagram_modules": "36:6:36"}  # 8 px: 1.3 times the 6 px read
    assert {r["setting"]: r["recommended"] for r in results["recommendations"]} == expected
    assert "| `sketch_font_px` | 13 | 8 **(change)** |" in (dest / "report.md").read_text()
    printed = capsys.readouterr().out
    assert f"recorded: runs with {MODEL} use these settings" in printed
    assert f"draws the tree's {len(before)} sketches again" in printed
    row = record(out)
    assert json.loads(row["settings"]) == expected and row["report"] == f"calibration/{dest.name}"
    # Calibrating again asks nothing: the answers are stored.
    sent = sum(r.requests for r in readers)
    assert sent == 80
    assert calibrate(out, suite="standard") == 0
    assert sum(r.requests for r in readers) == sent
    assert run_with_model(out) == 0
    assert options(out)["sketch"] == [8, 6.0, 1] and options(out)["modules"] == [36, 6, 36]
    assert sketches(out).keys() == before.keys() and sketches(out) != before
    assert main(["run", "-o", str(out), "--no-llm"]) == 0
    assert options(out)["sketch"] == [13, 10.0, 1] and sketches(out) == before


def test_the_trees_own_settings_win(tmp_path, monkeypatch, capsys):
    out = ingest(tmp_path, ("m.mdzip", make_mdzip()), args=("--no-llm", "--no-render", "--sketch-font-px", "15"))
    reader(monkeypatch, lambda card, drawn: perfect(drawn))
    assert calibrate(out, suite="standard") == 0
    printed = capsys.readouterr().out
    assert "sketch_font_px: 8 (was 15): " in printed and "the tree's own setting, 15, overrides it" in printed
    assert run_with_model(out) == 0
    assert options(out)["sketch"] == [15, 6.0, 1]


def test_misread_arrowheads_are_enlarged(tmp_path, monkeypatch, capsys):
    """A model that reverses one arrow in three below 14 px heads gets 14 px heads."""
    out = ingest(tmp_path, ("m.mdzip", make_mdzip()), args=("--no-llm", "--no-render"))

    def policy(card, drawn):
        answer = perfect(drawn)
        if card.family == "arrows" and card.arrow_px < 14:
            answer["arrows"] = [{"from": a["to"], "to": a["from"]} if k % 3 == 0 else a
                                for k, a in enumerate(answer["arrows"])]
        return answer

    reader(monkeypatch, policy)
    assert calibrate(out, suite="standard") == 0
    printed = capsys.readouterr().out
    assert "sketch_arrow_px: 14 (was 10.0)" in printed and "sketch_line_px: 1: " in printed
    assert json.loads(record(out)["settings"])["sketch_arrow_px"] == 14.0
    report = (next((out / "calibration").iterdir()) / "report.md").read_text()
    assert "| 10 px | 1 px | 64% | 36% |" in report and "| 14 px | 1 px | 100% | 0% |" in report  # 4 of 11


def test_a_reader_that_reverses_every_arrow(tmp_path, monkeypatch, capsys):
    """Every connection found, none the right way round: no arrowhead size helps, so the default
    sizes are recommended and flagged; the modules grow, since their measure is connections found.
    The quick suite checks a model, and is not recorded."""
    out = ingest(tmp_path, ("m.mdzip", make_mdzip()), args=("--no-llm", "--no-render"))

    def policy(card, drawn):
        answer = perfect(drawn)
        if card.family != "read":
            answer["arrows"] = [{"from": a["to"], "to": a["from"]} for a in answer["arrows"]]
        return answer

    reader(monkeypatch, policy)
    assert calibrate(out) == 0
    printed = capsys.readouterr().out
    assert "sketch_arrow_px: 10.0: none reaches 95% (the best, 0%): the default sizes" in printed
    assert "diagram_modules: 36:6:36 (was 25:6:25): connections are found among up to 36 shapes (the most tested)" \
        in printed
    assert "the quick suite checks a model and is not recorded" in printed and record(out) is None
    report = (next((out / "calibration").iterdir()) / "report.md").read_text()
    assert "| 36 | 100% | 0% | 100% |" in report


def test_unreadable_replies_are_not_recorded(tmp_path, monkeypatch, capsys):
    out = ingest(tmp_path, ("m.mdzip", make_mdzip()), args=("--no-llm", "--no-render"))
    reader(monkeypatch, lambda card, drawn: "I cannot read this image.")
    assert calibrate(out, suite="standard") == 2
    err = capsys.readouterr().err
    assert "80 of 80 replies could not be read" in err and "Not recorded" in err
    assert record(out) is None


def test_a_schema_2_tree_migrates(tmp_path):
    st = State(tmp_path)
    st.db.execute("DROP TABLE calibrations")
    st.db.execute("UPDATE meta SET value = '2' WHERE key = 'schema_version'")
    st.close()
    st = State(tmp_path)
    assert st.calibrations() == []
    assert st.db.execute("SELECT value FROM meta WHERE key = 'schema_version'").fetchone()[0] == str(SCHEMA_VERSION)
    st.save_calibration("", MODEL, SUITE_VERSION, {"sketch_font_px": 9}, {}, "calibration/x")
    assert json.loads(st.calibration("", MODEL, SUITE_VERSION)["settings"]) == {"sketch_font_px": 9}
    st.close()


def summary(read, arrows=None, density=None):
    return {"read": [{"area": a, "points": [], "threshold": t} for a, t in read.items()],
            "arrows": [{"arrow_px": a, "line_px": ln, "right": r, "reversed": 1 - r, "cards": 2}
                       for (a, ln), r in (arrows or {}).items()],
            "density": [{"shapes": n, "right": r - 0.05, "reversed": 0.05, "found": r, "cards": 2}
                        for n, r in (density or {}).items()],
            "unreadable": 0, "unasked": 0, "cards": 0}


def recs(s, **kw):
    return {r.setting: r for r in recommend(s, IMAGE_PIXELS, **kw)}


def test_the_budget_follows_the_host():
    # A fixed budget about ours (gemma-4 on DeepInfra): the threshold holds to 1x, grows beyond.
    r = recs(summary({0.5: 7.0, 1.0: 7.5, 2.0: 10.5, 4.0: 15.0}))
    assert not r["image_pixels"].changes and "as well up to 1 times" in r["image_pixels"].why
    assert r["sketch_font_px"].recommended == 10  # 1.3 x 7.5 = 9.75 px, down from 13: never the current size
    # A host whose budget is below ours: text reads smaller in half the area.
    r = recs(summary({0.5: 7.0, 1.0: 10.0, 2.0: 14.0, 4.0: 20.0}))
    assert r["image_pixels"].recommended == IMAGE_PIXELS // 2 and r["image_pixels"].recommended % (48 * 48) == 0
    assert r["sketch_font_px"].recommended == 10  # read at the half budget: 1.3 x 7 = 9.1 px
    # A host whose budget is above ours: text reads as well in twice the area.
    r = recs(summary({0.5: 7.0, 1.0: 7.0, 2.0: 7.4, 4.0: 11.0}))
    assert r["image_pixels"].recommended == 2 * IMAGE_PIXELS
    # Native resolution: the same threshold at every area; the budget, a cost, as configured.
    r = recs(summary({0.5: 6.0, 1.0: 6.2, 2.0: 6.0, 4.0: 6.1}))
    assert not r["image_pixels"].changes and "native resolution" in r["image_pixels"].why
    assert r["sketch_font_px"].recommended == 9  # 1.3 x 6.2 px at the configured budget
    # Too small a font for this model.
    r = recs(summary({0.5: 10.5, 1.0: 10.5, 2.0: 10.5, 4.0: 10.5}))
    assert (r["sketch_font_px"].current, r["sketch_font_px"].recommended) == (13, 14)
    # Nothing read at all: the reference font, and a warning.
    r = recs(summary({1.0: None, 4.0: None}))
    assert list(r) == ["sketch_font_px"] and "check its replies" in r["sketch_font_px"].why


def test_arrowheads_and_modules():
    read = {1.0: 7.0}
    grid = {(6, 1): 0.5, (10, 1): 0.8, (14, 1): 0.97, (6, 2): 0.7, (10, 2): 0.96, (14, 2): 1.0}
    r = recs(summary(read, grid))
    assert (r["sketch_arrow_px"].recommended, r["sketch_line_px"].recommended) == (14, 1)  # the thinnest lines
    # Whatever the tree uses now; with nothing passing, the defaults, not the tree's sizes.
    r = recs(summary(read, grid), sketch=(12, 16.0, 2))
    assert (r["sketch_arrow_px"].recommended, r["sketch_line_px"].recommended) == (14, 1)
    r = recs(summary(read, {k: 0.5 for k in grid}), sketch=(12, 16.0, 2))
    assert (r["sketch_arrow_px"].recommended, r["sketch_line_px"].recommended) == (10, 1)
    assert "none reaches 95%" in r["sketch_arrow_px"].why
    r = recs(summary(read, density={9: 1.0, 16: 0.92, 25: 0.85, 36: 0.6}))
    assert r["diagram_modules"].recommended == "16:6:16"
    # A dip at 9 shapes is averaged with the larger counts: 25 shapes hold.
    r = recs(summary(read, density={9: 0.88, 16: 0.96, 25: 0.95, 36: 0.7}))
    assert r["diagram_modules"].recommended == "25:6:25"
    r = recs(summary(read, density={9: 1.0, 16: 1.0, 25: 0.97, 36: 0.93}))
    assert r["diagram_modules"].recommended == "36:6:36" and "the most tested" in r["diagram_modules"].why


def test_sketch_settings_are_options():
    """The sketch sizes are options of every project, like the budget (plan VC-05)."""
    default = ProjectOptions.of(TreeSettings(), None, None, None)
    assert default.as_dict()["sketch"] == [13, 10.0, 1] and default.hash() == ProjectOptions().hash()
    calibrated = ProjectOptions.of(TreeSettings(sketch_arrow_px=14), None, None, None)
    assert calibrated.as_dict()["sketch"] == [13, 14.0, 1] and calibrated.hash() != default.hash()
