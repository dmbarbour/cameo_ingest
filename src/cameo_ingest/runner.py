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
import time
import uuid
from collections import defaultdict
from collections.abc import Callable
from pathlib import Path
from typing import Any

from . import exports, subjects
from .archive import UnsupportedInput, discover
from .config import ProjectOptions
from .fingerprint import fingerprint
from .llm import EnrichmentSession
from .pipeline import ingest_project
from .progress import Progress
from .provenance import TOOL, ContentInfo, sha256_bytes, utc_now
from .sketch import SketchStyle
from .state import State

log = logging.getLogger(__name__)
announce = logging.getLogger("cameo_ingest.progress")  # shown at any verbosity, like heartbeats

WORK = ".work"


class Runner:
    def __init__(self, state: State, out: Path, llm: EnrichmentSession, options: ProjectOptions, progress: Progress,
                 concurrency: int = 1, prepare: Callable[[], ProjectOptions] | None = None):
        self.state, self.out, self.llm, self.progress = state, out, llm, progress
        self.options = options
        self.opt_hash = options.hash()
        self.prepare = prepare  # after the scan, before building: the options, perhaps calibrated (plan VA)
        self.concurrency = concurrency
        self.projects_dir = out / exports.PROJECTS
        self.failed_inputs: list[str] = []
        self.failed_projects: list[str] = []
        self.written: list[str] = []
        self.subjects: dict[str, Any] = {}

    def run(self, command: list[str]) -> int:
        run_id = uuid.uuid4().hex
        self.state.start_run(run_id, command)
        outcome = "failed"
        try:
            self.check_inputs()
            self.scan()
            if self.prepare is not None:
                self.options = self.prepare()
                self.opt_hash = self.options.hash()
            self.build()
            # The families' subjects (ADR-0031): asked of the LLM where missing, changed or incomplete.
            self.subjects = subjects.update(self.state, self.out, self.llm, self.concurrency, self.progress)
            outcome = "finished"
        except KeyboardInterrupt:
            outcome = "interrupted"
            self.llm.close()
            raise
        finally:  # subjects without the LLM unless the run got that far
            exports.rebuild(self.state, self.out, with_subjects=outcome != "finished")
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
        """Hash the pending inputs and record the projects in them. Progress counts bytes, read in
        pieces, so that it moves during a large file, or one that arrives slowly (a synced
        folder's file on demand); its note names the file and the step."""
        pending = self.state.inputs("pending")
        if not pending:
            return
        sizes = {}
        for row in pending:
            try:
                sizes[row["id"]] = Path(row["path"]).stat().st_size
            except OSError:
                sizes[row["id"]] = 0
        with self.progress.phase(f"scanning {len(pending):,} input{'s' if len(pending) != 1 else ''}",
                                 sum(sizes.values()) or None, "B") as ph:
            for k, row in enumerate(pending, 1):
                started = time.monotonic()
                label = f"{Path(row['path']).name} ({sizes[row['id']] / 1e6:,.1f} MB, {k}/{len(pending)})"
                ph.set_note(f"reading {label}")
                log.info("scanning %s", label)
                self.scan_input(row, ph, label, sizes[row["id"]])
                log.debug("scanned %s in %.1f s", label, time.monotonic() - started)

    def _read(self, path: Path, ph: Any) -> bytes:
        """The file's bytes, read in pieces that advance `ph`."""
        buf = bytearray()
        with path.open("rb") as f:
            while chunk := f.read(8 << 20):
                buf += chunk
                if ph is not None:
                    ph.advance(len(chunk))
        return bytes(buf)

    def scan_input(self, row: Any, ph: Any = None, label: str = "", size: int = 0) -> None:
        """Hash an input and record the projects in it (unless this version was scanned before)."""
        path = Path(row["path"])
        label = label or path.name
        try:
            data = self._read(path, ph)
        except OSError as e:
            self._input_failed(row, f"cannot read: {e}")
            return
        if ph is not None and len(data) < size:  # shrank since it was measured: keep the total right
            ph.advance(size - len(data))
        if ph is not None:
            ph.set_note(f"hashing {label}")
        sha = sha256_bytes(data)
        st = path.stat()
        if not self.state.has_sighting(row["id"], sha):  # new or changed content: find the projects in it
            if ph is not None:
                ph.set_note(f"finding projects in {label}")
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
            new = [p for p in projects if self.state.fingerprint(p.sha256) is None]
            log.info("found %d project(s) in %s, %d not seen before", len(projects), path.name, len(new))
            for j, p in enumerate(new, 1):  # what each says about itself, for finding versions (plan PV)
                if ph is not None:
                    ph.set_note(f"fingerprinting {j}/{len(new)} {p.display_name} in {label}")
                self._fingerprint(p)
        self.state.update_input(row["id"], status="done", size=st.st_size, mtime_ns=st.st_mtime_ns, sha256=sha,
                                processed=utc_now(), error=None)

    def _fingerprint(self, project: Any) -> None:
        try:
            self.state.save_fingerprint(project.sha256, fingerprint(project))
        except Exception as e:  # an unreadable model fails its build later, with its own error
            log.warning("%s: cannot fingerprint: %s", project.display_name, e)

    def fingerprint_missing(self) -> int:
        """Fingerprint contents scanned before fingerprints existed, reading their inputs again."""
        shas = set(self.state.unfingerprinted())
        if not shas:
            return 0
        by_input: dict[str, set[str]] = defaultdict(set)
        for sha in shas:
            where = next((s for s in self.state.sightings(sha) if s["input_status"] == "done"), None)
            if where is not None:
                by_input[where["path"]].add(sha)
        done = 0
        with self.progress.phase("fingerprinting", sum(len(v) for v in by_input.values()), "project") as ph:
            for path_str, wanted in by_input.items():
                path = Path(path_str)
                try:
                    found = [p for p in discover(path.read_bytes(), path.name) if p.sha256 in wanted]
                except (OSError, UnsupportedInput) as e:
                    log.warning("cannot read %s again: %s", path, e)
                    ph.advance(len(wanted))
                    continue
                for p in found:
                    ph.set_note(f"{p.display_name} in {path.name}")
                    self._fingerprint(p)
                    done += 1
                ph.advance(len(wanted))
        return done

    def _input_failed(self, row: Any, error: str) -> None:
        log.error("input %s: %s", row["path"], error)
        self.state.update_input(row["id"], status="failed", processed=utc_now(), error=error)
        self.failed_inputs.append(row["path"])

    # -- projects --------------------------------------------------------------
    def todo(self) -> dict[str, list[tuple[str, str]]]:
        """Contents without up-to-date output, grouped by an input to read them from:
        {input path: [(content sha256, input sha256)]}."""
        by_input: dict[str, list[tuple[str, str]]] = defaultdict(list)
        for sha in self.state.stale_contents(TOOL, self.opt_hash):
            where = next((s for s in self.state.sightings(sha) if s["input_status"] == "done"), None)
            if where is not None:  # otherwise only seen in missing or old inputs: nothing to read
                by_input[where["path"]].append((sha, where["input_sha256"]))
        return by_input

    def build(self) -> None:
        todo = self.todo()
        total = sum(len(items) for items in todo.values())
        resumed = self.state.count_projects("working", TOOL, self.opt_hash)
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
                    self.state.update_input(self.state.input_id(path_str), status="pending")
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
        return self.state.count_projects("written", TOOL, self.opt_hash)

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
            result = ingest_project(content, project, work, self.llm, render=self.options.render,
                                    progress=self.progress, concurrency=self.concurrency,
                                    image_pixels=self.options.image_pixels, modules=self.options.modules,
                                    style=SketchStyle(*self.options.sketch), part_chars=self.options.part_chars)
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
            "tool": TOOL, "command": json.loads(run["command"]), "options": self.options.as_dict(),
            "projects": {"written": len(self.written), "failed": len(self.failed_projects)},
            "failed_inputs": self.failed_inputs,
            "llm": self.llm.report(),
            "subjects": self.subjects,
        }
        (self.out / "run.json").write_text(json.dumps(record, ensure_ascii=False, indent=1), encoding="utf-8")


# -- tree commands -----------------------------------------------------------------
def status(state: State) -> dict[str, Any]:
    """What an output tree holds, for `status` (reads only: works while a run is going)."""
    run = state.latest_run()
    return {
        "inputs": {
            "counts": state.counts("inputs"),
            "problems": [{"path": r["path"], "status": r["status"], "error": r["error"]}
                         for r in state.inputs("failed", "missing")],
        },
        "projects": {
            "counts": state.counts("projects"),
            "failed": [{"token": f"sha256:{r['sha256']}", "name": r["name"], "error": r["error"]}
                       for r in state.project_rows("failed")],
            "recovered": [{"token": f"sha256:{r['content_sha256']}", "name": r["name"], "entries": rec}
                          for r in state.written()
                          if (rec := json.loads(r["summary"] or "{}").get("recovered"))],
        },
        "subjects": subjects.summary(state.out),
        "calibrations": [{"model": r["model"], "kind": r["kind"], "endpoint": r["endpoint"], "created": r["created"],
                          "settings": json.loads(r["settings"]), "report": r["report"],
                          "validation": json.loads(r["validation"]) if r["validation"] else None}
                         for r in state.calibrations()],
        "latest_run": None if run is None else {
            "id": run["id"], "started": run["started"], "finished": run["finished"], "outcome": run["outcome"],
            "llm_calls": json.loads(run["llm"])["calls"] if run["llm"] else None,
        },
    }


def prune(state: State, out: Path, dry_run: bool = False) -> dict[str, Any]:
    """Drop missing inputs, sightings in old versions of changed inputs, and the contents
    that no existing input contains any more, with their output (plan decision 3)."""
    missing = [r["path"] for r in state.inputs("missing")]
    orphans = state.orphans()
    if not dry_run:
        state.prune([r["sha256"] for r in orphans])
        projects = out / exports.PROJECTS
        for r in orphans:
            for d in (projects / r["sha256"], projects / WORK / r["sha256"]):
                if d.exists():
                    shutil.rmtree(d)
        exports.rebuild(state, out)
    return {"inputs": missing, "projects": [{"token": f"sha256:{r['sha256']}", "name": r["name"]} for r in orphans]}
