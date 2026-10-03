"""Eye charts for the vision model, drawn as sketches are drawn (plan VC-01, VC-02).

A card is an image whose answer is known and can't be guessed: random codes and numbers, or
numbered boxes joined by arrows, drawn with `sketch.py`'s own font, number tags, lines and
arrowheads. What a model reads on cards is then what it reads on sketches, in the settings'
own units. Each card is seeded by its id, so the same card is the same bytes every time.

Families:
- **read:** lines of codes and numbers at a font size, in an image of a given area (acuity,
  and whether the host shrinks large images to a fixed budget).
- **arrows:** numbered boxes joined by arrows, at an arrowhead size and line width; the model
  lists each arrow from number to number, as a diagram's description must.
- **density:** the same at 9 to 36 boxes, for the size of a large diagram's modules.

The scoring, the monotone fit and the threshold are ported from the maintainer's
`semantic_pdf_diff` eye test (`lab/src/semantic_pdf_diff_lab/bench/eyetest.py`, MIT), which
draws with PyMuPDF; this draws with Pillow, as the sketches are drawn.
"""

from __future__ import annotations

import functools
import io
import json
import math
import random
import re
import unicodedata
from dataclasses import asdict, dataclass
from difflib import SequenceMatcher
from typing import Any

from PIL import Image, ImageDraw, ImageFont

from . import sketch
from .sketch import INK, SketchStyle
from .vision import patch_sides

LETTERS = "ABCDEFGHJKLMNPRSTUVWXYZ"  # no I, O or Q, as drawings avoid them
PASS = 0.9  # a font size is read when 90% of its items are
ASPECT = 4 / 3
RANDOM = "Everything written in it is random: nothing can be guessed or corrected from context, so read it."
JSON_ONLY = "Return only JSON: "
READ_PROMPT = ("The image shows a few lines of codes and numbers. " + RANDOM + " Transcribe every line exactly as "
               "printed, top to bottom, keeping the order of the items in each line. Write ? for each character "
               "you can't read.\n" + JSON_ONLY + '{"lines": ["first line", "second line"]}')
ARROWS_PROMPT = ("The image shows numbered boxes, each with a name, joined by arrows. " + RANDOM + " List every "
                 "arrow by the numbers of the two boxes it joins: the box it starts from, and the box its arrowhead "
                 "points to.\n" + JSON_ONLY + '{"arrows": [{"from": 3, "to": 7}]}')


@dataclass(frozen=True)
class Card:
    family: str  # read, arrows, density
    w: int
    h: int
    font_px: int = SketchStyle.font_px
    arrow_px: float = SketchStyle.arrow_px
    line_px: int = SketchStyle.line_px
    count: int = 0  # lines (read) or boxes (arrows, density); 0: the family's default
    seed: int = 1
    area: float = 1.0  # the image's area, as a multiple of the budget it was made for (for the report)

    @property
    def id(self) -> str:
        parts = [self.family, f"{self.w}x{self.h}", f"f{self.font_px}"]
        if self.family != "read":
            parts += [f"a{self.arrow_px:g}", f"l{self.line_px}", f"n{self.count}"]
        return "-".join(parts + [f"s{self.seed}"])

    @property
    def style(self) -> SketchStyle:
        return SketchStyle(self.font_px, self.arrow_px, self.line_px)


def sides(pixels: float) -> tuple[int, int]:
    """An image of about `pixels` at 4:3, sides in whole patches."""
    return patch_sides(math.sqrt(pixels * ASPECT), math.sqrt(pixels / ASPECT))


# -- suites ----------------------------------------------------------------------------------------
def reading(name: str, pixels: int) -> list[Card]:
    """The reading cards of a suite, in images of a half to four times a budget of `pixels`."""
    standard = name == "standard"
    seeds = (1, 2) if standard else (1,)
    fonts = (6, 7, 8, 10, 12, 16) if standard else (6, 8, 12)
    areas = (0.5, 1.0, 2.0, 4.0) if standard else (1.0, 4.0)
    return [Card("read", *sides(pixels * a), font_px=f, seed=s, area=a) for a in areas for f in fonts for s in seeds]


def drawings(name: str, pixels: int, style: SketchStyle = sketch.STYLE) -> list[Card]:
    """The arrow and density cards of a suite, at a budget of `pixels`, named in `style`'s font,
    with the density cards drawn in it whole. A count of boxes that doesn't fit is left out."""
    standard = name == "standard"
    w, h = sides(pixels)
    cards = [Card("arrows", w, h, style.font_px, arrow, line, count=9, seed=s)
             for arrow in (6, 10, 14) for line in ((1, 2) if standard else (1,))
             for s in ((1, 2, 3, 4) if standard else (1,))]
    cards += [Card("density", w, h, style.font_px, style.arrow_px, style.line_px, count=n, seed=s)
              for n in ((9, 16, 25, 36) if standard else (16, 36)) for s in ((1, 2) if standard else (1,))]
    return [c for c in cards if fits(c)]


def order_trial(pixels: int, style: SketchStyle = sketch.STYLE) -> list[Card]:
    """Cards to ask with the image both before and after the text (plan VA): reading at the
    budget, at sizes where models differ, and arrows at `style`'s sizes."""
    w, h = sides(pixels)
    return ([Card("read", w, h, font_px=f, seed=1) for f in (7, 8, 10, 12)]
            + [Card("arrows", w, h, style.font_px, style.arrow_px, style.line_px, count=9, seed=s) for s in (1, 2)])


def suite(name: str, pixels: int, style: SketchStyle = sketch.STYLE) -> list[Card]:
    """Every card of a suite. `standard`: 80 cards, to calibrate; `quick`: 11, to check a model.
    Calibration asks the reading cards first, and draws the rest at the font and budget they call
    for (`calibrate.measure`)."""
    return reading(name, pixels) + drawings(name, pixels, style)


def fits(card: Card) -> bool:
    try:
        render(card)
    except ValueError:
        return False
    return True


# -- random content --------------------------------------------------------------------------------
def code(rng: random.Random) -> str:
    """A random label: "HX-402", "P-17B", "K7Q", "RT58"."""
    kind = rng.random()
    if kind < 0.4:
        return ("".join(rng.choices(LETTERS, k=rng.randint(1, 3))) + "-" + str(rng.randint(1, 999))
                + (rng.choice(LETTERS) if rng.random() < 0.3 else ""))
    if kind < 0.7:
        return rng.choice(LETTERS) + str(rng.randint(0, 9)) + rng.choice(LETTERS)
    return "".join(rng.choices(LETTERS, k=2)) + str(rng.randint(10, 99))


def number(rng: random.Random) -> str:
    """A random value of digits and a point: "4827", "31.6", "0.075"."""
    if rng.random() < 0.5:
        return str(rng.randint(10, 9999))
    digits = rng.randint(1, 3)
    return f"{rng.randint(0, 999)}.{str(rng.randint(1, 10 ** digits - 1)).zfill(digits).rstrip('0') or '5'}"


def unique(rng: random.Random, make, n: int) -> list[str]:
    seen: set[str] = set()
    out = []
    while len(out) < n:
        x = make(rng)
        if compact(x) not in seen:
            seen.add(compact(x))
            out.append(x)
    return out


# -- drawing ---------------------------------------------------------------------------------------
@dataclass(frozen=True)
class Drawn:
    card: Card
    png: bytes
    truth: dict[str, Any]
    prompt: str


@functools.lru_cache(maxsize=256)  # a calibration draws each card to fit, to ask and to save it
def render(card: Card) -> Drawn:
    """The card's image, its truth and its prompt. Raises ValueError when its content doesn't
    fit the image (a suite that asks too much of a size)."""
    rng = random.Random(card.id)
    img = Image.new("L", (card.w, card.h), "white")
    d = ImageDraw.Draw(img)
    font = ImageFont.load_default(size=card.font_px)
    truth, prompt = (_read if card.family == "read" else _boxes)(card, rng, d, font)
    buf = io.BytesIO()
    img.save(buf, "PNG", compress_level=6)
    return Drawn(card, buf.getvalue(), truth, prompt)


def _read(card: Card, rng: random.Random, d: ImageDraw.ImageDraw, font) -> tuple[dict, str]:
    margin = max(8.0, card.font_px)
    gap, room = card.font_px * 1.6, card.w - 2 * margin
    n = min(card.count or 5, int((card.h - 2 * margin) // gap))
    lines = []
    for _ in range(n):
        tokens: list[str] = []
        while len(tokens) < 8:
            token = code(rng) if rng.random() < 0.5 else number(rng)
            if d.textlength("   ".join(tokens + [token]), font=font) > room:
                break
            tokens.append(token)
        if tokens:
            lines.append("   ".join(tokens))
    if not lines:
        raise ValueError(f"{card.id}: the font is too large for the image")
    block_w = max(d.textlength(line, font=font) for line in lines)
    x0 = margin + rng.random() * max(0.0, room - block_w)
    y0 = margin + rng.random() * max(0.0, card.h - 2 * margin - gap * len(lines))
    for k, line in enumerate(lines):
        d.text((x0, y0 + k * gap), line, fill="black", font=font)
    return {"lines": lines}, READ_PROMPT


def _border(box: tuple[float, float, float, float], toward: tuple[float, float]) -> tuple[float, float]:
    """Where the line from the box's centre toward a point leaves the box."""
    cx, cy = (box[0] + box[2]) / 2, (box[1] + box[3]) / 2
    dx, dy = toward[0] - cx, toward[1] - cy
    t = min((box[2] - box[0]) / 2 / abs(dx) if dx else math.inf, (box[3] - box[1]) / 2 / abs(dy) if dy else math.inf)
    return cx + t * dx, cy + t * dy


def _boxes(card: Card, rng: random.Random, d: ImageDraw.ImageDraw, font) -> tuple[dict, str]:
    """Boxes tagged with numbers and named, as a sketch's shapes are, joined by arrows drawn as a
    sketch draws them. The numbers are shuffled, so that reading order tells nothing."""
    n, style = card.count or 9, card.style
    margin = 10.0
    cols = max(2, round(math.sqrt(n * card.w / card.h)))
    rows = max(2, math.ceil(n / cols))
    cell_w, cell_h = (card.w - 2 * margin) / cols, (card.h - 2 * margin) / rows
    names = unique(rng, code, n)
    nums = list(range(1, n + 1))
    rng.shuffle(nums)
    boxes, tags = [], []
    for k in range(n):
        col, row = k % cols, k // cols
        tw = d.textlength(str(nums[k]), font=font)
        bw = tw + d.textlength(names[k], font=font) + 2.0 * card.font_px
        bh = 2.6 * card.font_px
        if bw > cell_w * 0.85 or bh > cell_h * 0.6:
            raise ValueError(f"{card.id}: too many boxes for the image at this font")
        cx = margin + (col + 0.5 + rng.uniform(-0.08, 0.08)) * cell_w
        cy = margin + (row + 0.5 + rng.uniform(-0.12, 0.12)) * cell_h
        boxes.append((cx - bw / 2, cy - bh / 2, cx + bw / 2, cy + bh / 2))
        tags.append(tw)
    pairs = [(r * cols + c, r * cols + c + 1) for r in range(rows) for c in range(cols - 1) if r * cols + c + 1 < n]
    pairs += [(r * cols + c, (r + 1) * cols + c) for r in range(rows - 1) for c in range(cols)
              if (r + 1) * cols + c < n]
    rng.shuffle(pairs)
    chosen = pairs[:max(n - 1, round(n * 1.2))]
    edges = []
    for a, b in chosen:
        if rng.random() < 0.5:
            a, b = b, a
        ca = ((boxes[a][0] + boxes[a][2]) / 2, (boxes[a][1] + boxes[a][3]) / 2)
        cb = ((boxes[b][0] + boxes[b][2]) / 2, (boxes[b][1] + boxes[b][3]) / 2)
        edges.append((a, b, _border(boxes[a], cb), _border(boxes[b], ca)))
    for box in boxes:  # shapes first, then connections, then tags and names over them, as a sketch does
        d.rectangle(box, outline=INK, fill="white", width=1)
    for _, _, p, q in edges:
        sketch._polyline(d, [p, q], dashed=False, width=style.line_px)
        sketch._arrowhead(d, p, q, hollow=False, size=style.arrow_px, stroke=style.head_stroke)
    for k, box in enumerate(boxes):
        tw = tags[k]
        d.rectangle([box[0] + 1, box[1] + 1, box[0] + tw + 5, box[1] + card.font_px + 3], fill="#e4e4e4")
        d.text((box[0] + 3, box[1] + 1), str(nums[k]), fill="black", font=font)
        d.text((box[0] + tw + 8, box[1] + 1), names[k], fill="black", font=font)
    centers = {nums[k]: [round((b[0] + b[2]) / 2), round((b[1] + b[3]) / 2)] for k, b in enumerate(boxes)}
    return {"arrows": [[nums[a], nums[b]] for a, b, _, _ in edges], "boxes": n, "centers": centers}, ARROWS_PROMPT


# -- answers and scores ----------------------------------------------------------------------------
FOLD = str.maketrans({"‐": "-", "‑": "-", "‒": "-", "–": "-", "—": "-", "−": "-"})


def norm(text: Any) -> str:
    return " ".join(unicodedata.normalize("NFKC", str(text)).translate(FOLD).casefold().split())


def compact(text: Any) -> str:
    return norm(text).replace(" ", "")


def parse(reply: str | None) -> dict[str, Any] | None:
    """The JSON object in a reply, leniently: the first {...} in it, inside a code fence or prose."""
    if not reply:
        return None
    m = re.search(r"\{.*\}", reply, re.DOTALL)
    if not m:
        return None
    try:
        value = json.loads(m.group(0))
    except json.JSONDecodeError:
        return None
    return value if isinstance(value, dict) else None


def score(card: Card, truth: dict[str, Any], answer: dict[str, Any] | None) -> dict[str, Any]:
    """{"score": the share right, and counts by kind of error}. An unreadable answer reads nothing."""
    if card.family == "read":
        expected = [norm(t) for line in truth["lines"] for t in line.split()]
        lines = answer.get("lines") if isinstance(answer, dict) else None
        given = [norm(t) for line in (lines if isinstance(lines, list) else []) for t in str(line).split()]
        matched = sum(b.size for b in SequenceMatcher(None, expected, given, autojunk=False).get_matching_blocks())
        return {"score": round(matched / len(expected), 4), "items": len(expected), "right": matched,
                "unreadable": answer is None}
    expected = [tuple(e) for e in truth["arrows"]]
    left = list(expected)
    counts = {"right": 0, "reversed": 0, "ends_wrong": 0, "spurious": 0}
    arrows = answer.get("arrows") if isinstance(answer, dict) else None
    for a in arrows if isinstance(arrows, list) else []:
        try:
            got = (int(a.get("from")), int(a.get("to")))
        except (AttributeError, TypeError, ValueError):
            counts["spurious"] += 1
            continue
        if got in left:
            left.remove(got)
            counts["right"] += 1
        elif (got[1], got[0]) in left:
            left.remove((got[1], got[0]))
            counts["reversed"] += 1
        elif any(got[0] in e or got[1] in e for e in left):
            counts["ends_wrong"] += 1
        else:
            counts["spurious"] += 1
    return {"score": round(counts["right"] / len(expected), 4), "items": len(expected), "missed": len(left),
            "unreadable": answer is None, **counts}


def perfect(drawn: Drawn) -> dict[str, Any]:
    """The answer of a model that reads everything right (for tests)."""
    if drawn.card.family == "read":
        return {"lines": list(drawn.truth["lines"])}
    return {"arrows": [{"from": a, "to": b} for a, b in drawn.truth["arrows"]]}


def monotone(values: list[float]) -> list[float]:
    """The closest non-decreasing sequence (pool adjacent violators): reading can only get easier
    as text grows, so a dip at one size is averaged with its neighbours."""
    blocks: list[list[float]] = []  # [mean, count]
    for v in values:
        blocks.append([v, 1])
        while len(blocks) > 1 and blocks[-2][0] > blocks[-1][0]:
            (m1, n1), (m2, n2) = blocks.pop(), blocks.pop()
            blocks.append([(m1 * n1 + m2 * n2) / (n1 + n2), n1 + n2])
    return [m for m, n in blocks for _ in range(int(n))]


def threshold(points: list[tuple[float, float]], passing: float = PASS) -> float | None:
    """The size at which reading reaches `passing`, interpolated on the monotone fit of points
    [(size, share read)]; None when even the largest falls short."""
    points = sorted(points)
    sizes, shares = [p for p, _ in points], monotone([s for _, s in points])
    for k, (size, share) in enumerate(zip(sizes, shares, strict=True)):
        if share >= passing:
            if k == 0:
                return float(size)
            s0, sh0 = sizes[k - 1], shares[k - 1]
            return round(s0 + (passing - sh0) / (share - sh0) * (size - s0), 2)
    return None


def card_record(drawn: Drawn) -> dict[str, Any]:
    return {**asdict(drawn.card), "id": drawn.card.id, "truth": drawn.truth}
