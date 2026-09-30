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
    image_first: bool = False  # the image goes before the text in the request (FU-015)

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
        if image is None:
            return text
        if self.image_first:
            return f"⟦IMAGE {image.name}, sent before the text: {image.description}⟧\n\n{text}"
        return f"{text}\n\n⟦IMAGE {image.name}, attached after the text: {image.description}⟧"

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

# Version 2 (2026-09-30): meaning rather than restated structure (FU-009), the notation
# explained, grouping only as drawn and no Markdown (FU-004), the legend and numbered sketch
# (FU-008), and saying when input was cut (FU-005, FU-011).
_NOTATION = (
    "In the sketch, each shape carries a number; the legend gives its full label. Connections read "
    "'[a] source →[kind: name]→ [b] target' for directed relationships (flows, dependencies, "
    "generalizations, «satisfy», «deriveReqt»...) and '[a] —[kind]— [b]' for undirected ones; "
    "'carries X →' names what flows along a connector, in the direction of the arrow."
)
_STYLE = ("Write plain prose, without headings, lists, bold or code formatting, and use the element "
          "names exactly as written.")

DIAGRAM_DESCRIPTION_V2 = Template(
    id="diagram-description",
    version=2,
    purpose=DIAGRAM_DESCRIPTION.purpose,
    text=(
        "You are helping to index a systems engineering model (UML/SysML, authored in Cameo) for search. "
        "Below is one diagram: a sketch redrawn from its layout (the attached image), and its content as "
        f"text. {_NOTATION}\n\n"
        "Explain what this diagram tells a reader about the system: what it is for, what it shows the "
        "system or its parts doing or being made of, and which flows or dependencies matter most and why. "
        "Do not restate the legend or list every connection: they are already recorded exactly. Group or "
        "order elements only as the diagram itself does (nesting, frames, partitions, the order of flows). "
        "Base every statement on the text and the sketch; when the diagram shows little, say little. "
        f"{_STYLE} At most 150 words.\n\n"
        "Diagram: {{DIAGRAM}}\nLegend:\n{{LEGEND}}\nConnections:\n{{CONNECTIONS}}{{CUT_NOTE}}"
    ),
    slots=(
        Slot("DIAGRAM", "text", "the diagram's name and type, '<name> (<diagram type>)'."),
        Slot("LEGEND", "text",
             "one line per shape, '- [<number>] <shape kind>: <label>', indented two spaces per level of "
             "nesting; labels are '«stereotype» name : Type', an unnamed typed element shows its type alone. "
             "Pins and ports are not listed; they appear in connections as '[n] Owner.pin'. At most 150 lines."),
        Slot("CONNECTIONS", "text",
             "one line per connection, in the notation the text explains, with directions taken from the model "
             "and the items a connector carries. At most 150 lines."),
        Slot("CUT_NOTE", "text",
             "empty, or a line saying that only the first 150 shapes or connections are listed, and how many "
             "there are (large diagrams: plan DV splits them instead)."),
        Slot("SKETCH", "image",
             "a PNG sketch redrawn from the layout data, at most --image-size (768) px on its longer side: shapes "
             "tagged with their legend numbers and, where it fits on one line, their name; pins and ports as "
             "dots; arrowheads at the target; small mid-line arrows for item flows; the title gives the diagram "
             "type and qualified name."),
    ),
)

PACKAGE_SUMMARY_V2 = Template(
    id="package-summary",
    version=2,
    purpose=PACKAGE_SUMMARY.purpose,
    text=(
        "You are helping to index a systems engineering model (UML/SysML, authored in Cameo) for search. "
        "Below is the extracted text of one package, in Markdown: the package's own description and members, "
        "then a section for each element in it. {{CUT_NOTE}}Summarize what this package models: its purpose, "
        "its main elements, and how they relate. Use only the information given, and do not speculate. "
        f"{_STYLE} At most 150 words.\n\n---\n{{{{PACKAGE_TEXT}}}}"
    ),
    slots=(
        Slot("CUT_NOTE", "text",
             "empty, or a sentence saying the text was cut at 12,000 of its N characters, so that later "
             "elements are known by name only."),
        Slot("PACKAGE_TEXT", "text",
             "the package's Markdown page as extracted, without trace lines: the package's own section (kind, "
             "qualified name, documentation, members with links), then one section per element (stereotypes, "
             "requirement text, documentation, tagged values, members, relationships, diagrams showing it). "
             "At most 12,000 characters (FU-005)."),
    ),
)

# Version 3 (2026-09-30): which way dependency arrows point (FU-013), and what the flows
# achieve rather than which "matter most" (which drew filler).
_DEPENDENCIES = (
    "A dependency arrow runs from the element that depends to the one it depends on: with «DeriveReqt», "
    "X → Y means X is derived from Y; with «Satisfy», X satisfies Y; with «Verify», X verifies Y; with "
    "«Refine», X refines Y; with «Allocate», X is allocated to Y. With Generalization, X → Y means X is a "
    "kind of Y; with Include, use case X includes Y."
)

DIAGRAM_DESCRIPTION_V3 = Template(
    id="diagram-description",
    version=3,
    purpose=DIAGRAM_DESCRIPTION.purpose,
    text=(
        "You are helping to index a systems engineering model (UML/SysML, authored in Cameo) for search. "
        "Below is one diagram: a sketch redrawn from its layout (the attached image), and its content as "
        f"text. {_NOTATION} {_DEPENDENCIES}\n\n"
        "Explain what this diagram tells a reader about the system: what it is for, what it shows the "
        "system or its parts doing or being made of, and what its main flows or dependencies achieve. "
        "Do not restate the legend or list every connection: they are already recorded exactly. Group or "
        "order elements only as the diagram itself does (nesting, frames, partitions, the order of flows). "
        "Base every statement on the text and the sketch; when the diagram shows little, say little. "
        f"{_STYLE} At most 150 words.\n\n"
        "Diagram: {{DIAGRAM}}\nLegend:\n{{LEGEND}}\nConnections:\n{{CONNECTIONS}}{{CUT_NOTE}}"
    ),
    slots=DIAGRAM_DESCRIPTION_V2.slots,
)



# Version 4 of diagrams and 2 of images (2026-09-30): the image comes first, as Google advises,
# drawn to fill gemma-4's pixel budget (FU-015).
_SKETCH_V4 = Slot(
    "SKETCH", "image",
    "a PNG sketch redrawn from the layout data, filling the vision model's pixel budget (--image-pixels, "
    "645,120 by default: 280 soft tokens of 48 x 48 px) at the diagram's own aspect ratio, sides in multiples "
    "of 48: shapes tagged with their legend numbers and, where it fits on one line, their name; pins and "
    "ports as dots; arrowheads at the target; small mid-line arrows for item flows; the title gives the "
    "diagram type and qualified name.")

DIAGRAM_DESCRIPTION_V4 = Template(
    id="diagram-description",
    version=4,
    purpose=DIAGRAM_DESCRIPTION.purpose,
    text=(
        "You are helping to index a systems engineering model (UML/SysML, authored in Cameo) for search. "
        "The image above is a sketch redrawn from one diagram's layout; below is the diagram's content as "
        f"text. {_NOTATION} {_DEPENDENCIES}\n\n"
        "Explain what this diagram tells a reader about the system: what it is for, what it shows the "
        "system or its parts doing or being made of, and what its main flows or dependencies achieve. "
        "Do not restate the legend or list every connection: they are already recorded exactly. Group or "
        "order elements only as the diagram itself does (nesting, frames, partitions, the order of flows). "
        "Base every statement on the text and the sketch; when the diagram shows little, say little. "
        f"{_STYLE} At most 150 words.\n\n"
        "Diagram: {{DIAGRAM}}\nLegend:\n{{LEGEND}}\nConnections:\n{{CONNECTIONS}}{{CUT_NOTE}}"
    ),
    slots=(*DIAGRAM_DESCRIPTION_V2.slots[:4], _SKETCH_V4),
    image_first=True,
)

IMAGE_DESCRIPTION_V2 = Template(
    id="image-description",
    version=2,
    purpose=IMAGE_DESCRIPTION.purpose,
    text=(
        "The image above was embedded in a systems engineering model (Cameo/SysML). Describe its content "
        "factually for a search index: what kind of image it is, any visible text, labels, components and "
        f"connections. Do not speculate beyond what is visible. {_STYLE} At most 200 words."
    ),
    slots=(
        Slot("IMAGE", "image",
             "the embedded image as stored in the model (PNG, JPEG or GIF), scaled down to the vision model's "
             "pixel budget if larger, sides in multiples of 48. Nothing says which element owns it or where it "
             "appears."),
    ),
    image_first=True,
)

# The versions in use. Their keys are part of a run's options, so that a project written
# with other versions is written again (FU-014).
CURRENT = {t.id: t for t in (DIAGRAM_DESCRIPTION_V4, IMAGE_DESCRIPTION_V2, PACKAGE_SUMMARY_V2)}

TEMPLATES = {t.key: t for t in (DIAGRAM_DESCRIPTION, IMAGE_DESCRIPTION, PACKAGE_SUMMARY, DIAGRAM_DESCRIPTION_V2,
                                PACKAGE_SUMMARY_V2, DIAGRAM_DESCRIPTION_V3, DIAGRAM_DESCRIPTION_V4,
                                IMAGE_DESCRIPTION_V2)}
