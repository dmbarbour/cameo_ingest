"""The LLM prompt templates, as named and versioned objects (plan LQ-01).

A template is the fixed text of a request with `{{SLOT}}` markers for what varies, and a
description of every slot: what fills it, its format, its limits. Templates can then be
reviewed and rated on their own, shown with stand-ins in place of their image and text
slots, and every request and response records which template and version it came from.

Changing a template's text means a new version (`version` + 1), so that projects written with
the old one are written again (FU-014); a test pins each template's text. Only the versions in
use are kept here. The older ones were retired (plan RA-03); they are in the commit tagged
`studies-2026-10-02`, and the LLM store's request log names the version of every answer.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

_SLOT = re.compile(r"\{\{([A-Z_]+)\}\}")

# What a request may hold (AR-009): used by the request builders (`prompt_values`), and stated in the
# slots' descriptions.
DIAGRAM_ITEMS = 150  # shapes, and connections, listed with a diagram
SUMMARY_CHARS = 12_000  # a package summarized in one request; a larger one in parts
PART_CHARS = (3_000, 12_000)  # a large package's parts: the smallest worth its own request, and the limit
OWN_CHARS = 6_000  # a large package's own section, sent with its parts' summaries
MAX_SUMMARIES = 30  # summaries per synthesis request; more are summarized in runs first
DIGEST_CHARS = (8_000, 4_000)  # an instances digest, and the text of the package's other elements


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
    # Sentences a request may add, as format strings: they belong to the version, as its text does
    # (AR-009), so that no wording reaches the model outside a version.
    fragments: tuple[tuple[str, str], ...] = ()

    @property
    def key(self) -> str:
        return f"{self.id}@v{self.version}"

    def fragment(self, name: str, **values: object) -> str:
        return dict(self.fragments)[name].format(**values)

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


# Diagrams and packages, version 2 (2026-09-30): meaning rather than restated structure
# (FU-009), the notation explained, grouping only as drawn and no Markdown (FU-004), the legend
# and numbered sketch (FU-008), and saying when input was cut (FU-005, FU-011).
_NOTATION = (
    "In the sketch, each shape carries a number; the legend gives its full label. Connections read "
    "'[a] source →[kind: name]→ [b] target' for directed relationships (flows, dependencies, "
    "generalizations, «satisfy», «deriveReqt»...) and '[a] —[kind]— [b]' for undirected ones; "
    "'carries X →' names what flows along a connector, in the direction of the arrow."
)
_STYLE = ("Write plain prose, without headings, lists, bold or code formatting, and use the element "
          "names exactly as written.")

# The text slots of a diagram's description.
_DIAGRAM_SLOTS = (
    Slot("DIAGRAM", "text", "the diagram's name and type, '<name> (<diagram type>)'."),
    Slot("LEGEND", "text",
         "one line per shape, '- [<number>] <shape kind>: <label>', indented two spaces per level of "
         "nesting; labels are '«stereotype» name : Type', an unnamed typed element shows its type alone. "
         "Pins and ports are not listed; they appear in connections as '[n] Owner.pin'. "
         f"At most {DIAGRAM_ITEMS} lines."),
    Slot("CONNECTIONS", "text",
         "one line per connection, in the notation the text explains, with directions taken from the model "
         f"and the items a connector carries. At most {DIAGRAM_ITEMS} lines."),
    Slot("CUT_NOTE", "text",
         f"empty, or a line saying that only the first {DIAGRAM_ITEMS} shapes or connections are listed, and how many "
         "there are (large diagrams: plan DV splits them instead)."),
)

PACKAGE_SUMMARY = Template(
    id="package-summary",
    version=4,
    purpose=(
        "A summary of one package for a search index, stored as a generated:summary chunk and shown at "
        "the top of the package's page. Only packages with at least 5 sections get one."
    ),
    text=(
        "You are helping to index a systems engineering model (UML/SysML, authored in Cameo) for search. "
        "Below is the extracted text of one package: the package's own description and members, then a "
        "section for each element in it. Summarize what this package models: its purpose, "
        "its main elements, and how they relate. Use only the information given, and do not speculate. "
        f"{_STYLE} At most 150 words.\n\n---\n{{{{PACKAGE_TEXT}}}}"
    ),
    slots=(
        Slot("PACKAGE_TEXT", "text",
             "the package's sections as plain text (AR-018): its own (its kind, qualified name, documentation, "
             "members), then one per element, each a title ('«stereotype» name'), its fields ('Kind: Class') and "
             "its blocks ('Documentation: ...', 'Relationships:' and a line each), meaning before members and "
             f"tagged values, sections apart by a blank line. At most the part size ({SUMMARY_CHARS:,} characters "
             "unless calibration lowers it, plan TC): a larger package is summarized in parts (FU-005)."),
    ),
)

# Diagrams, version 3 (2026-09-30): which way dependency arrows point (FU-013), and what the
# flows achieve rather than which "matter most" (which drew filler).
_DEPENDENCIES = (
    "A dependency arrow runs from the element that depends to the one it depends on: with «DeriveReqt», "
    "X → Y means X is derived from Y; with «Satisfy», X satisfies Y; with «Verify», X verifies Y; with "
    "«Refine», X refines Y; with «Allocate», X is allocated to Y. With Generalization, X → Y means X is a "
    "kind of Y; with Include, use case X includes Y."
)


# How to read a sketch (plan SK, 2026-10-03): one sentence per drawing convention, sent only when
# the sketch uses it. The sketches are ours, so we know what each mark means; validation showed a
# model reading a correct tree against its triangles. Part of each template that sends a sketch.
GUIDE = (
    ("guide", "Reading the sketch:"),
    ("tags", ("- Each shape shows its number in a grey tag at its top left, then its name, cut short with '…' when it "
              "doesn't fit (the legend has it whole).")),
    ("nesting", "- A shape drawn inside another is nested in it, not connected to it."),
    ("frames", "- A plain rectangle with a title, drawn around shapes, only groups them; it is not connected to them."),
    ("open", ("- An open arrowhead marks where a directed connection ends: it runs from the line's other end to the "
              "arrowhead. A line without an arrowhead is undirected.")),
    ("hollow", ("- A hollow triangle marks the general end of a generalization (the parent), or the realized end of a "
                "realization: the connection runs from the other end to the triangle.")),
    ("tree", ("- Connections to one shape may be drawn as a tree: each line, with its own arrowhead, joins a shared "
              "bar that leads to that shape. Each runs from its own end to that shape, whether the shape is above or "
              "below.")),
    ("containment", ("- Lines joined by a shared bar with no arrowhead show containment: the shape at the bar's root "
                     "contains the others.")),
    ("dashed", ("- A dashed line is a dependency (such as «satisfy», «deriveReqt», «verify», «refine», «trace» or a "
                "usage), running from its tail to its arrowhead.")),
    ("association-class", ("- A dashed line from the middle of a connection to a shape makes that shape the "
                           "connection's association class; it is not a connection of its own.")),
    ("pins", "- Small dots on a shape's border are its pins or ports; a line ending at a dot belongs to that shape."),
    ("flows", "- A small arrow in the middle of a line shows the direction its items flow."),
    ("breaks", "- A small circle labelled 'to N' or 'from N' continues a long line to or from shape N."),
    ("bars", "- A thick black bar is a fork or a join: flows split or meet there."),
    ("sequence", ("- Lifelines are the boxes along the top, with dashed lines below them; the narrow boxes on a "
                  "lifeline's line are its activations, listed under it in the legend. Messages are the horizontal "
                  "arrows between them, in time order from top to bottom.")),
)
GUIDE_SLOT = Slot("GUIDE", "text",
                  "empty, or a paragraph 'Reading the sketch:' with one line for each drawing convention the sketch "
                  "uses, from this version's fragments (tags, nesting, frames, arrowheads, triangles, trees, "
                  "containment, dashed dependencies, association classes, pins, item flows, connector circles, "
                  "fork and join bars, sequence diagrams).")

# Version 4 of diagrams and 2 of images (2026-09-30): the image comes first, as Google advises,
# drawn to fill gemma-4's pixel budget (FU-015).
_SKETCH = Slot(
    "SKETCH", "image",
    "a PNG sketch redrawn from the layout data, filling the vision model's pixel budget (--image-pixels, "
    "645,120 by default: 280 soft tokens of 48 x 48 px) at the diagram's own aspect ratio, sides in multiples "
    "of 48: shapes tagged with their legend numbers and, where it fits on one line, their name; pins and "
    "ports as dots; arrowheads at the target; small mid-line arrows for item flows; the title gives the "
    "diagram type and qualified name.")

DIAGRAM_DESCRIPTION = Template(
    id="diagram-description",
    version=6,
    purpose=(
        "A description of one diagram for a search index, stored as a generated:diagram_description chunk "
        "and shown on the diagram's page."
    ),
    text=(
        "You are helping to index a systems engineering model (UML/SysML, authored in Cameo) for search. "
        "The image above is a sketch redrawn from one diagram's layout; below is the diagram's content as "
        f"text. {_NOTATION} {_DEPENDENCIES}{{{{GUIDE}}}}\n\n"
        "Explain what this diagram tells a reader about the system: what it is for, what it shows the "
        "system or its parts doing or being made of, and what its main flows or dependencies achieve. "
        "Do not restate the legend or list every connection: they are already recorded exactly. Group or "
        "order elements only as the diagram itself does (nesting, frames, partitions, the order of flows). "
        "Base every statement on the text and the sketch; when the diagram shows little, say little. "
        f"{_STYLE} At most 150 words.\n\n"
        "Diagram: {{DIAGRAM}}\nLegend:\n{{LEGEND}}\nConnections:\n{{CONNECTIONS}}{{CUT_NOTE}}"
    ),
    slots=(*_DIAGRAM_SLOTS, GUIDE_SLOT, _SKETCH),
    image_first=True,
    fragments=(("cut", ("\n(Only the first {limit} shapes and connections are listed: the diagram has {shapes} "
                        "shapes and {connections} connections.)")), *GUIDE),
)

IMAGE_DESCRIPTION = Template(
    id="image-description",
    version=2,
    purpose=(
        "A description of one image embedded in the model (an attachment or image shape), for a search "
        "index, stored as a generated:image_description chunk and shown in images.md."
    ),
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

# Large diagrams (plan DV, 2026-09-30): each module is described on its own, then the
# diagram as a whole from those descriptions (FU-011). Version 2 of both (from the first live
# run on the drone sample): the answers named modules by number ("sends it to M2"), which means
# nothing outside the diagram's page.
_MODULES = ("The diagram is too large to read in one image, so its shapes have been split into modules of "
            "shapes that are connected and drawn close together.")

MODULE_DESCRIPTION = Template(
    id="module-description",
    version=3,
    purpose="A description of one module of a large diagram, for a search index, stored as a "
            "generated:module_description chunk (with the module's place in the diagram) and shown in the "
            "module's section of the diagram's page. The diagram-synthesis request builds on these.",
    text=(
        "You are helping to index a systems engineering model (UML/SysML, authored in Cameo) for search. "
        f"{_MODULES} The image above is a sketch of one module, redrawn from the diagram's layout: the "
        "module's shapes are drawn in full and the rest of the diagram is faded; shapes of other modules "
        "that connect to this one keep their numbers, at the picture's edge when they lie outside it. "
        f"Below is the module's content as text. {_NOTATION} {_DEPENDENCIES}{{{{GUIDE}}}}\n\n"
        "Explain what this part of the diagram shows about the system: what it does or is made of, what "
        "its main flows or dependencies achieve, and what it takes from or passes to the other modules, "
        "naming the shapes at the other end rather than their modules' numbers. "
        "Do not restate the legend or list every connection: they are already recorded exactly. Group or "
        "order elements only as the diagram itself does. Base every statement on the text and the sketch; "
        f"when the module shows little, say little. {_STYLE} At most 120 words.\n\n"
        "Diagram: {{DIAGRAM}}\nModule: {{MODULE}}\nLegend:\n{{LEGEND}}\nConnections within the module:\n"
        "{{CONNECTIONS}}\nConnections with other modules:\n{{BOUNDARY}}"
    ),
    slots=(
        Slot("DIAGRAM", "text", "the diagram's name and type, '<name> (<diagram type>)'."),
        Slot("MODULE", "text", "'M<k> of <n>': the module's number, in reading order, and the diagram's count."),
        Slot("LEGEND", "text",
             "one line per shape of the module, '- [<number>] <shape kind>: <label>', numbered as in the whole "
             "diagram and indented two spaces per level of nesting within the module; labels as in "
             "diagram-description. 6 to 25 lines by default (--diagram-modules)."),
        Slot("CONNECTIONS", "text",
             "one line per connection between shapes of the module, in the notation the text explains, or "
             "'(none)'."),
        Slot("BOUNDARY", "text",
             "one line per connection between a shape of the module and one of another module, whose end "
             "reads '[n] label (in M<j>)', or '(none)'."),
        GUIDE_SLOT,
        Slot("SKETCH", "image",
             "a PNG of the module's region of the diagram at the vision model's pixel budget (--image-pixels), "
             "sides in multiples of 48: the module's shapes numbered and named as in the whole sketch, other "
             "shapes faded grey, those of connected modules with their numbers, and connections leaving the "
             "picture ending in their far shape's number; the title gives the diagram and 'module M<k> of "
             "<n>'."),
    ),
    image_first=True,
    fragments=GUIDE,
)

DIAGRAM_SYNTHESIS = Template(
    id="diagram-synthesis",
    version=2,
    purpose="A description of a large diagram as a whole, for a search index, built from its modules' "
            "descriptions; stored as its generated:diagram_description chunk and shown on the diagram's page.",
    text=(
        "You are helping to index a systems engineering model (UML/SysML, authored in Cameo) for search. "
        f"{_MODULES} The image above is the whole diagram, redrawn from its layout, with each module's "
        "shapes tinted and outlined and labelled M1, M2 and so on. Below are each module's description, "
        "written from a closer view of it, and the connections between modules, whose shapes carry the "
        "numbers in the image. Connections read '[a] source →[kind: name]→ [b] target' for directed "
        "relationships and '[a] —[kind]— [b]' for undirected ones.\n\n"
        "Explain what the whole diagram tells a reader about the system: what it is for, what each module "
        "contributes, and how the modules work together, following the connections between them. Do not "
        "repeat the module descriptions; relate them. Refer to each module by what it does, not by its "
        "label (M1, M2...), which means nothing outside this diagram. Base every statement on the "
        "descriptions, the "
        f"connections and the image. {_STYLE} At most 200 words.\n\n"
        "Diagram: {{DIAGRAM}}\nModules:\n{{MODULES}}\nConnections between modules:\n{{CROSSING}}"
    ),
    slots=(
        Slot("DIAGRAM", "text", "the diagram's name and type, '<name> (<diagram type>)'."),
        Slot("MODULES", "text",
             "one paragraph per module: 'M<k> (<n> shapes): ' and its module-description answer, or '(not "
             "described)' when that request got no answer."),
        Slot("CROSSING", "text",
             "one line per connection between modules, in the notation the text explains, each end followed "
             "by '(in M<j>)', or '(none)'."),
        Slot("OVERVIEW", "image",
             "a PNG of the whole diagram at the vision model's pixel budget (--image-pixels), sides in "
             "multiples of 48: the sketch of diagram-description, with each module's shapes tinted in its "
             "colour and its region outlined and labelled M<k>."),
    ),
    image_first=True,
)

# Large packages (plan DV-05, 2026-09-30): each part is summarized on its own, then the package
# from those summaries, a level at a time when there are many (FU-005). Versions that repeat the
# task after the input were tried and not adopted (docs/research/sandwiching-2026-09-30.md).
_PARTS = ("The package is too large to summarize at once, so its elements have been split into parts of "
          "related elements, by nesting, relationships and their order in the package.")

MODULE_SUMMARY = Template(
    id="module-summary",
    version=3,
    purpose="A summary of one part of a large package, for a search index, stored as a generated:module_summary "
            "chunk (with the elements it covers) and shown in the package page's list of parts. The "
            "package-synthesis request builds on these.",
    text=(
        "You are helping to index a systems engineering model (UML/SysML, authored in Cameo) for search. "
        f"{_PARTS} Below is the extracted text of one part's elements. {{{{CUT_NOTE}}}}"
        "Summarize what this part models: its purpose, its main elements and how they relate, to each other "
        "and to elements elsewhere. Use only the information given, and do not speculate. "
        f"{_STYLE} At most 120 words.\n\nPackage: {{{{PACKAGE}}}}\nPart: {{{{PART}}}}\n---\n{{{{SECTIONS}}}}"
    ),
    slots=(
        Slot("CUT_NOTE", "text",
             "empty: parts are made to fit (plan TC-01). Kept for a fault: a sentence saying that the text was "
             "cut, and where."),
        Slot("PACKAGE", "text", "the package's qualified name."),
        Slot("PART", "text", "'<k> of <n>': the part's number, in the package's order, and the count."),
        Slot("SECTIONS", "text",
             "the part's element sections as plain text, as in package-summary: each with its kind, qualified "
             "name, stereotypes, requirement text, documentation, tagged values (long ones cut, FU-020), members, "
             f"relationships and diagrams. {PART_CHARS[0]:,} characters to the part size ({PART_CHARS[1]:,} unless "
             "calibration lowers it, plan TC) where the sections allow; a section longer than that goes in "
             "pieces, each headed by its title and a line 'Piece: i of n'."),
    ),
    fragments=(("cut", "The text was cut at {limit:,} of its {length:,} characters, so its end is missing. "),),
)

PACKAGE_SYNTHESIS = Template(
    id="package-synthesis",
    version=3,
    purpose="A summary of a large package, or of a run of its parts when there are many, built from the parts' "
            "summaries; stored as the package's generated:summary chunk (or a generated:module_summary chunk "
            "for a run of parts) and shown on the package page.",
    text=(
        "You are helping to index a systems engineering model (UML/SysML, authored in Cameo) for search. "
        f"{_PARTS} Each part has been summarized on its own. Below are the package's own section (its "
        "description and members) and the summaries of {{SCOPE}}, in the package's order. {{CUT_NOTE}}"
        "Summarize what {{SCOPE}} models: its purpose, its main elements, and how the parts relate. Do not "
        "repeat the part summaries; relate them, and refer to parts by what they cover rather than by "
        f"number. Use only the information given, and do not speculate. {_STYLE} At most 200 words."
        "\n\nPackage: {{PACKAGE}}\n---\n{{PACKAGE_TEXT}}\n---\nSummaries:\n{{SUMMARIES}}"
    ),
    slots=(
        Slot("SCOPE", "text", "'the whole package', or 'parts <a> to <b> of <n>' for a run of parts."),
        Slot("CUT_NOTE", "text",
             f"empty, or a sentence saying that the package's own section was cut at {OWN_CHARS:,} of its N "
             "characters."),
        Slot("PACKAGE", "text", "the package's qualified name."),
        Slot("PACKAGE_TEXT", "text",
             "the package's own section as plain text: kind, qualified name, documentation, tagged values and "
             f"members. At most {OWN_CHARS:,} characters."),
        Slot("SUMMARIES", "text",
             "one paragraph per part, 'Part <k> (<m> elements): ' and its module-summary answer, or per run of "
             "parts, 'Parts <a> to <b>: ' and the answer of this template for them; '(not summarized)' when a "
             f"request got no answer. At most {MAX_SUMMARIES} paragraphs: more parts are summarized in runs first."),
    ),
    fragments=(("cut", "The package's own section was cut at {limit:,} of its {length:,} characters. "),),
)

# Packages made mostly of instance specifications, such as the recorded results of an
# analysis, summarized in one request from a digest rather than in parts (FU-022).
INSTANCES_SUMMARY = Template(
    id="instances-summary",
    version=2,
    purpose="A summary of a large package made mostly of instance specifications (at least 80% of its elements), "
            "for a search index, from a digest of them; stored as the package's generated:summary chunk and shown "
            "at the top of its page.",
    text=(
        "You are helping to index a systems engineering model (UML/SysML, authored in Cameo) for search. The "
        "package below is made mostly of instance specifications, such as the recorded results of an analysis or "
        "simulation, or a configuration of parts. Instead of every instance, you are given the package's own "
        "section, a digest of its instances (how many there are of each classifier, which features their slots "
        "set, with some values, and some of their names), and its other elements. Summarize what the package "
        "records: what its instances are instances of, what their slots describe, and which analysis, scenario "
        "or configuration they belong to, as far as the names and values show. Use only the information given, "
        f"and do not speculate. {_STYLE} At most 150 words.\n\nPackage: {{{{PACKAGE}}}}\n---\n"
        "{{PACKAGE_TEXT}}\n---\nInstances:\n{{DIGEST}}\n---\nOther elements:\n{{OTHERS}}"
    ),
    slots=(
        Slot("PACKAGE", "text", "the package's qualified name."),
        Slot("PACKAGE_TEXT", "text",
             f"the package's own section as plain text, cut at {OWN_CHARS:,} characters: kind, qualified name, "
             "documentation, tagged values, then the start of its member list."),
        Slot("DIGEST", "text",
             "'<n> instance specifications of <m> classifiers.'; the top-level instances (those no other "
             "instance's slot refers to), up to 10; then per classifier, most instances first, up to 40: '- "
             "<classifier> (<kind>): <count> instances, such as <up to 3 names>', and its slots' features with "
             f"how many instances set them and up to 3 values. At most {DIGEST_CHARS[0]:,} characters, and "
             "marked where cut."),
        Slot("OTHERS", "text",
             f"the sections of the package's other elements as plain text, cut at {DIGEST_CHARS[1]:,} characters in "
             "all, or '(none)'."),
    ),
    fragments=(("cut", "\n(The digest was cut here.)"),),
)

# The versions in use, one per template. Their keys are part of a run's options, so that a project
# written with other versions is written again (FU-014).
_IN_USE = (DIAGRAM_DESCRIPTION, MODULE_DESCRIPTION, DIAGRAM_SYNTHESIS, IMAGE_DESCRIPTION, PACKAGE_SUMMARY,
           MODULE_SUMMARY, PACKAGE_SYNTHESIS, INSTANCES_SUMMARY)
CURRENT = {t.id: t for t in _IN_USE}  # by id
TEMPLATES = {t.key: t for t in _IN_USE}  # by key, as the request log names them
assert len(CURRENT) == len(_IN_USE), "two versions of one template"
