"""
Protocol persistence, edit changelog and version history.

Every save writes a new immutable version plus a deterministic list of changes against the
previous one, so a researcher can see exactly what an edit did — including which of their edits
replaced agent-drafted text.
"""

from __future__ import annotations

import json
from datetime import datetime
from enum import Enum

from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.protocol import ProtocolVersion, SavedProtocol

from .errors import ProtocolRequestError
from .models import DraftOrigin, ProtocolDraft

MAX_CHANGES = 200


class ChangeKind(str, Enum):
    __str__ = str.__str__

    ADDED = "added"
    REMOVED = "removed"
    MODIFIED = "modified"
    REORDERED = "reordered"


class ProtocolChange(BaseModel):
    """One entry of the changelog. `field` is dotted (`steps.step-3.instruction`)."""

    kind: ChangeKind
    field: str = Field(min_length=1, max_length=200)
    label: str = Field(min_length=1, max_length=300)
    before: str = Field(default="", max_length=1000)
    after: str = Field(default="", max_length=1000)


class ProtocolVersionSummary(BaseModel):
    version: int
    change_summary: str = ""
    changes: list[ProtocolChange] = Field(default_factory=list)
    author_user_id: str = ""
    created_at: datetime


class SavedProtocolResponse(BaseModel):
    id: str
    version: int
    protocol: ProtocolDraft
    created_at: datetime
    updated_at: datetime


class ProtocolHistoryResponse(BaseModel):
    id: str
    current_version: int
    versions: list[ProtocolVersionSummary]


class SavedProtocolSummary(BaseModel):
    """Enough to list a saved protocol without shipping every version's payload."""

    id: str
    title: str
    goal: str
    current_version: int
    created_at: datetime
    updated_at: datetime


class SaveProtocolRequest(BaseModel):
    protocol: ProtocolDraft
    change_summary: str = Field(default="", max_length=500)


_SCALAR_FIELDS = (
    ("title", "Title"),
    ("goal", "Goal"),
    ("assay_type", "Assay type"),
    ("summary", "Summary"),
    ("total_duration", "Total duration"),
)
_STEP_FIELDS = (
    ("title", "title"),
    ("instruction", "instruction"),
    ("duration", "duration"),
    ("temperature", "temperature"),
    ("critical_note", "critical note"),
)


def _clip(value: str) -> str:
    return value[:1000]


def diff_protocols(before: ProtocolDraft, after: ProtocolDraft) -> list[ProtocolChange]:
    """
    Compare two protocol versions field by field, matching steps by id.

    Reordering is reported separately from editing: moving step 4 above step 2 changes the
    protocol without changing a single word, and a changelog that showed that as two rewritten
    steps would hide what actually happened.
    """
    changes: list[ProtocolChange] = []

    for field, label in _SCALAR_FIELDS:
        old = str(getattr(before, field) or "")
        new = str(getattr(after, field) or "")
        if old != new:
            changes.append(
                ProtocolChange(
                    kind=ChangeKind.MODIFIED,
                    field=field,
                    label=label,
                    before=_clip(old),
                    after=_clip(new),
                )
            )

    old_steps = {step.id: step for step in before.steps}
    new_steps = {step.id: step for step in after.steps}

    for step_id, step in new_steps.items():
        if step_id not in old_steps:
            changes.append(
                ProtocolChange(
                    kind=ChangeKind.ADDED,
                    field=f"steps.{step_id}",
                    label=f"Step added: {step.title}",
                    after=_clip(step.instruction),
                )
            )
    for step_id, step in old_steps.items():
        if step_id not in new_steps:
            changes.append(
                ProtocolChange(
                    kind=ChangeKind.REMOVED,
                    field=f"steps.{step_id}",
                    label=f"Step removed: {step.title}",
                    before=_clip(step.instruction),
                )
            )

    for step_id, step in new_steps.items():
        old_step = old_steps.get(step_id)
        if old_step is None:
            continue
        for field, name in _STEP_FIELDS:
            old = str(getattr(old_step, field) or "")
            new = str(getattr(step, field) or "")
            if old != new:
                changes.append(
                    ProtocolChange(
                        kind=ChangeKind.MODIFIED,
                        field=f"steps.{step_id}.{field}",
                        label=f"Step {step.order} {name} edited",
                        before=_clip(old),
                        after=_clip(new),
                    )
                )
        if old_step.order != step.order:
            changes.append(
                ProtocolChange(
                    kind=ChangeKind.REORDERED,
                    field=f"steps.{step_id}.order",
                    label=f"Step moved: {step.title}",
                    before=str(old_step.order),
                    after=str(step.order),
                )
            )

    old_materials = {material.name: material for material in before.materials}
    new_materials = {material.name: material for material in after.materials}
    for name in sorted(new_materials.keys() - old_materials.keys()):
        changes.append(
            ProtocolChange(
                kind=ChangeKind.ADDED,
                field=f"materials.{name}"[:200],
                label=f"Material added: {name}"[:300],
            )
        )
    for name in sorted(old_materials.keys() - new_materials.keys()):
        changes.append(
            ProtocolChange(
                kind=ChangeKind.REMOVED,
                field=f"materials.{name}"[:200],
                label=f"Material removed: {name}"[:300],
            )
        )

    if before.expected_outcomes != after.expected_outcomes:
        changes.append(
            ProtocolChange(
                kind=ChangeKind.MODIFIED,
                field="expected_outcomes",
                label="Expected outcomes edited",
                before=_clip("; ".join(before.expected_outcomes)),
                after=_clip("; ".join(after.expected_outcomes)),
            )
        )

    return changes[:MAX_CHANGES]


def _dump(changes: list[ProtocolChange]) -> str:
    return json.dumps([change.model_dump(mode="json") for change in changes])


def _load_changes(raw: str) -> list[ProtocolChange]:
    try:
        data = json.loads(raw)
    except ValueError:
        return []
    if not isinstance(data, list):
        return []
    return [ProtocolChange.model_validate(entry) for entry in data if isinstance(entry, dict)]


def _load_protocol(version: ProtocolVersion) -> ProtocolDraft:
    return ProtocolDraft.model_validate_json(version.payload)


def create_protocol(
    db: Session, *, user_id: str, protocol: ProtocolDraft, change_summary: str = ""
) -> SavedProtocolResponse:
    """Save a protocol as version 1, with the draft exactly as it came out of the drafter."""
    record = SavedProtocol(
        user_id=user_id, title=protocol.title, goal=protocol.goal, current_version=1
    )
    db.add(record)
    db.flush()
    db.add(
        ProtocolVersion(
            protocol_id=record.id,
            version=1,
            payload=protocol.model_dump_json(),
            changes="[]",
            change_summary=change_summary or "Initial draft saved",
            author_user_id=user_id,
        )
    )
    db.commit()
    db.refresh(record)
    return SavedProtocolResponse(
        id=record.id,
        version=1,
        protocol=protocol,
        created_at=record.created_at,
        updated_at=record.updated_at,
    )


def _owned(db: Session, *, protocol_id: str, user_id: str) -> SavedProtocol:
    record = db.get(SavedProtocol, protocol_id)
    # A protocol belonging to someone else is reported as missing rather than forbidden, so the
    # endpoint does not confirm that an id exists.
    if record is None or record.user_id != user_id:
        raise ProtocolRequestError("no protocol with that id")
    return record


def _version(db: Session, *, protocol_id: str, version: int) -> ProtocolVersion:
    row = db.scalar(
        select(ProtocolVersion).where(
            ProtocolVersion.protocol_id == protocol_id, ProtocolVersion.version == version
        )
    )
    if row is None:  # pragma: no cover - a saved protocol always has its current version
        raise ProtocolRequestError("that version is missing")
    return row


MAX_LISTED = 50


def list_protocols(db: Session, *, user_id: str) -> list[SavedProtocolSummary]:
    """
    The caller's saved protocols, most recently edited first.

    Without this a save is unreachable once the page reloads: the browser holds the only pointer
    to the id, so the version history would sit on the server with no route back to it.
    """
    rows = db.scalars(
        select(SavedProtocol)
        .where(SavedProtocol.user_id == user_id)
        .order_by(SavedProtocol.updated_at.desc())
        .limit(MAX_LISTED)
    ).all()
    return [
        SavedProtocolSummary(
            id=row.id,
            title=row.title,
            goal=row.goal,
            current_version=row.current_version,
            created_at=row.created_at,
            updated_at=row.updated_at,
        )
        for row in rows
    ]


def get_protocol(db: Session, *, protocol_id: str, user_id: str) -> SavedProtocolResponse:
    record = _owned(db, protocol_id=protocol_id, user_id=user_id)
    current = _version(db, protocol_id=record.id, version=record.current_version)
    return SavedProtocolResponse(
        id=record.id,
        version=record.current_version,
        protocol=_load_protocol(current),
        created_at=record.created_at,
        updated_at=record.updated_at,
    )


def update_protocol(
    db: Session,
    *,
    protocol_id: str,
    user_id: str,
    protocol: ProtocolDraft,
    change_summary: str = "",
) -> SavedProtocolResponse:
    """
    Write the edited protocol as the next version, with its changelog.

    A protocol a researcher has edited is marked `researcher_edited`, which is the only origin
    change this system makes — and it still is not a review sign-off, so the disclaimer stays.
    """
    record = _owned(db, protocol_id=protocol_id, user_id=user_id)
    previous = _load_protocol(_version(db, protocol_id=record.id, version=record.current_version))
    changes = diff_protocols(previous, protocol)
    if not changes:
        return get_protocol(db, protocol_id=protocol_id, user_id=user_id)

    edited = protocol.model_copy(update={"origin": DraftOrigin.RESEARCHER_EDITED})
    next_version = record.current_version + 1
    db.add(
        ProtocolVersion(
            protocol_id=record.id,
            version=next_version,
            payload=edited.model_dump_json(),
            changes=_dump(changes),
            change_summary=change_summary or f"{len(changes)} change(s)",
            author_user_id=user_id,
        )
    )
    record.current_version = next_version
    record.title = edited.title
    record.updated_at = datetime.now(tz=record.created_at.tzinfo)
    db.commit()
    db.refresh(record)
    return SavedProtocolResponse(
        id=record.id,
        version=next_version,
        protocol=edited,
        created_at=record.created_at,
        updated_at=record.updated_at,
    )


def get_history(db: Session, *, protocol_id: str, user_id: str) -> ProtocolHistoryResponse:
    record = _owned(db, protocol_id=protocol_id, user_id=user_id)
    rows = db.scalars(
        select(ProtocolVersion)
        .where(ProtocolVersion.protocol_id == record.id)
        .order_by(ProtocolVersion.version.desc())
    ).all()
    return ProtocolHistoryResponse(
        id=record.id,
        current_version=record.current_version,
        versions=[
            ProtocolVersionSummary(
                version=row.version,
                change_summary=row.change_summary,
                changes=_load_changes(row.changes),
                author_user_id=row.author_user_id,
                created_at=row.created_at,
            )
            for row in rows
        ],
    )


def get_version(
    db: Session, *, protocol_id: str, user_id: str, version: int
) -> SavedProtocolResponse:
    record = _owned(db, protocol_id=protocol_id, user_id=user_id)
    row = _version(db, protocol_id=record.id, version=version)
    return SavedProtocolResponse(
        id=record.id,
        version=row.version,
        protocol=_load_protocol(row),
        created_at=record.created_at,
        updated_at=record.updated_at,
    )
