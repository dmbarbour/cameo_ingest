"""Working through an output tree's task list (plan RI-04).

A run checks every input for changes, scans the pending ones and records the Cameo
projects (contents) found in them, then builds each content that has no up-to-date output:
in `by-sha256/.work/<sha256>/`, published by one rename to `by-sha256/<sha256>/` and one
transaction in state.sqlite. Finally the root files are rebuilt and run.json exported.
Everything recorded is committed as it happens, so a stopped run loses at most the
project it was building.
"""

from __future__ import annotations

import json
import logging
import shutil
import uuid
from collections import defaultdict
from pathlib import Path
from typing import Any

from . import exports
from .archive import UnsupportedInput, discover
from .llm import LLM
from .pipeline import ingest_project
from .progress import Progress
from .provenance import TOOL, ContentInfo, sha256_bytes, sha256_text, utc_now
from .state import State

log = logging.getLogger(__name__)
announce = logging.getLogger("cameo_ingest.progress")  # shown at any verbosity, like heartbeats

WORK = ".work"


def options_hash(options: dict[str, Any]) -> str:
    """Of the options that change a project's output (rendering, models, call budget)."""
    return sha256_text(json.dumps(options, sort_keys=True))[:16]


class Runner:
    def __init__(self, state: State, out: Path, llm: LLM, options: dict[str, Any], progress: Progress,
                 concurrency: int = 1):
        self.state, self.out, self.llm, self.progress = state, out, llm, progress
        self.options = options
        self.opt_hash = options_hash(options)
        self.concurrency = concurrency
        self.projects_dir = out / exports.PROJECTS
        self.failed_inputs: list[str] = []
        self.failed_projects: list[str] = []
        self.written: list[str] = []

    def run(self, command: list[str]) -> int:
        run_id = uuid.uuid4().hex
        self.state.start_run(run_id, command)
        outcome = "failed"
        try:
            self.check_inputs()
            self.scan()
            self.build()
            outcome = "finished"
        except KeyboardInterrupt:
            outcome = "interrupted"
            self.llm.close()
            raise
        finally:
            exports.rebuild(self.state, self.out)
            self.state.finish_run(run_id, outcome, self.llm.report())
            self.write_run_json(run_id)
        if self.failed_projects:
            return 4
        return 3 if self.failed_inputs else 0

    # -- inputs ------------------------------------------------------------------
    def check_inputs(self) -> None:
        """Missing inputs are flagged (their projects stay); changed or failed ones are
        queued again."""
        for row in self.state.inputs():
            path = Path(row["path"])
            if not path.is_file():
                if row["status"] != "missing":
                    log.warning("input %s is missing; its projects are kept (`prune` removes them)", path)
                    self.state.update_input(row["id"], status="missing")
                continue
            st = path.stat()
            changed = (st.st_size, st.st_mtime_ns) != (row["size"], row["mtime_ns"])
            if row["status"] in ("missing", "failed") or (row["status"] == "done" and changed):
                self.state.update_input(row["id"], status="pending")

    def scan(self) -> None:
        pending = self.state.inputs("pending")
        if pending:
            with self.progress.phase("scanning inputs", len(pending), "input") as ph:
                for row in pending:
                    self.scan_input(row)
                    ph.advance()

    def scan_input(self, row: Any) -> None:
        """Hash an input and record the projects in it (unless this version was scanned before)."""
        path = Path(row["path"])
        try:
            data = path.read_bytes()
        except OSError as e:
            self._input_failed(row, f"cannot read: {e}")
            return
        sha = sha256_bytes(data)
        st = path.stat()
        known = self.state.db.execute("SELECT 1 FROM sightings WHERE input_id = ? AND input_sha256 = ? LIMIT 1",
                                      (row["id"], sha)).fetchone()
        if known is None:  # new or changed content: find the projects in it
            try:
                projects = list(discover(data, path.name))
            except UnsupportedInput as e:
                self._input_failed(row, str(e))
                return
            if not projects:
                self._input_failed(row, "no Cameo/XMI model found")
                return
            with self.state.tx():
                for p in projects:
                    self.state.record_sighting(p.sha256, p.display_name, p.kind, p.data_size, row["id"], sha, p.chain)
            log.info("found %d project(s) in %s", len(projects), path.name)
        self.state.update_input(row["id"], status="done", size=st.st_size, mtime_ns=st.st_mtime_ns, sha256=sha,
                                processed=utc_now(), error=None)

    def _input_failed(self, row: Any, error: str) -> None:
        log.error("input %s: %s", row["path"], error)
        self.state.update_input(row["id"], status="failed", processed=utc_now(), error=error)
        self.failed_inputs.append(row["path"])

    # -- projects --------------------------------------------------------------
    def todo(self) -> dict[str, list[tuple[str, str]]]:
        """Contents without up-to-date output, grouped by an input to read them from:
        {input path: [(content sha256, input sha256)]}."""
        rows = self.state.db.execute(
            "SELECT c.sha256 FROM contents c LEFT JOIN projects p ON p.content_sha256 = c.sha256 "
            "WHERE p.status IS NULL OR p.status != 'written' OR p.tool != ? OR p.options_hash != ? "
            "ORDER BY c.name, c.sha256", (TOOL, self.opt_hash)).fetchall()
        by_input: dict[str, list[tuple[str, str]]] = defaultdict(list)
        for (sha,) in rows:
            where = next((s for s in self.state.sightings(sha) if s["input_status"] == "done"), None)
            if where is not None:  # otherwise only seen in missing or old inputs: nothing to read
                by_input[where["path"]].append((sha, where["input_sha256"]))
        return by_input

    def build(self) -> None:
        todo = self.todo()
        total = sum(len(items) for items in todo.values())
        resumed = self.state.db.execute(
            "SELECT count(*) FROM projects WHERE status = 'working' AND tool = ? AND options_hash = ?",
            (TOOL, self.opt_hash)).fetchone()[0]
        announce.info("%d project(s) to build%s, %d up to date", total, f" ({resumed} resumed)" if resumed else "",
                      self._current_written())
        if not total:
            return
        with self.progress.phase("projects", total, "project") as ph:
            for path_str, items in todo.items():
                path = Path(path_str)
                data = path.read_bytes()
                if sha256_bytes(data) != items[0][1]:  # changed since it was scanned: next run
                    log.warning("input %s changed during the run; it will be scanned again", path)
                    row = self.state.db.execute("SELECT id FROM inputs WHERE path = ?", (path_str,)).fetchone()
                    self.state.update_input(row["id"], status="pending")
                    ph.advance(len(items))
                    continue
                found = {p.sha256: p for p in discover(data, path.name)}
                for sha, _ in items:
                    if sha in found:
                        self.build_project(found[sha])
                    else:  # e.g. a nested member that could not be read this time
                        self.state.set_project(sha, "failed", error=f"no longer found in {path.name}")
                        self.failed_projects.append(sha)
                    ph.advance()

    def _current_written(self) -> int:
        """Written projects made with this tool version and these options."""
        return self.state.db.execute("SELECT count(*) FROM projects WHERE status = 'written' AND tool = ? "
                                     "AND options_hash = ?", (TOOL, self.opt_hash)).fetchone()[0]

    def build_project(self, project: Any) -> None:
        sha = project.sha256
        content = ContentInfo(sha, self.state.content(sha)["name"])
        work = self.projects_dir / WORK / sha
        row = self.state.project(sha)
        resumable = row is not None and row["status"] == "working" and (row["tool"], row["options_hash"]) == (
            TOOL, self.opt_hash)
        if work.exists() and not resumable:
            shutil.rmtree(work)
        self.state.set_project(sha, "working", tool=TOOL, options_hash=self.opt_hash, error=None)
        try:
            result = ingest_project(content, project, work, self.llm, render=self.options["render"],
                                    progress=self.progress, concurrency=self.concurrency,
                                    image_size=self.options["image_size"])
        except Exception as e:  # one bad project must not stop the others (BASE-004)
            log.error("project %s (sha256:%s) failed: %s: %s", content.name, sha[:16], type(e).__name__, e)
            log.debug("traceback for %s", content.name, exc_info=True)
            self.state.set_project(sha, "failed", error=f"{type(e).__name__}: {e}")
            self.failed_projects.append(sha)
            return
        files = sorted((str(f.relative_to(work)), sha256_bytes(f.read_bytes())) for f in work.rglob("*") if f.is_file())
        final = self.projects_dir / sha
        old = work.with_name(f"{sha}.old")
        if old.exists():
            shutil.rmtree(old)
        if final.exists():
            final.rename(old)
        work.rename(final)
        self.state.publish(sha, TOOL, self.opt_hash, result.summary, files)
        if old.exists():
            shutil.rmtree(old)
        self.written.append(sha)

    # -- run record ------------------------------------------------------------
    def write_run_json(self, run_id: str) -> None:
        run = self.state.run(run_id)
        record = {
            "run_id": run_id, "started": run["started"], "finished": run["finished"], "outcome": run["outcome"],
            "tool": TOOL, "command": json.loads(run["command"]), "options": self.options,
            "projects": {"written": len(self.written), "failed": len(self.failed_projects)},
            "failed_inputs": self.failed_inputs,
            "llm": self.llm.report(),
        }
        (self.out / "run.json").write_text(json.dumps(record, ensure_ascii=False, indent=1), encoding="utf-8")


# -- tree commands -----------------------------------------------------------------
def status(state: State) -> dict[str, Any]:
    """What an output tree holds, for `status` (reads only: works while a run is going)."""
    db = state.db
    run = db.execute("SELECT * FROM runs ORDER BY started DESC, rowid DESC LIMIT 1").fetchone()
    return {
        "inputs": {
            "counts": dict(db.execute("SELECT status, count(*) FROM inputs GROUP BY status").fetchall()),
            "problems": [{"path": r["path"], "status": r["status"], "error": r["error"]}
                         for r in state.inputs("failed", "missing")],
        },
        "projects": {
            "counts": dict(db.execute("SELECT status, count(*) FROM project_status GROUP BY status").fetchall()),
            "failed": [{"token": f"sha256:{r['sha256']}", "name": r["name"], "error": r["error"]}
                       for r in db.execute("SELECT * FROM project_status WHERE status = 'failed' ORDER BY name")],
        },
        "latest_run": None if run is None else {
            "id": run["id"], "started": run["started"], "finished": run["finished"], "outcome": run["outcome"],
            "llm_calls": json.loads(run["llm"])["calls"] if run["llm"] else None,
        },
    }


def prune(state: State, out: Path, dry_run: bool = False) -> dict[str, Any]:
    """Drop missing inputs, sightings in old versions of changed inputs, and the contents
    that no existing input contains any more, with their output (plan decision 3)."""
    db = state.db
    missing = [r["path"] for r in state.inputs("missing")]
    orphans = db.execute(
        "SELECT sha256, name FROM contents c WHERE NOT EXISTS (SELECT 1 FROM current_sightings v "
        "WHERE v.content_sha256 = c.sha256 AND v.input_status != 'missing') ORDER BY name, sha256").fetchall()
    if not dry_run:
        with state.tx():
            db.execute("DELETE FROM inputs WHERE status = 'missing'")
            db.execute("DELETE FROM sightings WHERE NOT EXISTS (SELECT 1 FROM inputs i "
                       "WHERE i.id = sightings.input_id AND i.sha256 = sightings.input_sha256)")
            db.executemany("DELETE FROM contents WHERE sha256 = ?", [(r["sha256"],) for r in orphans])
        projects = out / exports.PROJECTS
        for r in orphans:
            for d in (projects / r["sha256"], projects / WORK / r["sha256"]):
                if d.exists():
                    shutil.rmtree(d)
        exports.rebuild(state, out)
    return {"inputs": missing, "projects": [{"token": f"sha256:{r['sha256']}", "name": r["name"]} for r in orphans]}
