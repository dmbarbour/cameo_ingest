"""Write RAG-ready outputs for one project: Markdown, CSV and JSON/JSONL.

Layout (per project, under <out>/<project-slug>/):

    README.md                 overview: counts, top-level packages, diagrams
    packages/<path>.md        one file per package, one section per element
    diagrams/<name>.md        one file per diagram (+ rendered image if available)
    tables/*.csv              elements, relationships, requirements, properties,
                              tagged_values, diagrams
    index/elements.jsonl      every element with full structure
    index/hierarchy.json      containment tree of section-level elements
    index/chunks.jsonl        one self-contained chunk per section, with metadata

Every Markdown file has JSON-valued YAML front matter with a `provenance` block; every
section carries a visible `trace:` locator; every CSV row has a `trace` column; every
chunk has `metadata.provenance`. Text produced by an LLM is always labelled as such.
"""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

from . import crossref
from . import modules as mod
from .annotations import Annotation
from .archive import Project
from .files import FilePlan
from .layout import Layout
from .ledger import LedgerWriter
from .model import ModelIndex
from .pages import PageWriter
from .provenance import ContentInfo
from .sink import ChunkSink
from .tables import TableWriter
from .view import ProjectView


class ProjectWriter:
    """A project's output, by the pieces that make it (AR-007R1): the model as pages and chunks see it
    (`view`), where its files are (`plan`), its chunks (`sink`), its pages and its tables."""

    def __init__(self, content: ContentInfo, project: Project, ix: ModelIndex, root: Path,
                 annotations: dict[str, list[Annotation]] | None = None,
                 layouts: dict[str, Layout] | None = None, modules: tuple[int, int, int] = mod.DEFAULTS):
        self.root = root
        self.view = ProjectView(content, project, ix, annotations, layouts, modules)
        self.plan = FilePlan(self.view)
        self.sink = ChunkSink(self.view)
        self.pages = PageWriter(self.view, self.plan, self.sink, root)
        self.tables = TableWriter(self.view, self.plan, self.sink, root)

    def write_steps(self) -> int:
        """How many times `write_all` calls `tick`."""
        return len(self.plan.pkg_file) + len(self.plan.dia_file) + 4

    def write_all(self, tick: Callable[[], None] = lambda: None) -> None:
        """Write every file; `tick` is called after each page and each of the four
        project-wide steps (README, ledger, tables, indices)."""
        for pkg_id, rel in self.plan.pkg_file.items():
            self.pages.write_package(self.view.ix.elements[pkg_id], rel)
            tick()
        for dia_id, rel in self.plan.dia_file.items():
            self.pages.write_diagram(dia_id, rel)
            tick()
        ledger = LedgerWriter(self.view, self.plan, self.sink, self.pages)
        for step in (self.pages.write_readme, ledger.write, self.tables.write_tables, self._write_indices):
            step()
            tick()

    def _write_indices(self) -> None:
        """The indices, once every chunk is made; and the project's threads, for which the
        tree decides whether its chunks include them (AR-014R2)."""
        threads = crossref.project_threads(self.view, self.sink.main)
        self.pages.write_threads(threads)
        self.tables.write_indices(threads)
