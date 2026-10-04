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
    """Both suites' cards, the drawn ones at the fonts and budgets the tests' readers call for:
    8 px for a reader that reads every size, 13 px (the default) for one that reads none, and
    16 px in half the budget for a host with half the budget."""
    cards = {c.id: c for name in ("quick", "standard") for c in reading(name, IMAGE_PIXELS)}
    for name in ("quick", "standard"):
        for font in (8, 13):
            cards.update({c.id: c for c in drawings(name, IMAGE_PIXELS, SketchStyle(font))})
    cards.update({c.id: c for c in drawings("standard", IMAGE_PIXELS // 2, SketchStyle(16))})
    return {hashlib.sha256(d.png).hexdigest(): d for d in map(render, cards.values())}


def read_sketch(truth, every=0):
    """A model's answer on one of the tree's sketches: everything as drawn, or with every `every`-th
    shape's name left out."""
    shapes = [{"number": int(n), "name": "" if every and k % every == every - 1 else name}
              for k, (n, name) in enumerate(truth["shapes"].items())]
    return {"shapes": shapes, "connections": [{"from": a, "to": b} for a, b, _ in truth["links"]]}


class EyeReader:
    """A vision model that knows each card's truth and answers as `policy(card, drawn)` says: a
    dict as JSON, or a string; and knows each validation sketch's truth, answering as `sketches`
    says. `text_first_only`: it reads no card when the image comes first. Any other request (a
    sketch to describe) gets a fixed answer. The order of every request about the tree's own
    sketches is noted."""

    replays = False

    def __init__(self, policy, text_first_only=False, sketches=read_sketch, truths=None):
        self.policy, self.text_first_only, self.sketches = policy, text_first_only, sketches
        self.truths = truths if truths is not None else {}
        self.requests = 0
        self.described: list[str] = []  # each description request's first part: "text" or "image_url"

    def complete(self, model, messages, temperature):
        self.requests += 1
        content = messages[0]["content"]
        images = [p for p in content if p["type"] == "image_url"] if isinstance(content, list) else []
        png = base64.b64decode(images[0]["image_url"]["url"].split(",", 1)[1]) if images else b""
        sha = hashlib.sha256(png).hexdigest()
        drawn = known_cards().get(sha)
        if images and drawn is None:  # a sketch of the tree's, to validate or to describe
            self.described.append(content[0]["type"])
        if self.text_first_only and drawn is not None and content[0]["type"] == "image_url":
            return "?"
        if sha in self.truths:
            return json.dumps(self.sketches(self.truths[sha]))
        if drawn is None:
            return "A block definition diagram showing Drone composed of Battery."
        answer = self.policy(drawn.card, drawn)
        return answer if isinstance(answer, str) else json.dumps(answer)

    def close(self):
        pass


def reader(monkeypatch, policy, text_first_only=False, sketches=read_sketch) -> list[EyeReader]:
    """Fake vision models, each made kept in the list; validation's sketches are noted as drawn, so
    that the models know their truth."""
    from cameo_ingest import llm, validate

    truths: dict[str, dict] = {}
    sample = validate.sample

    def noting(*args, **kw):
        picked = sample(*args, **kw)
        truths.update({hashlib.sha256(s.png).hexdigest(): s.truth for s in picked})
        return picked

    monkeypatch.setattr(validate, "sample", noting)
    made: list[EyeReader] = []
    monkeypatch.setattr(llm, "OpenAIChat",
                        lambda cfg: made.append(EyeReader(policy, text_first_only, sketches, truths)) or made[-1])
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
    # 80 cards, and the trial of the image's place: 6 cards both ways, 2 of them drawn only for it.
    assert len(results["cards"]) == 92 and len(list((dest / "cards").glob("*.png"))) == 82
    assert all(c["score"] == 1.0 for c in results["cards"])
    expected = {"image_pixels": IMAGE_PIXELS, "sketch_font_px": 8, "sketch_arrow_px": 6.0, "sketch_line_px": 1,
                "diagram_modules": "36:6:36", "image_first": True}  # 8 px: 1.3 times the 6 px read
    assert {r["setting"]: r["recommended"] for r in results["recommendations"]} == expected
    assert "| `sketch_font_px` | 13 | 8 **(change)** |" in (dest / "report.md").read_text()
    printed = capsys.readouterr().out
    assert f"recorded: runs with {MODEL} use these settings" in printed
    assert f"draws the tree's {len(before)} sketches again" in printed
    row = record(out)
    assert json.loads(row["settings"]) == expected and row["report"] == f"calibration/{dest.name}"
    # Calibrating again asks nothing: the answers are stored.
    sent = sum(r.requests for r in readers)
    assert sent == 89  # 4 of the trial's cards are reading cards too; 1 validation sketch
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
    assert "diagram_modules: 36:6:36 (was 25:6:25): connections are found among up to 36 shapes (the most tested" \
        in printed
    assert "the quick suite checks a model and is not recorded" in printed and record(out) is None
    report = (next((out / "calibration").iterdir()) / "report.md").read_text()
    assert "| 36 | 100% | 0% | 100% |" in report


def test_unreadable_replies_are_not_recorded(tmp_path, monkeypatch, capsys):
    out = ingest(tmp_path, ("m.mdzip", make_mdzip()), args=("--no-llm", "--no-render"))
    reader(monkeypatch, lambda card, drawn: "I cannot read this image.")
    assert calibrate(out, suite="standard") == 2
    err = capsys.readouterr().err
    assert "92 of 92 replies could not be read" in err and "Not recorded" in err
    assert record(out) is None


def half_budget_host(card, drawn):
    """A host that shrinks images to half our budget, and a model that reads text of 11 px or more,
    once shrunk; arrows it reads perfectly."""
    if card.family == "read" and card.font_px * min(1.0, (0.5 / card.area) ** 0.5) < 11:
        return {"lines": ["?" for _ in drawn.truth["lines"]]}
    return perfect(drawn)


def test_run_calibrates_the_model_first(tmp_path, monkeypatch, capsys):
    """A run with a vision model the tree has no calibration for calibrates it before building:
    half the budget and a larger font, with no setting given by hand. The record stays, and
    `status` shows it."""
    out = ingest(tmp_path, ("m.mdzip", make_mdzip()))
    reader(monkeypatch, half_budget_host)
    assert run_with_model(out) == 0
    err = capsys.readouterr().err
    assert f"calibrating the sketches to {MODEL}" in err and f"calibrated to {MODEL}: image_pixels 322560" in err
    settings = json.loads(record(out)["settings"])
    assert (settings["image_pixels"], settings["sketch_font_px"]) == (IMAGE_PIXELS // 2, 16)  # 1.3 x 11.8 px
    assert settings["diagram_modules"] == "9:6:9"  # no more boxes fit at 16 px in half the budget
    assert options(out)["image_pixels"] == IMAGE_PIXELS // 2 and options(out)["sketch"][0] == 16
    assert main(["status", "-o", str(out)]) == 0
    assert f"calibrated: {MODEL} on " in capsys.readouterr().out


def test_each_model_has_its_own_calibration(tmp_path, monkeypatch, capsys):
    out = ingest(tmp_path, ("m.mdzip", make_mdzip()))
    readers = reader(monkeypatch, lambda card, drawn: perfect(drawn))
    assert run_with_model(out) == 0
    first = options(out)
    assert main(["run", "-o", str(out), "--vision-model", "acme/other-vl", "--no-preflight"]) == 0
    state = State(out)
    assert {r["model"] for r in state.calibrations()} == {MODEL, "acme/other-vl"}
    state.close()
    assert options(out)["vision_model"] == "acme/other-vl" and options(out) != first
    # A rerun asks nothing: the calibration is recorded, and the answers stored.
    sent = sum(r.requests for r in readers)
    assert main(["run", "-o", str(out), "--no-preflight"]) == 0
    assert sum(r.requests for r in readers) == sent
    assert json.loads((out / "run.json").read_text())["llm"]["calls"] == 0


def test_no_calibrate_draws_to_the_defaults(tmp_path, monkeypatch, capsys):
    out = ingest(tmp_path, ("m.mdzip", make_mdzip()))
    readers = reader(monkeypatch, lambda card, drawn: perfect(drawn))
    assert run_with_model(out, "--no-calibrate") == 0
    assert record(out) is None and options(out)["sketch"] == [13, 10.0, 1]
    assert sum(r.requests for r in readers) == 3  # the fixture's descriptions, as without calibration
    assert "calibrating" not in capsys.readouterr().err


def test_a_model_that_reads_only_after_the_text(tmp_path, monkeypatch, capsys):
    """The trial puts the image after the text, every card is asked that way, and the model's
    descriptions are asked that way too. A model that reads either way keeps the image first."""
    out = ingest(tmp_path, ("m.mdzip", make_mdzip()))
    readers = reader(monkeypatch, lambda card, drawn: perfect(drawn), text_first_only=True)
    assert run_with_model(out) == 0
    settings = json.loads(record(out)["settings"])
    assert settings["image_first"] is False and settings["sketch_font_px"] == 8  # read as well as the perfect reader
    assert options(out)["image_first"] is False and set(readers[-1].described) == {"text"}  # validated, described
    report = (next((out / "calibration").iterdir()) / "report.md").read_text()
    assert "with it after the text (difference +100%" in report and "asked with the image after the text" in report


def fiction_scanned(tmp_path, settings=None):
    """The fictional projects added and scanned, not built; `settings`: the tree's own."""
    from cameo_ingest.evaluation.fiction import PROJECTS

    for prefix in sorted(PROJECTS):
        project = PROJECTS[prefix]()
        src = tmp_path / "in" / project.path
        src.parent.mkdir(parents=True, exist_ok=True)
        src.write_bytes(project.mdzip())
    out = tmp_path / "out"
    assert main(["add", str(tmp_path / "in"), "-o", str(out)]) == 0
    assert main(["scan", "-o", str(out)]) == 0
    if settings:
        state = State(out)
        state.save_settings(settings)
        state.close()
    return out


def test_validation_on_the_trees_sketches(tmp_path, monkeypatch, capsys):
    """A model that reads every sketch as drawn: every name, connection and direction, reported
    in one line, in validation.md, and by `status`."""
    out = fiction_scanned(tmp_path)
    reader(monkeypatch, lambda card, drawn: perfect(drawn))
    capsys.readouterr()
    assert calibrate(out, suite="standard") == 0
    err = capsys.readouterr().err
    assert (f"expected quality with {MODEL}: on 8 of the tree's sketches, 100% of names read, 100% of connections "
            "found, 100% of directions right") in err
    dest = next((out / "calibration").iterdir())
    summary = json.loads((dest / "validation.json").read_text())["summary"]
    assert set(summary["strata"]) == {"small", "medium"} and not summary["warnings"]
    assert len(list((dest / "validation").glob("*.png"))) == 8 and "| all | 8 |" in (dest / "validation.md").read_text()
    assert json.loads(record(out)["validation"])["overall"]["names"] == 1.0
    assert main(["status", "-o", str(out)]) == 0
    assert "expected quality: on 8 of the tree's sketches, 100% of names read" in capsys.readouterr().out


def test_validation_warns_of_what_will_suffer(tmp_path, monkeypatch, capsys):
    """A model that leaves out every third shape's name: about two thirds read, and a warning. With
    modules of at most 6 shapes, the sample takes modules of the larger diagrams too."""
    out = fiction_scanned(tmp_path, {"diagram_modules": "9:3:6"})
    reader(monkeypatch, lambda card, drawn: perfect(drawn), sketches=lambda truth: read_sketch(truth, every=3))
    assert calibrate(out, suite="standard") == 0
    summary = json.loads(record(out)["validation"])
    assert 0.55 < summary["overall"]["names"] < 0.8 and summary["overall"]["found"] == 1.0
    assert "modules" in summary["strata"]
    assert any("names read; their descriptions rely on the legend's text" in w for w in summary["warnings"])
    assert "of names read; their descriptions rely on the legend's text for names" in capsys.readouterr().err


def test_validation_counts_invented_connections(tmp_path, monkeypatch, capsys):
    """A model that adds a connection the diagram doesn't have, on every sketch: each counted as
    invented, against all it listed, with a warning when they pass a tenth (plan SK)."""
    out = fiction_scanned(tmp_path)

    def inventing(truth):
        answer = read_sketch(truth)
        answer["connections"].append({"from": 998, "to": 999})
        return answer

    reader(monkeypatch, lambda card, drawn: perfect(drawn), sketches=inventing)
    assert calibrate(out, suite="standard") == 0
    summary = json.loads(record(out)["validation"])
    sketches = json.loads((next((out / "calibration").iterdir()) / "validation.json").read_text())["sketches"]
    links = sum(r["links"] for r in sketches)
    assert summary["overall"]["invented"] == len(sketches) / (links + len(sketches))
    assert summary["overall"]["found"] == 1.0
    assert "of the connections the model listed aren't there" in capsys.readouterr().err


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
    assert "at most that budget, perhaps less" in r["image_pixels"].why  # the range's lower end
    # A host whose budget is above ours: text reads as well in twice the area.
    r = recs(summary({0.5: 7.0, 1.0: 7.0, 2.0: 7.4, 4.0: 11.0}))
    assert r["image_pixels"].recommended == 2 * IMAGE_PIXELS
    # Native resolution: the same threshold at every area; the budget, a cost, as configured.
    r = recs(summary({0.5: 6.0, 1.0: 6.2, 2.0: 6.0, 4.0: 6.1}))
    assert not r["image_pixels"].changes and "native resolution" in r["image_pixels"].why
    assert "at least 4 times this one" in r["image_pixels"].why  # or a host budget beyond the range
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


def test_the_comparison_script(tmp_path):
    """scripts/validate_sketches.py on the fiction: a sample by key, drawn and asked, and scored
    (plan SK-04). A first pass learns each sketch's truth; a model that knows it then reads all."""
    import importlib.util
    from pathlib import Path

    from cameo_ingest.llm import EnrichmentSession, LLMConfig

    spec = importlib.util.spec_from_file_location("validate_sketches",
                                                  Path(__file__).parent.parent / "scripts" / "validate_sketches.py")
    script = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(script)
    out = fiction_scanned(tmp_path / "f")
    sizes = TreeSettings()
    keys = script.choose(out, per_stratum=2, targeted=2, max_projects=8, sizes=sizes)
    assert {k["stratum"] for k in keys} <= {"small", "medium", "modules", "targeted"} and len(keys) >= 4
    truths: dict[str, dict] = {}

    class Knowing:
        replays = False

        def complete(self, model, messages, temperature):
            image = next(p for p in messages[0]["content"] if p["type"] == "image_url")
            sha = hashlib.sha256(base64.b64decode(image["image_url"]["url"].split(",", 1)[1])).hexdigest()
            return json.dumps(read_sketch(truths[sha])) if sha in truths else "{}"

        def close(self):
            pass

    cfg = LLMConfig(None, MODEL, None)
    rows = script.ask(out, keys, EnrichmentSession(cfg, tmp_path / "c1", Knowing()), sizes, True, 2)
    truths.update({r["png_sha256"]: r["truth"] for r in rows})
    again = script.ask(out, keys, EnrichmentSession(cfg, tmp_path / "c2", Knowing()), sizes, True, 2)
    for name, rs in (("first", rows), ("second", again)):
        with (tmp_path / f"{name}.jsonl").open("w") as f:
            f.writelines(json.dumps(r) + "\n" for r in rs)
    table = script.score([tmp_path / "first.jsonl", tmp_path / "second.jsonl"])
    assert "| first | all |" in table and "| second | all | " in table
    second_all = next(line for line in table.splitlines() if line.startswith("| second | all |"))
    assert "| 100% | 100% |" in second_all
