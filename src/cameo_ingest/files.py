"""Where a project's pages are, and links between them: one file per package and per diagram,
an anchor per section element (plan RA-13, AR-007R1)."""

from __future__ import annotations

from typing import TYPE_CHECKING

from . import sections as sx
from . import semantics as sem
from .diagram_text import Refs, markdown
from .model import Element
from .text import md_inline, slug

if TYPE_CHECKING:
    from .view import ProjectView


def relpath(dest: str, from_file: str) -> str:
    """Relative link from one project-relative file to another (keeps #anchors)."""
    path, _, frag = dest.partition("#")
    from_parts = from_file.split("/")[:-1]
    to_parts = path.split("/")
    i = 0
    while i < len(from_parts) and i < len(to_parts) - 1 and from_parts[i] == to_parts[i]:
        i += 1
    rel = "/".join([".."] * (len(from_parts) - i) + to_parts[i:])
    return f"{rel}#{frag}" if frag else rel


class FilePlan:
    def __init__(self, view: ProjectView):
        self.view = view
        self.file_of: dict[str, str] = {}  # element id -> relative md path (+anchor)
        self._plan_files()

    def _plan_files(self) -> None:
        used: set[str] = set()
        self.pkg_file: dict[str, str] = {}
        for el in self.view.ix.elements.values():
            if el.kind in sem.PACKAGE_KINDS:
                base = slug(self.view.ix.qualified_name(el.id).replace("::", "__") or el.id, 150)
                name, n = base, 1
                while name.lower() in used:
                    n += 1
                    name = f"{base}_{n}"
                used.add(name.lower())
                self.pkg_file[el.id] = f"packages/{name}.md"
        self.dia_file: dict[str, str] = {}
        for d in self.view.ix.diagrams.values():
            base = slug(d.name or d.id)
            name, n = base, 1
            while f"d/{name}".lower() in used:
                n += 1
                name = f"{base}_{n}"
            used.add(f"d/{name}".lower())
            self.dia_file[d.id] = f"diagrams/{name}.md"
        for el in self.view.ix.elements.values():
            if el.kind == "Diagram" and el.id in self.dia_file:
                self.file_of[el.id] = self.dia_file[el.id]
            elif el.kind in sem.PACKAGE_KINDS:
                self.file_of[el.id] = self.pkg_file[el.id]
            elif sem.is_section(self.view.ix, el):
                pkg = self.view.package_of(el)
                if pkg is not None:
                    self.file_of[el.id] = f"{self.pkg_file[pkg.id]}#{self.anchor(el)}"

    def anchor(self, el: Element) -> str:
        # Only the name part is shortened, so the id always keeps anchors unique. Ids keep
        # their case: EMF-style ids (e.g. "_2VHvQXmuEe6Klrv3p62i1g") are case-sensitive.
        return f"{slug(el.name or el.kind, 80).lower()}-{slug(el.id, 200)}"

    def refs(self, from_file: str) -> Refs:
        """Links from `from_file` to the pages of elements that have one, for diagram lists."""
        return markdown(lambda e: relpath(self.file_of[e], from_file) if self.file_of.get(e) else None)

    def link(self, target_id: str, from_file: str, text: str | None = None) -> str:
        """A link to the element's page, labelled with `text` or the element's label; the label
        alone when the element has no page."""
        label = md_inline(text if text is not None else sem.label(self.view.ix, target_id))
        dest = self.file_of.get(target_id)
        if not dest:
            return label
        rel = relpath(dest, from_file)
        return f"[{label}]({rel})"

    def linker(self, from_file: str) -> sx.Link:
        return lambda id_, label: self.link(id_, from_file, label)

    def module_image(self, dia_id: str, num: int) -> str:
        return f"{self.dia_file[dia_id].removesuffix('.md')}.modules/M{num}.png"
