"""
Benchling ELN export: internal protocol -> Benchling entry payload.

STATUS: schema-ready, UNTESTED AGAINST THE LIVE API. This module was written against Benchling's
public developer documentation for entries (`POST /api/v2/entries` and the entry `days[].notes[]`
note-block structure); no request has ever been sent to a real Benchling tenant from this repo,
and no credentials exist in this environment. Treat field names as documented-but-unverified until
someone runs it against a real account, and expect to adjust `customFields`/`fields` to whatever
that tenant's entry schema actually defines.

Deliberately, this module only *builds* a payload. Nothing here performs HTTP, so there is no
outbound request to a caller-supplied URL, and no credential is read, logged or returned. When a
real integration is added later, the token belongs in server-side settings and must stay out of
the response body and out of logs: the export response is designed to be safe to hand to the
browser, so it must never grow a token, tenant URL or auth header field.
"""

from __future__ import annotations

import re
from enum import Enum
from typing import Any

from pydantic import BaseModel, Field

from .models import REVIEW_DISCLAIMER, ProtocolDraft

# Benchling resource ids are prefixed, opaque and alphanumeric (e.g. "lib_A1b2C3", "tmpl_...").
# Bounded and pattern-checked so a caller cannot smuggle a path or a URL into a request body that
# a future live client would interpolate into a request path.
_BENCHLING_ID = re.compile(r"^[A-Za-z0-9_\-]{1,64}$")

# The one string the exported record must always carry, so a protocol that leaves AskGrey does
# not arrive in an ELN looking like a reviewed one.
EXPORT_NOTICE = (
    f"{REVIEW_DISCLAIMER} Drafted in AskGrey and exported without laboratory validation."
)

INTEGRATION_STATUS = "schema_ready_untested"
INTEGRATION_NOTE = (
    "Built from Benchling's public API documentation and never exercised against a live "
    "Benchling account. Field names and entry structure are unverified; review the payload "
    "before importing it."
)


class NoteBlockType(str, Enum):
    """The subset of Benchling's documented note-block types this exporter emits."""

    __str__ = str.__str__

    TEXT = "text"
    LIST_BULLET = "list_bullet"
    LIST_NUMBER = "list_number"


class BenchlingNoteBlock(BaseModel):
    type: NoteBlockType
    text: str = Field(min_length=1, max_length=4000)


class BenchlingEntry(BaseModel):
    """The entry-creation body, matching the documented `POST /api/v2/entries` shape."""

    name: str = Field(min_length=1, max_length=300)
    folderId: str  # noqa: N815 - Benchling's documented field name is camelCase.
    entryTemplateId: str | None = None  # noqa: N815
    schemaId: str | None = None  # noqa: N815
    customFields: dict[str, dict[str, str]] = Field(default_factory=dict)  # noqa: N815


class ElnExportRequest(BaseModel):
    protocol: ProtocolDraft
    folder_id: str = Field(min_length=1, max_length=64)
    entry_template_id: str | None = Field(default=None, max_length=64)
    schema_id: str | None = Field(default=None, max_length=64)
    entry_name: str = Field(default="", max_length=300)


class ElnExportPayload(BaseModel):
    """
    What a live client would POST, plus the caveats that must travel with it.

    `integration_status` is part of the payload so the UI cannot present this as a verified
    export: the button that renders this response has to say it is untested.
    """

    provider: str = "benchling"
    integration_status: str = INTEGRATION_STATUS
    integration_note: str = INTEGRATION_NOTE
    endpoint: str = "POST /api/v2/entries"
    entry: BenchlingEntry
    notes: list[BenchlingNoteBlock]
    warnings: list[str] = Field(default_factory=list)


class ElnExportError(ValueError):
    """The request cannot be turned into a Benchling payload."""


def _check_id(value: str | None, field: str) -> str | None:
    if value is None or value == "":
        return None
    if not _BENCHLING_ID.match(value):
        raise ElnExportError(
            f"{field} must be a Benchling resource id (letters, digits, '_' or '-')"
        )
    return value


def _text(block: str) -> BenchlingNoteBlock:
    return BenchlingNoteBlock(type=NoteBlockType.TEXT, text=block[:4000])


def _bullet(block: str) -> BenchlingNoteBlock:
    return BenchlingNoteBlock(type=NoteBlockType.LIST_BULLET, text=block[:4000])


def _numbered(block: str) -> BenchlingNoteBlock:
    return BenchlingNoteBlock(type=NoteBlockType.LIST_NUMBER, text=block[:4000])


def _material_line(material: Any) -> str:
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


def _step_line(step: Any) -> str:
    line = f"{step.title}: {step.instruction}"
    conditions = [value for value in (step.duration, step.temperature) if value]
    if conditions:
        line += f" ({', '.join(conditions)})"
    if step.equipment:
        line += f" [equipment: {', '.join(step.equipment)}]"
    if step.critical_note:
        line += f" [critical: {step.critical_note}]"
    return line


def build_note_blocks(protocol: ProtocolDraft) -> list[BenchlingNoteBlock]:
    """
    Render the protocol as note blocks, leading with the review notice.

    The notice is the first block on purpose: whoever opens the entry in Benchling sees that this
    was drafted rather than reviewed before they read a single step.
    """
    blocks = [_text(EXPORT_NOTICE), _text(f"Experimental goal: {protocol.goal}")]
    if protocol.summary:
        blocks.append(_text(protocol.summary))
    if protocol.assay_type:
        blocks.append(_text(f"Assay type: {protocol.assay_type}"))
    if protocol.materials:
        blocks.append(_text("Materials"))
        blocks.extend(_bullet(_material_line(material)) for material in protocol.materials)
    blocks.append(_text("Method"))
    blocks.extend(_numbered(_step_line(step)) for step in protocol.steps)
    if protocol.total_duration:
        blocks.append(_text(f"Total duration: {protocol.total_duration}"))
    if protocol.expected_outcomes:
        blocks.append(_text("Expected outcomes"))
        blocks.extend(_bullet(outcome) for outcome in protocol.expected_outcomes)
    return blocks


def build_export(request: ElnExportRequest) -> ElnExportPayload:
    """Transform a protocol into a Benchling entry payload. No network call is made."""
    protocol = request.protocol
    folder_id = _check_id(request.folder_id, "folder_id")
    if folder_id is None:
        raise ElnExportError("folder_id is required to create a Benchling entry")

    warnings = [INTEGRATION_NOTE]
    if request.schema_id and not request.entry_template_id:
        warnings.append(
            "A schemaId without an entryTemplateId only validates; entry content still comes "
            "from the note blocks below."
        )
    if not protocol.materials:
        warnings.append("The protocol lists no materials, so the entry has no materials section.")

    entry = BenchlingEntry(
        name=(request.entry_name or protocol.title)[:300],
        folderId=folder_id,
        entryTemplateId=_check_id(request.entry_template_id, "entry_template_id"),
        schemaId=_check_id(request.schema_id, "schema_id"),
        customFields={
            "AskGrey protocol goal": {"value": protocol.goal[:500]},
            "AskGrey content origin": {"value": protocol.origin.value},
            "AskGrey review status": {"value": REVIEW_DISCLAIMER},
        },
    )
    return ElnExportPayload(entry=entry, notes=build_note_blocks(protocol), warnings=warnings)
