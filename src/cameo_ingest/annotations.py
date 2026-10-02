"""Derived text and images about an element (LLM descriptions, sketches), and what kind of
generated text each is: how pages label it and which kind of chunk holds it (AR-008)."""

from __future__ import annotations

from dataclasses import dataclass

from .provenance import Trace


@dataclass(frozen=True)
class AnnotationKind:
    label: str  # how pages label it
    chunk: str  # the kind of the chunk that holds it


DIAGRAM = AnnotationKind("Diagram description", "generated:diagram_description")
MODULE = AnnotationKind("Module description", "generated:module_description")  # a module of a large diagram
PART = AnnotationKind("Part summary", "generated:module_summary")  # a part of a large package
RUN = AnnotationKind("Summary of parts", "generated:module_summary")  # a run of a large package's parts
SUMMARY = AnnotationKind("Summary", "generated:summary")
IMAGE = AnnotationKind("Description", "generated:image_description")  # an image embedded in the model


@dataclass
class Annotation:
    """A piece of derived text (LLM description, rendered image...) about an element."""

    label: str
    text: str
    trace: Trace
    image: str | None = None  # path relative to the project dir
    module: int | None = None  # about this module of a large diagram, or part of a large package (plan DV)
    parts: tuple[int, int] | None = None  # about this run of a large package's parts
    kind: AnnotationKind | None = None  # generated text's kind; None for a sketch
