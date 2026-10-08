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
from dataclasses import dataclass, replace

_SLOT = re.compile(r"\{\{([A-Z_]+)\}\}")

# What a request may hold (AR-009): used by the request builders (`prompt_values`), and stated in the
# slots' descriptions.
DIAGRAM_ITEMS = 150  # shapes, and connections, listed with a diagram
SUMMARY_CHARS = 12_000  # a package summarized in one request; a larger one in parts
PART_CHARS = (3_000, 12_000)  # a large package's parts: the smallest worth its own request, and the limit
OWN_CHARS = 6_000  # a large package's own section, sent with its parts' summaries
MAX_SUMMARIES = 30  # summaries per synthesis request; more are summarized in runs first
# An instances digest, and the text of the package's other elements, at the default part size; they
# follow the part size in use (`digest_chars`), so that calibration guards them as it guards a part.
DIGEST_CHARS = (8_000, 4_000)


def digest_chars(part_chars: int) -> tuple[int, int]:
    """The digest's limits for a part size: two thirds and one third of it (8,000 and 4,000 of 12,000)."""
    return part_chars * DIGEST_CHARS[0] // PART_CHARS[1], part_chars * DIGEST_CHARS[1] // PART_CHARS[1]
CONTEXT_CHARS = (400, 200, 3_000)  # context (plan GS): a package's, each shape's first sentence, a diagram's in all


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
    classes: tuple[str, ...] = ()  # an answer starts with 'Class: <one of these>' (plan GS)

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
             f"how many instances set them and up to 3 values. At most {DIGEST_CHARS[0]:,} characters at the default "
             "part size, two thirds of the part size in use, and "
             "marked where cut."),
        Slot("OTHERS", "text",
             f"the sections of the package's other elements as plain text, cut at {DIGEST_CHARS[1]:,} characters (a "
             "third of the part size) in "
             "all, or '(none)'."),
    ),
    fragments=(("cut", "\n(The digest was cut here.)"),),
)



# -- Variants (plan GS): requests for what search by meaning needs -------------------------------
# Built from the requests in use before 0.20.0 (`current/plain`, above): +1, the same with context;
# +2, the `about` request; +3, the `about` request with context, in use since 0.20.0. A variant
# swaps its templates into CURRENT for an experiment (scripts/build_variant.py).

PACKAGE_CLASSES = (
    ("intent", "it states purposes, rationale or how things are meant to work"),
    ("structure", "parts, types and relationships, with little stated purpose"),
    ("register", "many like items told apart by names and values, such as sites, instruments or test runs"),
    ("requirements", "requirement statements"),
    ("behavior", "activities, states or sequences"),
    ("library", "types, units or stereotypes for reuse"),
    ("results", "the recorded values of an analysis or a configuration"),
    ("sparse", "too little to say anything"),
)
DIAGRAM_CLASSES = (
    ("flow", "an activity or process: what is done, and in what order"),
    ("states", "modes or states, and what changes them"),
    ("structure", "parts and types, and how they are composed"),
    ("interfaces", "what passes between parts, through ports and connectors"),
    ("requirements", "requirements, and what satisfies, verifies or derives them"),
    ("overview", "a context or summary picture of a system and its surroundings"),
    ("sparse", "too little to say anything"),
)
_SEARCH = ("You are helping people find things in a systems engineering model (UML/SysML, authored in Cameo) by "
           "searching in their own words. ")
_PLAIN_PROSE = ("Don't use the elements' names, identifiers or exact values: the index has them already. Write plain "
                "prose, without headings, lists, bold or code formatting, at most 80 words.")


def _classify(what: str, classes: tuple[tuple[str, str], ...]) -> str:
    listed = "; ".join(f"{c} ({d})" for c, d in classes)
    return f"First, on a line of its own, classify {what}: 'Class: <class>', where <class> is one of: {listed}. "


def _about_package(what: str, scope: str) -> str:
    return (_classify(what, PACKAGE_CLASSES)
            + f"Then say what {scope} is about and what it is for, as someone searching for it would put it: the "
            "concerns it addresses, the purposes it serves and the kinds of things it covers, in everyday words and "
            "the domain's common terms. Infer the purpose where the text implies it, and say nothing it doesn't "
            "support. " + _PLAIN_PROSE)


def _about_diagram(what: str, scope: str) -> str:
    return (_classify(what, DIAGRAM_CLASSES)
            + f"Then say what {scope} is about and what it is for, as someone searching for it would put it: what it "
            "shows the system doing or being made of, and why that matters, in everyday words and the domain's "
            "common terms. Infer the purpose where the text and the sketch imply it, and say nothing they don't "
            "support. " + _PLAIN_PROSE)


_CONTEXT_PACKAGE = ("\n\nFor context only (not to be summarized), where the package sits in the model, and what it "
                    "refers to outside itself:\n{{CONTEXT}}")
_CONTEXT_DIAGRAM = ("\n\nFor context only, what the diagram's context and its shapes are, from the model's "
                    "documentation and behaviors:\n{{CONTEXT}}")
_CONTEXT_SLOTS = {
    "package": Slot("CONTEXT", "text",
                    "'The model <name>: <documentation>', then 'Within <name>: <documentation>' for each package "
                    "around it, outermost first, each cut at 400 characters; then 'It refers to:' and up to 10 "
                    "lines '- <kind> <name>: <first sentence>' for the documented elements outside the package that "
                    "its elements refer to most. At most 3,000 characters; '(none)'."),
    "diagram": Slot("CONTEXT", "text",
                    "'Context, <kind> <name>: <first sentence>' for the diagram's context element, then one line per "
                    "shape whose element is documented or has behaviors, '- [<number>] <label>: <first sentence of "
                    "its documentation>', with '; entry/do/exit: <behavior>' for a state's behaviors. At most 3,000 "
                    "characters; '(none)'."),
}
# Where each template's input begins: the context goes just before it.
_BODIES = {
    "package-summary": "\n\n---\n{{PACKAGE_TEXT}}",
    "module-summary": "\n\nPackage: {{PACKAGE}}\nPart: {{PART}}",
    "package-synthesis": "\n\nPackage: {{PACKAGE}}\n---\n{{PACKAGE_TEXT}}",
    "instances-summary": "\n\nPackage: {{PACKAGE}}\n---\n{{PACKAGE_TEXT}}",
    "diagram-description": "\n\nDiagram: {{DIAGRAM}}\nLegend:",
    "diagram-synthesis": "\n\nDiagram: {{DIAGRAM}}\nModules:",
}
_ABOUT_TEXTS = {
    "package-summary": (
        _SEARCH + "Below is the extracted text of one package: the package's own description and members, then a "
        "section for each element in it. " + _about_package("the package", "this package")),
    "module-summary": (
        _SEARCH + f"{_PARTS} Below is the extracted text of one part's elements. {{{{CUT_NOTE}}}}"
        + _about_package("this part", "this part of the package")),
    "package-synthesis": (
        _SEARCH + f"{_PARTS} Each part has been described on its own. Below are the package's own section (its "
        "description and members) and the descriptions of {{SCOPE}}, in the package's order. {{CUT_NOTE}}"
        + _about_package("{{SCOPE}} as a whole", "{{SCOPE}}") + " Relate the parts; don't repeat their descriptions."),
    "instances-summary": (
        _SEARCH + "The package below is made mostly of instance specifications, such as the recorded results of an "
        "analysis or simulation, or a configuration of parts. Instead of every instance, you are given the "
        "package's own section, a digest of its instances (how many there are of each classifier, which features "
        "their slots set, with some values, and some of their names), and its other elements. "
        + _about_package("the package", "this package")),
    "diagram-description": (
        _SEARCH + "The image above is a sketch redrawn from one diagram's layout; below is the diagram's content as "
        f"text. {_NOTATION} {_DEPENDENCIES}{{{{GUIDE}}}}\n\n" + _about_diagram("the diagram", "this diagram")),
    "diagram-synthesis": (
        _SEARCH + f"{_MODULES} The image above is the whole diagram, redrawn from its layout, with each module's "
        "shapes tinted and outlined and labelled M1, M2 and so on. Below are each module's description, written "
        "from a closer view of it, and the connections between modules, whose shapes carry the numbers in the "
        "image. Connections read '[a] source →[kind: name]→ [b] target' for directed relationships and "
        "'[a] —[kind]— [b]' for undirected ones.\n\n" + _about_diagram("the whole diagram", "the whole diagram")
        + " Relate the modules; don't repeat their descriptions or refer to them by label (M1, M2...)."),
}


def _candidate(base: Template, about: bool, context: bool) -> Template:
    body = _BODIES[base.id]
    kind = "diagram" if base.id.startswith("diagram") else "package"
    head, sep, tail = base.text.partition(body)
    assert sep, f"{base.key}: no body marker"
    if about:
        head = _ABOUT_TEXTS[base.id]
    extra = (_CONTEXT_DIAGRAM if kind == "diagram" else _CONTEXT_PACKAGE) if context else ""
    classes = tuple(c for c, _ in (DIAGRAM_CLASSES if kind == "diagram" else PACKAGE_CLASSES)) if about else ()
    return replace(base, version=base.version + (3 if about and context else 2 if about else 1),
                   text=head + extra + sep + tail, classes=classes,
                   slots=base.slots + ((_CONTEXT_SLOTS[kind],) if context else ()),
                   purpose=base.purpose + (" Plan GS: " + ", ".join(
                       x for x, on in (("about", about), ("with context", context)) if on) + "."))


_VARIED = (PACKAGE_SUMMARY, MODULE_SUMMARY, PACKAGE_SYNTHESIS, INSTANCES_SUMMARY, DIAGRAM_DESCRIPTION, DIAGRAM_SYNTHESIS)
VARIANTS = {  # name -> the templates it puts in CURRENT, by id
    "current/plain": {t.id: t for t in _VARIED},  # in use before 0.20.0
    "current/context": {t.id: _candidate(t, False, True) for t in _VARIED},
    "about/plain": {t.id: _candidate(t, True, False) for t in _VARIED},
    "about/context": {t.id: _candidate(t, True, True) for t in _VARIED},
}

# The versions in use, one per template. Their keys are part of a run's options, so that a project
# written with other versions is written again (FU-014). Since 0.20.0 (plan GS, ADR-0029), packages
# and diagrams are asked what they are about and for, with context.
_ABOUT = VARIANTS["about/context"]
_IN_USE = (_ABOUT["diagram-description"], MODULE_DESCRIPTION, _ABOUT["diagram-synthesis"], IMAGE_DESCRIPTION,
           _ABOUT["package-summary"], _ABOUT["module-summary"], _ABOUT["package-synthesis"],
           _ABOUT["instances-summary"])
CURRENT = {t.id: t for t in _IN_USE}  # by id
TEMPLATES = {t.key: t for t in _IN_USE}  # by key, as the request log names them
assert len(CURRENT) == len(_IN_USE), "two versions of one template"
_ALL = {t.key: t for t in (*_IN_USE, *(t for v in VARIANTS.values() for t in v.values()))}
assert len(_ALL) == len(_IN_USE) + 3 * len(_VARIED), "two variants share a version"


def split_class(key: str | None, answer: str) -> tuple[str | None, str]:
    """An answer's class and text (plan GS): for a template that classifies, the class from a
    first line 'Class: <class>', or 'unknown' when it's missing or not one of the template's;
    for one that doesn't, (None, the answer)."""
    t = _ALL.get(key or "")
    if t is None or not t.classes:
        return None, answer
    first, _, rest = answer.strip().partition("\n")
    m = re.fullmatch(r"[*_#\s]*class[*_\s]*:[*_\s]*([a-z]+)[*_.\s]*", first, re.IGNORECASE)
    if m is None:
        return "unknown", answer.strip()
    found = m.group(1).lower()
    return (found if found in t.classes else "unknown"), rest.strip()



# Subjects for discovery (plan SB, ADR-0031): asked at the root, for each family of versions of a
# model, after the projects are built. Outside CURRENT, since they change no project's options.
# The wording is the one the panel judged (`evaluation.subject_llm`, plan SB-05).
SUBJECTS_PROPOSE = Template(
    id="subjects-propose", version=1,
    purpose="Ways to organize a model's diagrams into subjects for discovery, each on its own principle (ADR-0031).",
    text=("Below is an outline of one systems engineering model (UML/SysML, authored in Cameo), named {{MODEL}}, "
          "with {{COUNT}} diagrams: its packages, with how many diagrams each holds, and example diagrams. A person "
          "wants to discover the different things this model covers. Propose {{WAYS}} different ways to organize its "
          "diagrams into about {{K}} subjects. Each way should follow its own principle (for example, by part of the "
          "system, by engineering activity, or by kind of concern), and every diagram should fit one subject of "
          "each way. Give each subject a label of 2 to 5 words and one sentence on what it holds.\n\n{{OUTLINE}}\n\n"
          "Reply with JSON only: {\"ways\": [{\"principle\": \"...\", \"subjects\": [{\"label\": \"...\", "
          "\"holds\": \"...\"}, ...]}, ...]}."),
    slots=(Slot("MODEL", "text", "the model's name (its newest version's file name)."),
           Slot("COUNT", "text", "the number of diagrams, each counted once across versions."),
           Slot("WAYS", "text", "how many ways to propose (subjects.WAYS)."),
           Slot("K", "text", "about how many subjects: the square root of half the diagrams, 2 to 15."),
           Slot("OUTLINE", "text", "the packages, three levels deep, with their diagram counts (at most 80), and "
                                   "60 example diagrams spread over the model: name, owner, kind, about text.")),
)

SUBJECTS_ASSIGN = Template(
    id="subjects-assign", version=1,
    purpose="Put each of a batch of a model's diagrams in one subject of a proposed way (ADR-0031).",
    text=("A systems engineering model's diagrams are being organized into these subjects:\n{{SUBJECTS}}\n\n"
          "Put each diagram below in the one subject it fits best.\n\n{{DIAGRAMS}}\n\n"
          "Reply with JSON only, the subject's number for every diagram's number: {\"1\": 3, \"2\": 1, ...}."),
    slots=(Slot("SUBJECTS", "text", "the way's subjects, numbered: label, and what each holds."),
           Slot("DIAGRAMS", "text", "at most 30 diagrams, numbered, cut by package: name, owner, kind, about text.")),
)

# Topics across models (plan SB CP4): asked at the root after the families' subjects, over every
# family's subjects in its suggested view. Outside CURRENT, as the subjects' templates are.
TOPICS_PROPOSE = Template(
    id="topics-propose", version=1,
    purpose="Topics that cut across a collection of models, from each model's subjects (plan SB CP4).",
    text=("Below are the subjects of {{MODELS}} systems engineering models (UML/SysML, authored in Cameo), each "
          "model's diagrams already organized into a few subjects. A person wants to discover what the collection "
          "covers, and to find what different models hold on the same thing together. Propose about {{K}} topics "
          "that cut across the models: each topic should gather subjects of several models where it can, and every "
          "subject should fit one topic. Give each topic a label of 2 to 5 words and one sentence on what it "
          "holds.\n\nSubjects (label, model: what it holds):\n{{SUBJECTS}}\n\n"
          "Reply with JSON only: {\"topics\": [{\"label\": \"...\", \"holds\": \"...\"}, ...]}."),
    slots=(Slot("MODELS", "text", "how many models (families of versions) the subjects come from."),
           Slot("K", "text", "about how many topics: the square root of half the subjects, 2 to 15."),
           Slot("SUBJECTS", "text", "every subject, a line each: label, model, what it holds (cut short); at "
                                    "most 400, spread over the collection.")),
)

TOPICS_ASSIGN = Template(
    id="topics-assign", version=1,
    purpose="Put each of a batch of models' subjects in one topic across models (plan SB CP4).",
    text=("Subjects of several systems engineering models are being gathered into these topics:\n{{TOPICS}}\n\n"
          "Put each subject below in the one topic it fits best.\n\n{{SUBJECTS}}\n\n"
          "Reply with JSON only, the topic's number for every subject's number: {\"1\": 3, \"2\": 1, ...}."),
    slots=(Slot("TOPICS", "text", "the topics, numbered: label, and what each holds."),
           Slot("SUBJECTS", "text", "at most 30 subjects, numbered: label, model, what it holds, and three of "
                                    "its diagrams.")),
)
