"""Helpers shared by the tests (plan RA-18a): ingesting, reading trees, checking invariants, a fake
LLM endpoint."""

import csv
import json
import re
import threading
import time
from collections import Counter
from collections.abc import Sequence
from pathlib import Path

from cameo_ingest.chunks import problems as chunk_problems
from cameo_ingest.cli import main
from cameo_ingest.llm import PREFLIGHT_PROMPT

csv.field_size_limit(1 << 30)  # documentation columns in large models exceed the default

LLM_ENV = ("OPENAI_API_KEY", "OPENAI_BASE_URL", "OPENAI_MODEL", "CAMEO_INGEST_TEXT_MODEL",
           "CAMEO_INGEST_VISION_MODEL", "CAMEO_INGEST_LLM_TIMEOUT", "CAMEO_INGEST_LLM_RETRIES",
           "CAMEO_INGEST_LLM_MAX_CALLS")
TREE_ENV = ("CAMEO_INGEST_TREE", "CAMEO_INGEST_DEST", "CAMEO_INGEST_CACHE")  # never a test's, unless it sets them


SAMPLES_DIR = Path(__file__).parent.parent / "samples"


# Root files that name local paths or times; everything else in a tree is reproducible.
RUN_RECORDS = {"run.json", "provenance.jsonl", "state.sqlite", "state.sqlite-wal", "state.sqlite-shm", "state.lock"}


def tree(out: Path) -> dict[str, bytes]:
    """Every file of a tree but those that name local paths or times."""
    return {str(f.relative_to(out)): f.read_bytes() for f in out.rglob("*")
            if f.is_file() and f.name not in RUN_RECORDS and ".cache" not in f.parts
            and f.relative_to(out).parts[:2] != ("rag", "meta")}


def project_dir(out: Path, name: str | None = None) -> Path:
    """The directory of the only (or the named) written project in an output tree."""
    projects = [p for p in json.loads((out / "manifest.json").read_text())["projects"]
                if name is None or p["name"] == name]
    assert len(projects) == 1, [p["name"] for p in projects]
    return out / projects[0]["dir"]


def provenance(out: Path) -> dict[str, dict]:
    return {r["token"]: r for r in map(json.loads, (out / "provenance.jsonl").open())}


def ingest(tmp_path: Path, *sources: tuple[str, bytes] | Path, args: Sequence[str] = ("--no-llm",),
           out: str = "out", status: int = 0) -> Path:
    """Ingest into `tmp_path/out` and return the tree. Each source is a path, or a (relative
    path, bytes) pair written under `tmp_path`; `args` are the flags, as given."""
    tmp_path.mkdir(parents=True, exist_ok=True)
    paths = []
    for s in sources:
        if isinstance(s, tuple):
            path = tmp_path / s[0]
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(s[1])
            s = path
        paths.append(str(s))
    tree_dir = tmp_path / out
    assert main([*paths, "-o", str(tree_dir), *args]) == status
    return tree_dir


def run(tmp_path: Path, name: str, data: bytes) -> Path:
    return ingest(tmp_path, (name, data), args=("--meta", "program=test", "--no-llm"))


DIAGNOSTICS = ("calibration", "quality")  # the tool's reports to the maintainer, not the models' content


def check_invariants(out: Path) -> None:
    """Properties every output tree must have, whatever the input (BASE-007R1)."""
    for md in out.rglob("*.md"):
        if md.relative_to(out).parts[0] in DIAGNOSTICS:
            continue
        text = md.read_text(encoding="utf-8")
        head = text.split("\n---\n", 1)[0]
        assert head.startswith("---\n") and "provenance:" in head, md
        dup = [a for a, n in Counter(re.findall(r'<a id="([^"]+)"></a>', text)).items() if n > 1]
        assert not dup, (md, dup[:3])
        assert "<unnamed>" not in text and "{#" not in text, md  # placeholders and anchors (BASE-009)
    for f in out.rglob("*.csv"):
        with f.open(encoding="utf-8", newline="") as fh:
            assert all(r.get("trace", "").startswith("sha256:") for r in csv.DictReader(fh)), f
    chunks = [json.loads(line) for line in (out / "chunks.jsonl").open(encoding="utf-8")]
    dup = [i for i, n in Counter(c["id"] for c in chunks).items() if n > 1]
    assert not dup, dup[:3]
    long = [c["id"] for c in chunks if max(map(len, c["text"].splitlines()), default=0) > 8000]
    assert not long, long[:3]  # no encoded images or configuration dumps (FU-020)
    for c in chunks:
        assert not chunk_problems(c), (c["id"], chunk_problems(c))  # what every chunk carries (AR-015)
        if "content" in c["metadata"]:
            assert "source_metadata" in c["metadata"], c["id"]  # joined in at the root
        if c["metadata"]["provenance"]["derivation"]["method"] == "llm":  # labelled (BASE-025)
            assert c["metadata"]["kind"].startswith("generated:"), c["id"]
            assert "not part of the source model" in c["text"], c["id"]
    # A `base_*` attribute or reference means a stereotype application was read as an element.
    for f in out.glob("by-sha256/*/index/elements.jsonl"):
        for line in f.open(encoding="utf-8"):
            rec = json.loads(line)
            assert not any(n.startswith("base_") for n in [*rec["attrs"], *(r for r, _ in rec["refs"])]), rec["id"]


class FakeChat:
    """Stands in for the endpoint's client (`llm.OpenAIChat`): records requests and returns a
    fixed reply."""

    replays = False
    fail = False  # set on the class to make every request raise
    interrupt_at: int | None = None  # raise KeyboardInterrupt on this enrichment request (Ctrl-C)
    delay = 0.0  # seconds per request
    inflight = max_inflight = 0
    _lock = threading.Lock()

    def __init__(self, cfg=None):
        self.cfg = cfg
        self.requests: list[tuple[str, list]] = []

    def complete(self, model, messages, temperature):
        self.requests.append((model, messages))
        if self.interrupt_at is not None and len(self.enrichment()) == self.interrupt_at:
            raise KeyboardInterrupt
        if self.fail:
            raise RuntimeError("endpoint down")
        with FakeChat._lock:
            FakeChat.inflight += 1
            FakeChat.max_inflight = max(FakeChat.max_inflight, FakeChat.inflight)
        time.sleep(self.delay)
        with FakeChat._lock:
            FakeChat.inflight -= 1
        return "A block definition diagram showing Drone composed of Battery."

    def close(self):
        pass

    def enrichment(self) -> list[tuple[str, list]]:
        """Requests other than the preflight check."""
        return [r for r in self.requests if PREFLIGHT_PROMPT not in json.dumps(r[1])]
