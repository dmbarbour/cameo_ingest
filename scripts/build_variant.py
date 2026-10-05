#!/usr/bin/env python3
"""Build an output tree with a variant of the LLM requests, to measure it (plan GS).

    uv run python scripts/build_variant.py about/context ingest INPUTS -o OUT --env .env \\
        --text-model M --vision-model M --no-calibrate

VARIANT is one of `prompts.VARIANTS` (`current/context`, `about/plain`, `about/context`), or
`current/plain` for the requests in use. The rest are `cameo-ingest`'s arguments. The variant's
templates replace those in use for this run: their keys are part of each project's options, so
the projects they touch are written again, and their answers are cached as any others. Users
don't choose requests (ADR-0027); this script is for measuring them.
"""

from __future__ import annotations

import sys

from cameo_ingest import prompts
from cameo_ingest.cli import main as ingest


def main(argv: list[str] | None = None) -> int:
    argv = sys.argv[1:] if argv is None else argv
    names = ["current/plain", *prompts.VARIANTS]
    if not argv or argv[0] not in names:
        print(f"usage: build_variant.py {{{','.join(names)}}} CAMEO_INGEST_ARGS...", file=sys.stderr)
        return 2
    prompts.CURRENT.update(prompts.VARIANTS.get(argv[0], {}))  # in place: every module shares CURRENT
    return ingest(argv[1:])


if __name__ == "__main__":
    raise SystemExit(main())
