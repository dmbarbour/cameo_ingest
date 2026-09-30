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
