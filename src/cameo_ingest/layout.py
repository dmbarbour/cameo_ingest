"""MagicDraw diagram layout streams (`BINARY-<uuid>` entries, root `<mdOwnedViews>`).

Each `mdElement` is a presentation element: `elementClass` (shape kind), an optional
`elementID` idref to the model element shown, `geometry` ("x, y, w, h" for shapes or
"x1, y1; x2, y2; ..." for paths), nested `mdOwnedViews`, and for paths
`linkFirstEndID` / `linkSecondEndID` pointing at other presentation elements.
Coordinates are absolute diagram coordinates.

A tree of generalizations (plan SK) is a `Tree` element: a horizontal bar (`horizontalBarLeft`,
`horizontalBarRight`, `horizontalBarY`) and a vertical bar from the parent shape (`baseShape`,
at `verticalBarX` from its left edge and `verticalBarY`) to it. Each member path names it by
`treeID`, and runs only from its child to the bar.
"""

from __future__ import annotations

import logging
import re
from collections.abc import Collection
from dataclasses import dataclass, field
from typing import IO

from lxml import etree

from .richtext import to_text

log = logging.getLogger(__name__)

# Presentation-only helpers that carry no model meaning.
NON_VISUAL = {
    "BooleanProperty", "ChoiceProperty", "ColorProperty", "FontProperty", "NumberProperty",
    "ExtendableManager", "PropertyManagerByDiagram", "PropertyManagerByStereotype",
    "SimpleStyle", "ElementProperty", "StringProperty", "PropertyManager", "ElementListProperty",
    "IntegerProperty", "DiagramPropertiesShape",
}
_NUM = re.compile(r"-?\d+(?:\.\d+)?")
TREE_BARS = ("verticalBarX", "verticalBarY", "horizontalBarLeft", "horizontalBarRight", "horizontalBarY")


def _number(text: str | None) -> float | None:
    m = _NUM.search(text or "")
    return float(m.group(0)) if m else None


@dataclass
class View:
    view_id: str | None
    cls: str
    element: str | None  # model element id (may be an href into a used project)
    rect: tuple[float, float, float, float] | None = None
    points: list[tuple[float, float]] = field(default_factory=list)
    text: str | None = None
    first: str | None = None  # view ids at the ends of a path
    second: str | None = None
    parent: str | None = None  # view id of the enclosing view
    tree: str | None = None  # a path's tree of generalizations (the Tree view's id)
    base: str | None = None  # a Tree's parent shape (its view id)
    bars: tuple[float, float, float, float, float] | None = None  # a Tree's verticalBarX, verticalBarY,
    #                                                                horizontalBarLeft, horizontalBarRight, horizontalBarY

    @property
    def is_path(self) -> bool:
        return bool(self.points) or self.first is not None


@dataclass
class Layout:
    views: list[View] = field(default_factory=list)

    def by_view_id(self) -> dict[str, View]:
        return {v.view_id: v for v in self.views if v.view_id}

    def elements(self) -> list[str]:
        return list(dict.fromkeys(v.element for v in self.views if v.element))


def _local(attr: str) -> str:
    # Streams may use `xmi:` prefixes without declaring them; lxml (recover mode) then
    # keeps the literal "xmi:id" name, otherwise we get "{uri}id".
    return re.split(r"[}:]", attr)[-1]


def _attr(node, local: str) -> str | None:
    for k, v in node.attrib.items():
        if _local(k) == local:
            return v
    return None


def _idref(node) -> str | None:
    return _attr(node, "idref") or node.get("href")


def _geometry(text: str) -> tuple[tuple[float, float, float, float] | None, list[tuple[float, float]]]:
    text = text.strip()
    if ";" in text:
        pts = []
        for seg in text.split(";"):
            nums = [float(n) for n in _NUM.findall(seg)]
            if len(nums) >= 2:
                pts.append((nums[0], nums[1]))
        return None, pts
    nums = [float(n) for n in _NUM.findall(text)]
    if len(nums) >= 4:
        return (nums[0], nums[1], nums[2], nums[3]), []
    return None, []


def own_elements(layout: Layout, ids: Collection[str]) -> None:
    """A view naming the project's own element through its file (`file.mdzip#id`) names it by
    its id (FU-019)."""
    for v in layout.views:
        if v.element and v.element not in ids and "#" in v.element:
            own = v.element.rpartition("#")[2]
            if own in ids:
                v.element = own


def parse_layout(stream: IO[bytes]) -> Layout:
    """Parse one layout stream. Tolerates unknown child elements."""
    parser = etree.XMLParser(huge_tree=True, resolve_entities=False, no_network=True, recover=True)
    tree = etree.parse(stream, parser)
    out = Layout()

    def walk(node, parent_view: str | None) -> None:
        for md in node.iterchildren("mdElement"):
            cls = md.get("elementClass") or ""
            if cls in NON_VISUAL:
                continue
            vid = _attr(md, "id")
            view = View(view_id=vid, cls=cls, element=None, parent=parent_view)
            bars: dict[str, float | None] = {}
            for child in md.iterchildren():
                tag = child.tag if isinstance(child.tag, str) else ""
                if tag == "elementID":
                    view.element = _idref(child)
                elif tag == "geometry" and child.text:
                    view.rect, view.points = _geometry(child.text)
                elif tag == "text" and child.text:
                    view.text = to_text(child.text)  # a note's or text box's text can be HTML, as documentation is
                elif tag == "linkFirstEndID":
                    view.first = _idref(child)
                elif tag == "linkSecondEndID":
                    view.second = _idref(child)
                elif tag == "treeID":
                    view.tree = _idref(child)
                elif tag == "baseShape":
                    view.base = _idref(child)
                elif tag in TREE_BARS:
                    bars[tag] = _number(_attr(child, "value"))
            if cls == "Tree" and all(bars.get(k) is not None for k in TREE_BARS):
                view.bars = tuple(bars[k] for k in TREE_BARS)  # type: ignore[assignment]
            out.views.append(view)
            for owned in md.iterchildren("mdOwnedViews"):
                walk(owned, vid)

    root = tree.getroot()
    if root is None:
        return out
    walk(root, None)
    return out
