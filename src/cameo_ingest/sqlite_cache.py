"""An SQLite file of answers worth keeping (LLM responses, embeddings, rerank scores), shared by
request threads through one connection under a lock (AR-017R2).

A file that is not a database, or is damaged, is moved aside and a new one started: a cache is
worth less than the run that uses it (BASE-005).
"""

from __future__ import annotations

import logging
import sqlite3
import threading
import time
from pathlib import Path

log = logging.getLogger(__name__)


class SqliteCache:
    SCHEMA = ""  # CREATE ... IF NOT EXISTS statements
    WAL = False  # write-ahead logging, for caches written by many threads in bulk
    WHAT = "cache"  # for messages

    def __init__(self, path: Path, readonly: bool = False):
        self.path = path
        self._lock = threading.Lock()  # one connection, shared by the request threads
        if readonly:
            if not path.is_file():
                raise FileNotFoundError(f"{self.WHAT} {path} not found")
            self._db = sqlite3.connect(f"file:{path}?mode=ro", uri=True, check_same_thread=False)
            return
        path.parent.mkdir(parents=True, exist_ok=True)
        try:
            self._db = self._open(path)
        except sqlite3.DatabaseError as e:  # not a database, or damaged
            aside = path.with_name(f"{path.name}.corrupt-{int(time.time())}")
            path.replace(aside)
            log.warning("%s %s is unreadable (%s); moved it to %s and started a new one", self.WHAT, path, e, aside)
            self._db = self._open(path)

    def _open(self, path: Path) -> sqlite3.Connection:
        db = sqlite3.connect(path, timeout=30, check_same_thread=False)
        try:
            if self.WAL:
                db.execute("PRAGMA journal_mode=WAL")
            db.executescript(self.SCHEMA)
        except sqlite3.DatabaseError:
            db.close()
            raise
        return db

    def close(self) -> None:
        with self._lock:
            self._db.close()
