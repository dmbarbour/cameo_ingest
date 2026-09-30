"""Progress reporting for long runs (BASE-018).

Each phase of a project (parsing, layouts, rendering, LLM requests, writing) reports how
far it got. On a terminal this is a tqdm bar on stderr. Otherwise, and in any log file, a
heartbeat line is logged every few seconds by a timer thread, so progress keeps showing
even while a single LLM request is blocking.
"""

from __future__ import annotations

import logging
import sys
import threading
import time
from collections.abc import Iterator
from contextlib import contextmanager
from typing import Any

log = logging.getLogger(__name__)


def _duration(seconds: float) -> str:
    seconds = int(seconds)
    if seconds < 60:
        return f"{seconds} s"
    if seconds < 3600:
        return f"{seconds // 60} min {seconds % 60} s"
    return f"{seconds // 3600} h {seconds % 3600 // 60} min"


class Phase:
    def __init__(self, label: str, total: int | None, unit: str):
        self.label, self.total, self.unit = label, total, unit
        self.done = 0
        self.started = time.monotonic()
        self._bar: Any = None
        self._lock = threading.Lock()

    def advance(self, n: int = 1) -> None:
        with self._lock:
            self.done += n
        if self._bar is not None:
            self._bar.update(n)

    def amount(self, n: int) -> str:
        if self.unit == "B":
            return f"{n / 1e6:,.1f} MB"
        return f"{n:,} {self.unit}{'' if n == 1 else 's'}"

    def status(self) -> str:
        elapsed = time.monotonic() - self.started
        s = f"{self.label}: {self.amount(self.done)}"
        if self.total:
            s += f" of {self.amount(self.total)} ({100 * self.done // self.total}%)"
        s += f", {_duration(elapsed)} elapsed"
        if self.total and self.done:
            s += f", about {_duration(elapsed * (self.total - self.done) / self.done)} left"
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
                           file=sys.stderr, dynamic_ncols=True)
        # With bars on screen, heartbeats only go to a log file (DEBUG).
        level = logging.DEBUG if self.bars else logging.INFO
        stop = threading.Event()
        beat = None
        if self.heartbeat > 0:
            def run() -> None:
                while not stop.wait(self.heartbeat):
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
