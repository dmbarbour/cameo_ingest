"""Calibrating sketches to the vision model: the command, its recommendations, and the sketch
settings they change (plan VC-03 to VC-05)."""

import base64
import hashlib
import json
import sqlite3

from fixture_model import make_mdzip
from helpers import ingest

from cameo_ingest.calibrate import recommend
from cameo_ingest.cli import main
from cameo_ingest.config import IMAGE_PIXELS, ProjectOptions, TreeSettings
from cameo_ingest.eyechart import perfect, render, suite
from cameo_ingest.state import State


class EyeReader:
    """A vision model that knows each quick-suite card's truth, and answers as `policy(card, drawn)`
    says: a dict as JSON, or a string as it is."""

    replays = False

    def __init__(self, policy):
        self.policy = policy
        self.cards = {hashlib.sha256(d.png).hexdigest(): d for d in map(render, suite("quick", IMAGE_PIXELS))}
        self.requests = 0

    def complete(self, model, messages, temperature):
        self.requests += 1
        (image,) = [p for p in messages[0]["content"] if p["type"] == "image_url"]
        drawn = self.cards[hashlib.sha256(base64.b64decode(image["image_url"]["url"].split(",", 1)[1])).hexdigest()]
        answer = self.policy(drawn.card, drawn)
        return answer if isinstance(answer, str) else json.dumps(answer)

    def close(self):
        pass


def reader(monkeypatch, policy) -> list[EyeReader]:
    from cameo_ingest import llm

    made: list[EyeReader] = []
    monkeypatch.setattr(llm, "OpenAIChat", lambda cfg: made.append(EyeReader(policy)) or made[-1])
    return made


def calibrate(out, *flags) -> int:
    return main(["calibrate-vision", "-o", str(out), "--suite", "quick", "--vision-model", "acme/eye-vl",
                 "--no-preflight", *flags])


def test_a_perfect_reader_keeps_every_setting(tmp_path, monkeypatch, capsys):
    out = ingest(tmp_path, ("m.mdzip", make_mdzip()), args=("--no-llm", "--no-render"))
    readers = reader(monkeypatch, lambda card, drawn: perfect(drawn))
    assert calibrate(out) == 0
    (dest,) = (out / "calibration").iterdir()
    assert dest.name.startswith("acme_eye-vl-")
    results = json.loads((dest / "results.json").read_text())
    assert len(results["cards"]) == 11 and len(list((dest / "cards").glob("*.png"))) == 11
    assert all(c["score"] == 1.0 for c in results["cards"])
    assert all(r["recommended"] == r["current"] for r in results["recommendations"])
    report = (dest / "report.md").read_text()
    assert "| `sketch_font_px` | 12 | 12 |" in report and "native resolution" in report
    assert "`--apply`" not in capsys.readouterr().out
    # The answers are stored: calibrating again sends nothing, and there is nothing to apply.
    sent = sum(r.requests for r in readers)
    assert sent == 11
    assert calibrate(out, "--apply") == 0
    assert sum(r.requests for r in readers) == sent
    assert "nothing to apply" in capsys.readouterr().out
    state = State(out)
    assert not any(k.startswith("sketch") for k in state.settings())
    state.close()


def test_misread_arrowheads_are_enlarged_and_applied(tmp_path, monkeypatch, capsys):
    """A model that reverses one arrow in three below 14 px heads: the heads grow to 14 px; --apply
    writes that to the tree, and the next run draws the sketches again under another options hash."""
    out = ingest(tmp_path, ("m.mdzip", make_mdzip()))

    def policy(card, drawn):
        answer = perfect(drawn)
        if card.family == "arrows" and card.arrow_px < 14:
            answer["arrows"] = [{"from": a["to"], "to": a["from"]} if k % 3 == 0 else a
                                for k, a in enumerate(answer["arrows"])]
        return answer

    reader(monkeypatch, policy)
    sketches = {p.relative_to(out): p.read_bytes() for p in out.glob("by-sha256/*/diagrams/*.png")}
    assert sketches
    db = sqlite3.connect(out / "state.sqlite")
    (hash_before,) = db.execute("SELECT options_hash FROM projects").fetchone()
    db.close()
    capsys.readouterr()
    assert calibrate(out, "--apply") == 0
    printed = capsys.readouterr().out
    assert "sketch_arrow_px: 10.0 -> 14" in printed and "sketch_line_px: 1 (kept)" in printed
    assert f"sketch_arrow_px = 14. The next run draws its {len(sketches)} sketches again" in printed
    state = State(out)
    assert state.settings()["sketch_arrow_px"] == 14
    state.close()
    report = (next((out / "calibration").iterdir()) / "report.md").read_text()
    assert "| 10 px | 1 px | 64% | 36% |" in report and "| 14 px | 1 px | 100% | 0% |" in report  # 4 of 11

    def options_hash():
        db = sqlite3.connect(out / "state.sqlite")
        try:
            return db.execute("SELECT options_hash FROM projects").fetchone()[0]
        finally:
            db.close()

    assert main(["run", "-o", str(out)]) == 0
    assert "1 project(s) written in this run" in capsys.readouterr().out
    assert options_hash() != hash_before
    # The fixture's one connection has no arrowhead; a larger font shows the sketches redrawn.
    assert main(["run", "-o", str(out), "--sketch-font-px", "16"]) == 0
    redrawn = {p.relative_to(out): p.read_bytes() for p in out.glob("by-sha256/*/diagrams/*.png")}
    assert redrawn.keys() == sketches.keys() and redrawn != sketches


def test_unreadable_replies_are_not_applied(tmp_path, monkeypatch, capsys):
    out = ingest(tmp_path, ("m.mdzip", make_mdzip()), args=("--no-llm", "--no-render"))
    reader(monkeypatch, lambda card, drawn: "I cannot read this image.")
    assert calibrate(out, "--apply") == 2
    err = capsys.readouterr().err
    assert "11 of 11 replies could not be read" in err and "not applied" in err


def summary(read, arrows=None, density=None):
    return {"read": [{"area": a, "points": [], "threshold": t} for a, t in read.items()],
            "arrows": [{"arrow_px": a, "line_px": ln, "right": r, "reversed": 1 - r, "cards": 2}
                       for (a, ln), r in (arrows or {}).items()],
            "density": [{"shapes": n, "right": r, "reversed": 0.0, "cards": 2} for n, r in (density or {}).items()],
            "unreadable": 0, "unasked": 0, "cards": 0}


def recs(s, **kw):
    return {r.setting: r for r in recommend(s, IMAGE_PIXELS, **kw)}


def test_the_budget_follows_the_host():
    # A fixed budget at least ours (gemma-4 on DeepInfra): the threshold holds to 1x, grows beyond.
    r = recs(summary({0.5: 7.0, 1.0: 7.5, 2.0: 10.5, 4.0: 15.0}))
    assert not r["image_pixels"].changes and "holds up to 1 times" in r["image_pixels"].why
    assert not r["sketch_font_px"].changes  # 1.3 x 7.5 = 9.75 px: 12 px has the margin
    # A host whose budget is below ours: text reads smaller in half the area.
    r = recs(summary({0.5: 7.0, 1.0: 10.0, 2.0: 14.0, 4.0: 20.0}))
    assert r["image_pixels"].recommended == IMAGE_PIXELS // 2 and r["image_pixels"].recommended % (48 * 48) == 0
    assert r["sketch_font_px"].recommended == 12  # read at the half budget: 1.3 x 7 = 9.1 px
    # Native resolution: the same threshold at every area, so the budget is kept.
    r = recs(summary({0.5: 6.0, 1.0: 6.2, 2.0: 6.0, 4.0: 6.1}))
    assert not r["image_pixels"].changes and "native resolution" in r["image_pixels"].why
    # Too small a font for this model.
    r = recs(summary({0.5: 10.5, 1.0: 10.5, 2.0: 10.5, 4.0: 10.5}))
    assert (r["sketch_font_px"].current, r["sketch_font_px"].recommended) == (12, 14)
    # Nothing read at all: no recommendation but a warning.
    r = recs(summary({1.0: None, 4.0: None}))
    assert list(r) == ["sketch_font_px"] and "check its replies" in r["sketch_font_px"].why


def test_arrowheads_and_modules():
    read = {1.0: 7.0}
    grid = {(6, 1): 0.5, (10, 1): 0.8, (14, 1): 0.97, (6, 2): 0.7, (10, 2): 0.96, (14, 2): 1.0}
    r = recs(summary(read, grid))
    assert (r["sketch_arrow_px"].recommended, r["sketch_line_px"].recommended) == (14, 1)  # the thinnest lines
    # A current size off the grid passes when a smaller one does; nothing passing keeps the current.
    r = recs(summary(read, grid), sketch=(12, 16.0, 1))
    assert not r["sketch_arrow_px"].changes
    r = recs(summary(read, {k: 0.5 for k in grid}))
    assert not r["sketch_arrow_px"].changes and "none reaches 95%" in r["sketch_arrow_px"].why
    r = recs(summary(read, density={9: 1.0, 16: 0.92, 25: 0.85, 36: 0.6}))
    assert r["diagram_modules"].recommended == "16:6:16"
    # A dip at 9 shapes is averaged with the larger counts: the modules hold.
    r = recs(summary(read, density={9: 0.88, 16: 0.96, 25: 0.95, 36: 0.7}))
    assert not r["diagram_modules"].changes


def test_default_sketch_settings_keep_the_options_hash():
    """Trees that never calibrate keep their projects: the sketch settings enter the options only
    when they differ from the defaults (plan VC-05)."""
    default = ProjectOptions.of(TreeSettings(), None, None, None)
    assert "sketch" not in default.as_dict() and default.hash() == ProjectOptions().hash() == "489267e10ded456b"
    calibrated = ProjectOptions.of(TreeSettings(sketch_arrow_px=14), None, None, None)
    assert calibrated.as_dict()["sketch"] == [12, 14.0, 1] and calibrated.hash() != default.hash()
