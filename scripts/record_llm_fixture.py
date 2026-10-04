#!/usr/bin/env python3
"""Record the LLM replay fixture, tests/fixtures/llm-replay.sqlite, against a live endpoint.

    uv run python scripts/record_llm_fixture.py --env .env

The regular test suite replays these answers with --llm-replay, so the LLM code paths are
tested offline and deterministically (BASE-022R5). Record again whenever a prompt, the
fixture model (tests/fixture_model.py) or the page text changes; the replay test then
fails with a ReplayMiss.

Recording runs without calibrating, as the replay tests do, and without rendering
(--no-render), so that no request depends on how the installed Pillow draws diagram sketches.
Package_Delivery_Drone is included when the sample is present (scripts/fetch_samples.py
--small). The fixture keeps model names, request hashes and answers; endpoints are blanked,
since replay ignores them.
"""

from __future__ import annotations

import argparse
import json
import sqlite3
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tests"))

from fixture_model import make_mdzip

from cameo_ingest.cli import main as ingest

FIXTURE = ROOT / "tests" / "fixtures" / "llm-replay.sqlite"
SAMPLE = ROOT / "samples" / "Package_Delivery_Drone.mdzip"


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--env", help="dotenv file with the OPENAI_* settings, e.g. .env")
    ap.add_argument("--model", help="model to record (default: CAMEO_INGEST_TEXT_MODEL or OPENAI_MODEL)")
    args = ap.parse_args()

    with tempfile.TemporaryDirectory() as tmp_dir:
        tmp = Path(tmp_dir)
        fixture = tmp / "drone.mdzip"
        fixture.write_bytes(make_mdzip())
        common = ["--no-render", "--no-calibrate", "--cache-dir", str(tmp / "store"), "--llm-concurrency", "4", "-v"]
        common += ["--env", args.env] if args.env else []
        common += ["--text-model", args.model] if args.model else []
        for i, src in enumerate([fixture] + ([SAMPLE] if SAMPLE.exists() else [])):
            out = tmp / f"out{i}"
            rc = ingest([str(src), "-o", str(out), *common])
            if rc != 0:
                print(f"error: recording {src.name} failed (exit {rc})", file=sys.stderr)
                return 1
            incomplete = json.loads((out / "run.json").read_text())["llm"]["incomplete"]
            if incomplete:  # a replay of this fixture would miss these
                print(f"error: {len(incomplete)} item(s) of {src.name} got no answer: {incomplete[:3]}",
                      file=sys.stderr)
                return 1
        db = sqlite3.connect(tmp / "store" / "llm.sqlite")
        with db:
            db.execute("UPDATE responses SET endpoint = ''")
            db.execute("DROP TABLE IF EXISTS requests")  # prompts carry third-party model content
        FIXTURE.parent.mkdir(exist_ok=True)
        FIXTURE.unlink(missing_ok=True)
        db.execute("VACUUM INTO ?", (str(FIXTURE),))
        count, models = db.execute("SELECT count(*), group_concat(DISTINCT model) FROM responses").fetchone()
        db.close()
    print(f"recorded {count} responses from {models} into {FIXTURE.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
