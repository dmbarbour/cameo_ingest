"""Retrieval evaluation of an output tree (plan RE, `docs/plans/retrieval-evaluation-2026-09-30.md`).

Not needed for ingesting: its heavier dependencies (numpy, tokenizers) are the `eval` extra,
installed with `pip install "cameo-ingest[eval]"`, or `uv sync --extra eval` in a checkout. Grading
(`grading`) and the fictional projects (`fiction`) need neither.
"""

import importlib
from types import ModuleType

EXTRA = 'install "cameo-ingest[eval]" (or `uv sync --extra eval` in a checkout)'


def require(module: str) -> ModuleType:
    """An optional dependency of the evaluation, or an error that says how to install it."""
    try:
        return importlib.import_module(module)
    except ImportError as e:
        raise ImportError(f"the retrieval evaluation needs {module}: {EXTRA}") from e
