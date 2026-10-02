"""The durable state of an output tree (plan RI-01).

`OUT/state.sqlite` holds the task list of inputs, the contents (Cameo projects) found in
them, where each content was seen, what has been written, the runs, and the tree's
settings. Every change is committed at once, so the database always describes work that
really finished, and a stopped run can continue from it. It is plain SQLite, meant to be
queried directly; the README documents the tables and views.
"""

from __future__ import annotations

import json
import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Any

from .provenance import utc_now

STATE_FILE = "state.sqlite"
LOCK_FILE = "state.lock"
SCHEMA_VERSION = 1

SCHEMA = """
CREATE TABLE IF NOT EXISTS meta (key TEXT PRIMARY KEY, value TEXT NOT NULL);

-- The task list: one row per input file (adding a directory adds the files under it).
CREATE TABLE IF NOT EXISTS inputs (
    id INTEGER PRIMARY KEY,
    path TEXT NOT NULL UNIQUE,                    -- absolute
    status TEXT NOT NULL DEFAULT 'pending'
        CHECK (status IN ('pending', 'done', 'failed', 'missing')),
    metadata TEXT NOT NULL DEFAULT '{}',          -- --meta values (JSON object)
    size INTEGER, mtime_ns INTEGER, sha256 TEXT,  -- the file as last processed
    added TEXT NOT NULL, processed TEXT, error TEXT
);

-- Each Cameo project, identified by the sha256 of its own bytes.
CREATE TABLE IF NOT EXISTS contents (
    sha256 TEXT PRIMARY KEY,
    name TEXT NOT NULL,                           -- file name under which it was first seen
    kind TEXT NOT NULL,                           -- 'zip' or 'xmi'
    size INTEGER NOT NULL,
    first_seen TEXT NOT NULL
);

-- Where each content was found: in which version of which input, down which archive chain.
CREATE TABLE IF NOT EXISTS sightings (
    content_sha256 TEXT NOT NULL REFERENCES contents(sha256) ON DELETE CASCADE,
    input_id INTEGER NOT NULL REFERENCES inputs(id) ON DELETE CASCADE,
    input_sha256 TEXT NOT NULL,
    chain TEXT NOT NULL,                          -- JSON list of archive members, input to project
    seen TEXT NOT NULL,
    PRIMARY KEY (content_sha256, input_id, input_sha256, chain)
);

-- The output of each content under by-sha256/<sha256>/.
CREATE TABLE IF NOT EXISTS projects (
    content_sha256 TEXT PRIMARY KEY REFERENCES contents(sha256) ON DELETE CASCADE,
    status TEXT NOT NULL CHECK (status IN ('pending', 'working', 'written', 'failed')),
    tool TEXT, options_hash TEXT,                 -- what the output (or work in progress) was made with
    summary TEXT, error TEXT, updated TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS files (
    content_sha256 TEXT NOT NULL REFERENCES projects(content_sha256) ON DELETE CASCADE,
    path TEXT NOT NULL,                           -- relative to the project directory
    sha256 TEXT NOT NULL,
    PRIMARY KEY (content_sha256, path)
);

CREATE TABLE IF NOT EXISTS runs (
    id TEXT PRIMARY KEY, started TEXT NOT NULL, finished TEXT,
    command TEXT NOT NULL,                        -- JSON list of arguments
    outcome TEXT,                                 -- 'finished', 'interrupted', 'failed'
    llm TEXT                                      -- JSON: calls, outcomes, incomplete items
);

-- The tree's run settings (models, rendering, --env path...). Never secrets.
CREATE TABLE IF NOT EXISTS settings (key TEXT PRIMARY KEY, value TEXT NOT NULL);

-- Sightings in the current version of each input (missing inputs included, flagged).
CREATE VIEW IF NOT EXISTS current_sightings AS
    SELECT s.content_sha256, c.name, i.id AS input_id, i.path, i.status AS input_status,
           i.metadata, s.input_sha256, s.chain
    FROM sightings s
    JOIN inputs i ON i.id = s.input_id AND i.sha256 = s.input_sha256
    JOIN contents c ON c.sha256 = s.content_sha256;

-- Every content with the state of its output and how often it is currently seen.
CREATE VIEW IF NOT EXISTS project_status AS
    SELECT c.sha256, c.name, COALESCE(p.status, 'pending') AS status, p.error, p.updated,
           (SELECT count(*) FROM current_sightings v WHERE v.content_sha256 = c.sha256) AS sightings
    FROM contents c LEFT JOIN projects p ON p.content_sha256 = c.sha256;
"""


class StateError(Exception):
    pass


class State:
    def __init__(self, out: Path):
        self.out = out
        self.path = out / STATE_FILE
        out.mkdir(parents=True, exist_ok=True)
        self.db = sqlite3.connect(self.path, timeout=30, isolation_level=None)  # autocommit; see tx()
        self.db.row_factory = sqlite3.Row
        self.db.execute("PRAGMA journal_mode = WAL")  # `status` can read while a run writes
        self.db.execute("PRAGMA foreign_keys = ON")
        self.db.executescript(SCHEMA)
        row = self.db.execute("SELECT value FROM meta WHERE key = 'schema_version'").fetchone()
        if row is None:
            self.db.execute("INSERT INTO meta VALUES ('schema_version', ?)", (str(SCHEMA_VERSION),))
        elif int(row[0]) > SCHEMA_VERSION:
            raise StateError(f"{self.path} was made by a newer cameo-ingest (schema {row[0]})")
        self._lock_fd: Any = None

    @staticmethod
    def exists(out: Path) -> bool:
        return (out / STATE_FILE).is_file()

    def close(self) -> None:
        self.unlock()
        self.db.close()

    @contextmanager
    def tx(self) -> Iterator[sqlite3.Connection]:
        """One transaction: all of it is committed, or none of it."""
        self.db.execute("BEGIN IMMEDIATE")
        try:
            yield self.db
        except BaseException:
            self.db.execute("ROLLBACK")
            raise
        self.db.execute("COMMIT")

    # -- lock -------------------------------------------------------------------
    def lock(self) -> None:
        """Take the output tree for this process; fails at once if another run has it."""
        try:
            import fcntl
        except ImportError:  # not POSIX: go without the lock
            return
        fd = (self.out / LOCK_FILE).open("a")
        try:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            fd.close()
            raise StateError(f"another cameo-ingest run is using {self.out}") from None
        self._lock_fd = fd

    def unlock(self) -> None:
        if self._lock_fd is not None:
            self._lock_fd.close()  # closing releases the flock
            self._lock_fd = None

    # -- inputs (the task list) -----------------------------------------------
    def add_input(self, path: Path, metadata: dict[str, Any]) -> bool:
        """Add a file to the task list, or mark it pending again with new metadata.
        Returns True if the path was new."""
        meta = json.dumps(metadata, sort_keys=True, ensure_ascii=False)
        row = self.db.execute("SELECT id, metadata FROM inputs WHERE path = ?", (str(path),)).fetchone()
        if row is None:
            self.db.execute("INSERT INTO inputs (path, metadata, added) VALUES (?, ?, ?)",
                            (str(path), meta, utc_now()))
            return True
        if row["metadata"] != meta:
            self.db.execute("UPDATE inputs SET metadata = ?, status = 'pending' WHERE id = ?", (meta, row["id"]))
        return False

    def inputs(self, *statuses: str) -> list[sqlite3.Row]:
        if statuses:
            marks = ", ".join("?" * len(statuses))
            return self.db.execute(f"SELECT * FROM inputs WHERE status IN ({marks}) ORDER BY id", statuses).fetchall()
        return self.db.execute("SELECT * FROM inputs ORDER BY id").fetchall()

    def update_input(self, input_id: int, **fields: Any) -> None:
        cols = ", ".join(f"{k} = ?" for k in fields)
        self.db.execute(f"UPDATE inputs SET {cols} WHERE id = ?", (*fields.values(), input_id))

    # -- contents and sightings -----------------------------------------------
    def record_sighting(self, sha256: str, name: str, kind: str, size: int, input_id: int, input_sha256: str,
                        chain: tuple[str, ...]) -> bool:
        """Record content found in an input. Returns True if the content was new."""
        new = self.db.execute("INSERT OR IGNORE INTO contents VALUES (?, ?, ?, ?, ?)",
                              (sha256, name, kind, size, utc_now())).rowcount == 1
        self.db.execute("INSERT OR IGNORE INTO sightings VALUES (?, ?, ?, ?, ?)",
                        (sha256, input_id, input_sha256, json.dumps(list(chain), ensure_ascii=False), utc_now()))
        return new

    def content(self, sha256: str) -> sqlite3.Row | None:
        return self.db.execute("SELECT * FROM contents WHERE sha256 = ?", (sha256,)).fetchone()

    def sightings(self, sha256: str) -> list[sqlite3.Row]:
        return self.db.execute("SELECT * FROM current_sightings WHERE content_sha256 = ? ORDER BY path, chain",
                               (sha256,)).fetchall()

    # -- projects --------------------------------------------------------------
    def project(self, sha256: str) -> sqlite3.Row | None:
        return self.db.execute("SELECT * FROM projects WHERE content_sha256 = ?", (sha256,)).fetchone()

    def set_project(self, sha256: str, status: str, **fields: Any) -> None:
        fields = {"status": status, "updated": utc_now(), **fields}
        cols = ", ".join(fields)
        marks = ", ".join("?" * len(fields))
        updates = ", ".join(f"{k} = excluded.{k}" for k in fields)
        self.db.execute(f"INSERT INTO projects (content_sha256, {cols}) VALUES (?, {marks}) "
                        f"ON CONFLICT (content_sha256) DO UPDATE SET {updates}", (sha256, *fields.values()))

    def publish(self, sha256: str, tool: str, options_hash: str, summary: dict[str, Any],
                files: list[tuple[str, str]]) -> None:
        """Mark a project written, with its files, in one transaction."""
        with self.tx() as db:
            self.set_project(sha256, "written", tool=tool, options_hash=options_hash,
                             summary=json.dumps(summary, ensure_ascii=False), error=None)
            db.execute("DELETE FROM files WHERE content_sha256 = ?", (sha256,))
            db.executemany("INSERT INTO files VALUES (?, ?, ?)", [(sha256, p, h) for p, h in files])

    def written(self) -> list[sqlite3.Row]:
        """Written projects with their content, in a stable order."""
        return self.db.execute(
            "SELECT p.*, c.name, c.kind, c.size FROM projects p JOIN contents c ON c.sha256 = p.content_sha256 "
            "WHERE p.status = 'written' ORDER BY c.name, c.sha256").fetchall()

    def files(self, sha256: str) -> list[sqlite3.Row]:
        return self.db.execute("SELECT path, sha256 FROM files WHERE content_sha256 = ? ORDER BY path",
                               (sha256,)).fetchall()

    # -- runs and settings -----------------------------------------------------
    def start_run(self, run_id: str, command: list[str]) -> None:
        self.db.execute("INSERT INTO runs (id, started, command) VALUES (?, ?, ?)",
                        (run_id, utc_now(), json.dumps(command, ensure_ascii=False)))

    def finish_run(self, run_id: str, outcome: str, llm: dict[str, Any]) -> None:
        self.db.execute("UPDATE runs SET finished = ?, outcome = ?, llm = ? WHERE id = ?",
                        (utc_now(), outcome, json.dumps(llm, ensure_ascii=False), run_id))

    def run(self, run_id: str) -> sqlite3.Row | None:
        return self.db.execute("SELECT * FROM runs WHERE id = ?", (run_id,)).fetchone()

    # -- what the runner, the CLI and the root files ask (AR-024) ----------------------------------
    def has_sighting(self, input_id: int, input_sha256: str) -> bool:
        """Whether this version of an input has been read for its projects."""
        return self.db.execute("SELECT 1 FROM sightings WHERE input_id = ? AND input_sha256 = ? LIMIT 1",
                               (input_id, input_sha256)).fetchone() is not None

    def stale_contents(self, tool: str, options_hash: str) -> list[str]:
        """Contents whose output is missing, failed or unfinished, or made by another tool or options."""
        return [r[0] for r in self.db.execute(
            "SELECT c.sha256 FROM contents c LEFT JOIN projects p ON p.content_sha256 = c.sha256 "
            "WHERE p.status IS NULL OR p.status != 'written' OR p.tool != ? OR p.options_hash != ? "
            "ORDER BY c.name, c.sha256", (tool, options_hash))]

    def count_projects(self, status: str, tool: str, options_hash: str) -> int:
        return self.db.execute("SELECT count(*) FROM projects WHERE status = ? AND tool = ? AND options_hash = ?",
                               (status, tool, options_hash)).fetchone()[0]

    def input_id(self, path: str) -> int | None:
        row = self.db.execute("SELECT id FROM inputs WHERE path = ?", (path,)).fetchone()
        return row["id"] if row else None

    def project_rows(self, status: str | None = None) -> list[sqlite3.Row]:
        """Every content and the state of its project, by name; or those in one state."""
        if status is None:
            return self.db.execute("SELECT * FROM project_status ORDER BY name, sha256").fetchall()
        return self.db.execute("SELECT * FROM project_status WHERE status = ? ORDER BY name, sha256",
                               (status,)).fetchall()

    def counts(self, what: str) -> dict[str, int]:
        """Inputs ("inputs") or projects ("projects") by status."""
        table = {"inputs": "inputs", "projects": "project_status"}[what]
        return dict(self.db.execute(f"SELECT status, count(*) FROM {table} GROUP BY status").fetchall())

    def latest_run(self) -> sqlite3.Row | None:
        return self.db.execute("SELECT * FROM runs ORDER BY started DESC, rowid DESC LIMIT 1").fetchone()

    def orphans(self) -> list[sqlite3.Row]:
        """Contents that no existing input contains any more."""
        return self.db.execute(
            "SELECT sha256, name FROM contents c WHERE NOT EXISTS (SELECT 1 FROM current_sightings v "
            "WHERE v.content_sha256 = c.sha256 AND v.input_status != 'missing') ORDER BY name, sha256").fetchall()

    def prune(self, orphans: list[str]) -> None:
        """Drop missing inputs, sightings in old versions of changed inputs, and these contents."""
        with self.tx() as db:
            db.execute("DELETE FROM inputs WHERE status = 'missing'")
            db.execute("DELETE FROM sightings WHERE NOT EXISTS (SELECT 1 FROM inputs i "
                       "WHERE i.id = sightings.input_id AND i.sha256 = sightings.input_sha256)")
            db.executemany("DELETE FROM contents WHERE sha256 = ?", [(sha,) for sha in orphans])

    def settings(self) -> dict[str, Any]:
        return {r["key"]: json.loads(r["value"]) for r in self.db.execute("SELECT * FROM settings")}

    def save_settings(self, settings: dict[str, Any]) -> None:
        with self.tx() as db:
            db.execute("DELETE FROM settings")
            db.executemany("INSERT INTO settings VALUES (?, ?)",
                           [(k, json.dumps(v)) for k, v in sorted(settings.items())])
