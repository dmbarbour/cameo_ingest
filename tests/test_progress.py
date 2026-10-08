"""The console on a terminal: the log written above the progress bars (RN-003)."""

from __future__ import annotations

import io
import sys

from tqdm import tqdm

from cameo_ingest import progress


class Terminal(io.StringIO):
    def isatty(self) -> bool:
        return True


def test_lines_are_written_above_the_bars(monkeypatch):
    """Each whole line goes through `tqdm.write`, which clears the bars, writes it and draws them
    again; what is left of a line waits for its end, or for the command's."""
    term = Terminal()
    written: list[str] = []
    real_write = tqdm.write
    monkeypatch.setattr(tqdm, "write", lambda s, file=None, **kw: (written.append(s), real_write(s, file=file)))
    monkeypatch.setattr(sys, "stderr", term)
    with progress.console():
        assert isinstance(sys.stderr, progress.AboveBars) and sys.stderr.isatty()
        assert progress._terminal() is term  # the bars are drawn on the terminal itself
        print("WARNING one", file=sys.stderr)
        sys.stderr.write("two, then ")
        assert written == ["WARNING one"]
        sys.stderr.write("three\nfour")
    assert written == ["WARNING one", "two, then three"]
    assert sys.stderr is term and term.getvalue() == "WARNING one\ntwo, then three\nfour"


def test_not_a_terminal_is_left_alone(monkeypatch):
    plain = io.StringIO()
    monkeypatch.setattr(sys, "stderr", plain)
    with progress.console():
        assert sys.stderr is plain
