"""Eye charts for the vision model, drawn as sketches are drawn, and their scoring (plan VC)."""

import io

import pytest
from PIL import Image

from cameo_ingest.config import IMAGE_PIXELS
from cameo_ingest.eyechart import Card, monotone, parse, perfect, render, score, sides, suite, threshold


def test_suites_draw_and_a_perfect_reader_scores_full():
    """Every card of both suites draws within its size, the same bytes each time, and the
    answer of a model that reads everything right scores 1."""
    for name, n in (("standard", 68), ("quick", 11)):
        cards = suite(name, IMAGE_PIXELS)
        assert len(cards) == n and len({c.id for c in cards}) == n
        for card in cards:
            drawn = render(card)
            assert drawn.png == render(card).png
            with Image.open(io.BytesIO(drawn.png)) as img:
                assert img.size == (card.w, card.h) and card.w % 48 == 0 and card.h % 48 == 0
            assert score(card, drawn.truth, perfect(drawn))["score"] == 1.0
    assert sides(IMAGE_PIXELS)[0] * sides(IMAGE_PIXELS)[1] <= IMAGE_PIXELS


def test_reading_scores():
    card = Card("read", 912, 672, font_px=8)
    truth = {"lines": ["AB-12   4481   K7Q", "9.5   RT58"]}
    assert score(card, truth, {"lines": ["AB-12 4481 K7Q", "9.5 RT58"]})["score"] == 1.0
    assert score(card, truth, {"lines": ["AB-12 4481 K?Q", "9.5"]})["score"] == 0.6  # 3 of 5 tokens
    assert score(card, truth, {"lines": ["ab–12 4481 k7q 9.5 rt58"]})["score"] == 1.0  # case, dashes and lines
    out = score(card, truth, None)
    assert out["score"] == 0.0 and out["unreadable"]


def test_arrow_scores():
    card = Card("arrows", 912, 672, count=4)
    truth = {"arrows": [[1, 2], [3, 2], [4, 1]], "boxes": 4}
    got = score(card, truth, {"arrows": [{"from": 1, "to": 2}, {"from": 2, "to": 3}, {"from": 4, "to": 3},
                                         {"from": "x", "to": 1}]})
    assert (got["right"], got["reversed"], got["ends_wrong"], got["spurious"], got["missed"]) == (1, 1, 1, 1, 1)
    assert got["score"] == pytest.approx(1 / 3, abs=1e-3)


def test_threshold_and_fit():
    assert monotone([0.2, 0.6, 0.5, 0.9]) == [0.2, 0.55, 0.55, 0.9]
    assert threshold([(6, 0.4), (8, 0.8), (10, 1.0)]) == 9.0  # 0.9 is halfway from 8 to 10
    assert threshold([(6, 0.95), (8, 1.0)]) == 6.0
    assert threshold([(6, 0.2), (8, 0.5)]) is None


def test_lenient_replies():
    assert parse('Sure!\n```json\n{"lines": ["A1"]}\n```') == {"lines": ["A1"]}
    assert parse("no json here") is None and parse('{"broken": ') is None and parse(None) is None
