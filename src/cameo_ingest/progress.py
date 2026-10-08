"""Progress reporting for long runs (BASE-018).

Each phase of a project (parsing, layouts, rendering, LLM requests, writing) reports how
far it got. On a terminal this is a tqdm bar on stderr. Otherwise, and in any log file, a
heartbeat line is logged every few seconds by a timer thread, so progress keeps showing
even while a single LLM request is blocking.

On a terminal, the bars stay as its last lines while the log scrolls above them (RN-003):
while a command runs, stderr is `AboveBars` (`console`), which writes each line with
`tqdm.write`: the bars are cleared, the line written, and the bars drawn again below it.
"""

from __future__ import annotations

import io
import logging
import sys
import threading
import time
from collections.abc import Iterator
from contextlib import contextmanager
from typing import Any, TextIO

log = logging.getLogger(__name__)


def _duration(seconds: float) -> str:
    seconds = int(seconds)
    if seconds < 60:
        return f"{seconds} s"
    if seconds < 3600:
        return f"{seconds // 60} min {seconds % 60} s"
    return f"{seconds // 3600} h {seconds % 3600 // 60} min"


class AboveBars(io.TextIOBase):
    """Stderr while bars may be shown: each whole line written above the bars (RN-003)."""

    def __init__(self, real: TextIO):
        self.real = real
        self._buf = ""
        self._lock = threading.Lock()

    def writable(self) -> bool:
        return True

    def write(self, s: str) -> int:
        from tqdm import tqdm

        with self._lock:
            self._buf += s
            *lines, self._buf = self._buf.split("\n")
            for line in lines:
                tqdm.write(line, file=self.real)
        return len(s)

    def flush(self) -> None:
        self.real.flush()

    def finish(self) -> None:
        """Write what is left of a line."""
        with self._lock:
            if self._buf:
                self.real.write(self._buf)
                self._buf = ""
        self.real.flush()

    def isatty(self) -> bool:
        return self.real.isatty()

    def fileno(self) -> int:
        return self.real.fileno()

    @property
    def encoding(self) -> str:  # type: ignore[override]
        return getattr(self.real, "encoding", "utf-8")


@contextmanager
def console() -> Iterator[None]:
    """On a terminal, stderr above the bars for the duration (`AboveBars`); elsewhere, as it is.
    Set it up before the log's console handler, which then writes through it."""
    real = sys.stderr
    if not real.isatty():
        yield
        return
    above = AboveBars(real)
    sys.stderr = above
    try:
        yield
    finally:
        above.finish()
        sys.stderr = real


def _terminal() -> TextIO:
    """Where bars are drawn: the terminal itself, not `AboveBars`."""
    return getattr(sys.stderr, "real", sys.stderr)


class Phase:
    def __init__(self, label: str, total: int | None, unit: str):
        self.label, self.total, self.unit = label, total, unit
        self.done = 0
        self.note = ""  # what the phase is on now ("TMT.mdzip (27 MB): fingerprinting"), shown with its progress
        self.started = time.monotonic()
        self._bar: Any = None
        self._lock = threading.Lock()

    def advance(self, n: int = 1) -> None:
        with self._lock:
            self.done += n
        if self._bar is not None:
            self._bar.update(n)

    def set_note(self, note: str) -> None:
        self.note = note
        if self._bar is not None:
            self._bar.set_postfix_str(note[:80], refresh=True)

    def amount(self, n: int) -> str:
        if self.unit == "B":
            return f"{n / 1e6:,.1f} MB"
        return f"{n:,} {self.unit}{'' if n == 1 else 'es' if self.unit.endswith(('ch', 'sh', 's', 'x')) else 's'}"

    def status(self) -> str:
        elapsed = time.monotonic() - self.started
        s = f"{self.label}: {self.amount(self.done)}"
        if self.total:
            s += f" of {self.amount(self.total)} ({100 * self.done // self.total}%)"
        s += f", {_duration(elapsed)} elapsed"
        if self.total and self.done:
            s += f", about {_duration(elapsed * (self.total - self.done) / self.done)} left"
        if self.note:
            s += f"; now: {self.note}"
        return s


class Progress:
    """`bars=None` shows bars when stderr is a terminal. `heartbeat` is the interval in
    seconds between heartbeat lines (0: none)."""

    def __init__(self, heartbeat: float = 30.0, bars: bool | None = None):
        self.heartbeat = heartbeat
        self.bars = sys.stderr.isatty() if bars is None else bars

    @contextmanager
    def phase(self, label: str, total: int | None = None, unit: str = "item") -> Iterator[Phase]:
        ph = Phase(label, total, unit)
        if self.bars:
            from tqdm import tqdm

            ph._bar = tqdm(total=total, desc=label, unit=unit, unit_scale=unit == "B", leave=False,
                           file=_terminal(), dynamic_ncols=True)
        # With bars on screen, heartbeats only go to a log file (DEBUG).
        level = logging.DEBUG if self.bars else logging.INFO
        stop = threading.Event()
        beat = None
        if self.heartbeat > 0 or ph._bar is not None:
            def run() -> None:
                # A bar redraws once a second, so that its elapsed time moves while one item takes long.
                tick = 1.0 if ph._bar is not None else self.heartbeat
                last = time.monotonic()
                while not stop.wait(tick):
                    if ph._bar is not None:
                        ph._bar.refresh()
                    if self.heartbeat > 0 and time.monotonic() - last >= self.heartbeat:
                        last = time.monotonic()
                        log.log(level, "%s", ph.status())

            beat = threading.Thread(target=run, name=f"heartbeat {label}", daemon=True)
            beat.start()
        try:
            yield ph
        finally:
            stop.set()
            if beat is not None:
                beat.join()
            if ph._bar is not None:
                ph._bar.close()
        log.info("%s: %s in %s", label, ph.amount(ph.done), _duration(time.monotonic() - ph.started))


QUIET = Progress(heartbeat=0, bars=False)
