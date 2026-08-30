"""
The notebook-neutral record: what leaves AskGrey when work goes into someone's ELN.

Deliberately not a Benchling entry, a LabArchives page or anything else vendor-shaped. Every
electronic lab notebook accepts a document and an attachment, and none of them agree on an API,
so the record is defined once here in terms every notebook has — a title, some fields, headed
sections of text, bullets and numbered steps — and rendered into files a notebook can ingest.
A vendor API client, when a tenant exists to test it against, maps this same record instead of
reaching back into the protocol model.
"""

from __future__ import annotations

import re
from datetime import datetime, timezone
from enum import Enum

from pydantic import BaseModel, Field

from app.services.protocols.models import REVIEW_DISCLAIMER, ProtocolDraft, ProtocolMaterial
from app.services.protocols.models import ProtocolStep as Step

MAX_BLOCK_CHARS = 4000
MAX_BLOCKS_PER_SECTION = 200
MAX_SECTIONS = 20

# The sentence the record carries into the notebook. A protocol that arrives in an ELN must not
# look reviewed just because it arrived as a tidy document.
HANDOFF_NOTICE = (
    f"{REVIEW_DISCLAIMER} Drafted in AskGrey and exported without laboratory validation."
)

_SLUG_STRIP = re.compile(r"[^a-z0-9]+")


class BlockKind(str, Enum):
    """The three shapes every notebook's editor has in common."""

    __str__ = str.__str__

    TEXT = "text"
    BULLET = "bullet"
    NUMBER = "number"


class Block(BaseModel):
    kind: BlockKind
    text: str = Field(min_length=1, max_length=MAX_BLOCK_CHARS)


class Section(BaseModel):
    heading: str = Field(default="", max_length=200)
    blocks: list[Block] = Field(default_factory=list, max_length=MAX_BLOCKS_PER_SECTION)


class ElnRecord(BaseModel):
    """
    One piece of saved work, ready to be rendered for a notebook.

    `notice` and `fields` are part of the record rather than presentation state: whoever opens
    the imported document sees the provenance and the review requirement without having to be
    told separately where the content came from.
    """

    title: str = Field(min_length=1, max_length=300)
    notice: str = HANDOFF_NOTICE
    fields: dict[str, str] = Field(default_factory=dict)
    sections: list[Section] = Field(default_factory=list, max_length=MAX_SECTIONS)
    exported_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))

    def slug(self) -> str:
        """A filename stem from the title, or a stable fallback when it has no usable letters."""
        stem = _SLUG_STRIP.sub("-", self.title.lower()).strip("-")
        return stem[:60] or "eln-record"


def _clip(value: str) -> str:
    return value[:MAX_BLOCK_CHARS]


def _text(value: str) -> Block:
    return Block(kind=BlockKind.TEXT, text=_clip(value))


def _bullet(value: str) -> Block:
    return Block(kind=BlockKind.BULLET, text=_clip(value))


def _numbered(value: str) -> Block:
    return Block(kind=BlockKind.NUMBER, text=_clip(value))


def material_line(material: ProtocolMaterial) -> str:
    parts = [material.name]
    if material.amount:
        parts.append(material.amount)
    if material.storage:
        parts.append(f"storage {material.storage}")
    if material.vendor_or_catalog:
        parts.append(material.vendor_or_catalog)
    if material.note:
        parts.append(material.note)
    return " — ".join(parts)


def step_line(step: Step) -> str:
    line = f"{step.title}: {step.instruction}"
    conditions = [value for value in (step.duration, step.temperature) if value]
    if conditions:
        line += f" ({', '.join(conditions)})"
    if step.equipment:
        line += f" [equipment: {', '.join(step.equipment)}]"
    if step.critical_note:
        line += f" [critical: {step.critical_note}]"
    return line


def record_from_protocol(protocol: ProtocolDraft) -> ElnRecord:
    """Turn a protocol draft into the neutral record, keeping the ordering of the bench steps."""
    fields = {
        "Experimental goal": protocol.goal[:500],
        "Content origin": protocol.origin.value,
        "Review status": REVIEW_DISCLAIMER,
    }
    if protocol.assay_type:
        fields["Assay type"] = protocol.assay_type
    if protocol.total_duration:
        fields["Total duration"] = protocol.total_duration
    if protocol.model:
        fields["Drafting model"] = protocol.model

    sections: list[Section] = []
    if protocol.summary:
        sections.append(Section(heading="Summary", blocks=[_text(protocol.summary)]))
    if protocol.materials:
        sections.append(
            Section(
                heading="Materials",
                blocks=[_bullet(material_line(material)) for material in protocol.materials],
            )
        )
    sections.append(
        Section(
            heading="Method",
            blocks=[_numbered(step_line(step)) for step in sorted(protocol.steps, key=order_of)],
        )
    )
    if protocol.expected_outcomes:
        sections.append(
            Section(
                heading="Expected outcomes",
                blocks=[_bullet(outcome) for outcome in protocol.expected_outcomes],
            )
        )
    return ElnRecord(title=protocol.title, fields=fields, sections=sections)


def order_of(step: Step) -> int:
    return step.order
