"""The LLM prompt templates, as named and versioned objects (plan LQ-01).

A template is the fixed text of a request with `{{SLOT}}` markers for what varies, and a
description of every slot: what fills it, its format, its limits. Templates can then be
reviewed and rated on their own, shown with stand-ins in place of their image and text
slots, and every request and response records which template and version it came from.

Changing a template's text means a new version (a new object with `version` + 1, the old
one kept in `TEMPLATES`), so that ratings and answers of the two can be compared. Version 1
of each template produces exactly the requests the tool made before templates existed.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

_SLOT = re.compile(r"\{\{([A-Z_]+)\}\}")


@dataclass(frozen=True)
class Slot:
    name: str
    kind: str  # "text": replaces {{NAME}} in the text; "image": attached after the text
    description: str  # what fills it: content, format, limits


@dataclass(frozen=True)
class Template:
    id: str
    version: int
    purpose: str  # what the answer is for, and where it goes
    text: str
    slots: tuple[Slot, ...]

    @property
    def key(self) -> str:
        return f"{self.id}@v{self.version}"

    @property
    def image_slot(self) -> Slot | None:
        return next((s for s in self.slots if s.kind == "image"), None)

    def render(self, values: dict[str, str]) -> str:
        """The request text, with every text slot filled (in one pass, so that slot values
        are never scanned for markers)."""
        return _SLOT.sub(lambda m: values[m.group(1)], self.text)

    def stand_in(self) -> str:
        """The template as a reviewer should see it: each slot replaced by an obvious
        stand-in that says what will fill it."""
        text = _SLOT.sub(lambda m: f"⟦{m.group(1)}: {self._slot(m.group(1)).description}⟧", self.text)
        image = self.image_slot
        return text + (f"\n\n⟦IMAGE {image.name}, attached after the text: {image.description}⟧" if image else "")

    def _slot(self, name: str) -> Slot:
        return next(s for s in self.slots if s.name == name)


DIAGRAM_DESCRIPTION = Template(
    id="diagram-description",
    version=1,
    purpose="A description of one diagram for a search index, stored as a generated:diagram_description chunk "
            "and shown on the diagram's page.",
    text=(
        "This is a simplified re-drawing of a Cameo (UML/SysML) diagram: boxes, labels and connector lines "
        "only, generated from layout data. The authoritative list of shapes and connections follows the "
        "instructions. Describe what the diagram communicates for a search index: its subject, the main "
        "elements, how they are arranged or grouped, and the key flows or relationships. Be factual, use "
        "the element names, and do not invent elements that are not listed. At most 200 words."
        "\n\n{{CONTEXT}}"
    ),
    slots=(
        Slot("CONTEXT", "text",
             "the diagram's extracted content, as plain text. Line 1: 'Diagram: <name> (<diagram type>)'. "
             "Then 'Shapes:' and one line per shape, '- <shape kind>: <label>', indented two spaces per level "
             "of nesting; labels are '«stereotype» name : Type', and pins and ports read 'Owner.pin'. Then "
             "'Connections:' and one line per connection, '- <end> →[<kind>: «stereotype» name]→ <end>' ('—' "
             "for undirected kinds). At most 150 shapes and 150 connections; the rest is cut without notice. "
             "Known defects: ends are in the drawn path's order, which reverses every directed edge (FU-001); "
             "the items a connector carries are missing (FU-002)."),
        Slot("SKETCH", "image",
             "a PNG sketch redrawn from the layout data, at most 2000 px on its longer side: boxes (ellipses "
             "for use cases and initial and final nodes), labels wrapped to three lines, connector paths, "
             "arrowheads on directed kinds (at the wrong end, FU-001), and text boxes such as item-flow labels. "
             "The title line gives the diagram type and qualified name."),
    ),
)

IMAGE_DESCRIPTION = Template(
    id="image-description",
    version=1,
    purpose="A description of one image embedded in the model (an attachment or image shape), for a search "
            "index, stored as a generated:image_description chunk and shown in images.md.",
    text=(
        "This image was embedded in a systems engineering model (Cameo/SysML). Describe its content "
        "factually for a search index: what kind of image it is, any visible text, labels, components and "
        "connections. Do not speculate beyond what is visible. At most 200 words."
    ),
    slots=(
        Slot("IMAGE", "image",
             "the embedded image as stored in the model (PNG, JPEG or GIF), unscaled. Nothing says which "
             "element owns it or where it appears."),
    ),
)

PACKAGE_SUMMARY = Template(
    id="package-summary",
    version=1,
    purpose="A summary of one package for a search index, stored as a generated:summary chunk and shown at "
            "the top of the package's page. Only packages with at least 5 sections get one.",
    text=(
        "You are documenting a systems engineering model (UML/SysML, authored in Cameo). Below is an "
        "extract of one package. Write a concise factual summary (at most 150 words) of what this package "
        "models: its purpose, the main elements and how they relate. Use only the information given; do "
        "not speculate. Plain prose, no headings."
        "\n\n---\n{{PACKAGE_TEXT}}"
    ),
    slots=(
        Slot("PACKAGE_TEXT", "text",
             "the package's Markdown page as extracted, without trace lines: the package's own section (kind, "
             "qualified name, documentation, members with links), then one section per element (stereotypes, "
             "requirement text, documentation, tagged values, members, relationships, diagrams showing it). "
             "Cut at 12,000 characters without notice; large packages lose the detail of later elements "
             "(FU-005)."),
    ),
)

TEMPLATES = {t.key: t for t in (DIAGRAM_DESCRIPTION, IMAGE_DESCRIPTION, PACKAGE_SUMMARY)}
