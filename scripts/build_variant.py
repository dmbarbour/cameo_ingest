#!/usr/bin/env python3
"""Build an output tree with a variant of the LLM requests, to measure it (plan GS).

    uv run cameo-ingest config -o OUT set text-model M          # the tree's settings, as for any tree
    uv run python scripts/build_variant.py about/context ingest INPUTS -o OUT --no-calibrate

with OPENAI_BASE_URL and OPENAI_API_KEY in the environment. VARIANT is one of `prompts.VARIANTS`:
`current/plain` (the requests in use before 0.20.0), `current/context`, `about/plain` or
`about/context` (in use since 0.20.0). The rest are `cameo-ingest`'s arguments. The variant's
templates replace those in use for this run: their keys are part of each project's options, so
the projects they touch are written again, and their answers are cached as any others. Users
don't choose requests (ADR-0027); this script is for measuring them.

Build a variant on a copy of a calibrated tree (`run -o COPY`): text calibration probes with the
module-summary template in use, and would probe with the variant's, whose answers it can't score.
A calibrated tree keeps its calibration.
"""

from __future__ import annotations

import sys

from cameo_ingest import prompts
from cameo_ingest.cli import main as ingest


def main(argv: list[str] | None = None) -> int:
    argv = sys.argv[1:] if argv is None else argv
    names = list(prompts.VARIANTS)
    if not argv or argv[0] not in names:
        print(f"usage: build_variant.py {{{','.join(names)}}} CAMEO_INGEST_ARGS...", file=sys.stderr)
        return 2
    prompts.CURRENT.update(prompts.VARIANTS[argv[0]])  # in place: every module shares CURRENT
    return ingest(argv[1:])


if __name__ == "__main__":
    raise SystemExit(main())
