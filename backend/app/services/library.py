"""
The saved library: agent outputs a researcher explicitly chose to keep.

Every tab in the app produces something — a descriptor profile, a preclinical narrative, a budget,
a mock review — that until now lived only in the open browser tab. This module persists those
outputs per account so they can be reopened later, without changing when they are produced: a row
is written only when the researcher presses save.

Payloads are re-validated against the model the endpoint returned rather than stored as free-form
JSON. That is a safety property, not tidiness: each of those models carries its own review notice,
confidence wording and "unvalidated" flags, so a reopened artifact renders the caveats it was born
with instead of whatever the frontend would supply today. A payload that no longer parses is
rejected on the way in.

Protocols keep their own tables: they are the one output with real version history, and folding
them in here would lose the per-edit diffs.

An artifact saved while the researcher is working in a shared workspace belongs to that workspace
and is readable by its members; saved otherwise it is private, which is what every row written
before workspaces existed remains. Callers pass the `Access` the workspace service issued rather
than a workspace id, so this module can never be asked to read a workspace the caller is not in.
"""

from __future__ import annotations

import json
from datetime import datetime
from enum import Enum

from pydantic import BaseModel, Field, JsonValue, ValidationError
from sqlalchemy import and_, or_, select
from sqlalchemy.orm import Session
from sqlalchemy.sql.elements import ColumnElement

from app.models.library import SavedArtifact
from app.services.grants.budget import GrantBudget
from app.services.grants.eligibility import EligibilityReport
from app.services.grants.review_board import BoardReport
from app.services.regulatory.ind import IndDraft
from app.services.regulatory.preclinical import PreclinicalReport
from app.services.screening.admet import AdmetProfile
from app.services.screening.patents import PatentLandscape
from app.services.screening.sar import DescriptorProfile, SuggestionSet
from app.services.workspaces import Access

# One page of saved work; the list is a picker, not an archive browser.
MAX_LISTED = 50
# A stored artifact is a single API response. Anything larger than this is not one of ours.
MAX_PAYLOAD_CHARS = 200_000


class ScreeningProfile(BaseModel):
    """
    The two reads the screening tab makes of one structure, kept as a single saved item.

    Descriptors and ADMET are produced together and are meaningless apart on that page, so they
    are stored together. Each half is its own model, so both keep their own caveat text.
    """

    descriptors: DescriptorProfile
    admet: AdmetProfile


class LibraryError(Exception):
    """Base class for library failures."""


class LibraryRequestError(LibraryError):
    """The caller asked for something that does not exist, or sent something unstorable."""


class LibraryPermissionError(LibraryError):
    """The item exists and the caller can see it, but not do this to it."""


class ArtifactKind(str, Enum):
    """Which output an artifact is. Closed set: an unknown kind has no model to validate against."""

    __str__ = str.__str__

    SCREENING_PROFILE = "screening_profile"
    SCREENING_DESCRIPTORS = "screening_descriptors"
    SCREENING_ADMET = "screening_admet"
    SCREENING_SUGGESTIONS = "screening_suggestions"
    SCREENING_PATENTS = "screening_patents"
    REGULATORY_PRECLINICAL = "regulatory_preclinical"
    REGULATORY_IND = "regulatory_ind"
    GRANTS_ELIGIBILITY = "grants_eligibility"
    GRANTS_BUDGET = "grants_budget"
    GRANTS_REVIEW_BOARD = "grants_review_board"


PAYLOAD_MODELS: dict[ArtifactKind, type[BaseModel]] = {
    ArtifactKind.SCREENING_PROFILE: ScreeningProfile,
    ArtifactKind.SCREENING_DESCRIPTORS: DescriptorProfile,
    ArtifactKind.SCREENING_ADMET: AdmetProfile,
    ArtifactKind.SCREENING_SUGGESTIONS: SuggestionSet,
    ArtifactKind.SCREENING_PATENTS: PatentLandscape,
    ArtifactKind.REGULATORY_PRECLINICAL: PreclinicalReport,
    ArtifactKind.REGULATORY_IND: IndDraft,
    ArtifactKind.GRANTS_ELIGIBILITY: EligibilityReport,
    ArtifactKind.GRANTS_BUDGET: GrantBudget,
    ArtifactKind.GRANTS_REVIEW_BOARD: BoardReport,
}


class SaveArtifactRequest(BaseModel):
    kind: ArtifactKind
    title: str = Field(min_length=1, max_length=300)
    subtitle: str = Field(default="", max_length=500)
    payload: dict[str, JsonValue]


class SavedArtifactSummary(BaseModel):
    """Enough to list a saved artifact and reopen it, without shipping its payload."""

    id: str
    kind: ArtifactKind
    title: str
    subtitle: str
    # Which account saved it, and whether it is shared: a workspace list mixes colleagues' work
    # with your own, and a row that does not say whose it is invites the wrong assumption.
    saved_by_user_id: str
    workspace_id: str | None
    created_at: datetime
    updated_at: datetime


class SavedArtifactRead(SavedArtifactSummary):
    payload: dict[str, JsonValue]


def _validated(kind: ArtifactKind, payload: dict[str, JsonValue]) -> dict[str, JsonValue]:
    """
    Round-trip the payload through the model its endpoint returned.

    Storing the model's own dump rather than the caller's object means a browser cannot smuggle
    extra fields into the store, and cannot strip a review notice on the way in either.
    """
    model = PAYLOAD_MODELS[kind]
    try:
        parsed = model.model_validate(payload)
    except ValidationError as exc:
        raise LibraryRequestError(f"that payload is not a valid {kind} result") from exc
    dumped: dict[str, JsonValue] = parsed.model_dump(mode="json")
    if len(json.dumps(dumped)) > MAX_PAYLOAD_CHARS:
        raise LibraryRequestError("that result is too large to save")
    return dumped


def _read(record: SavedArtifact) -> SavedArtifactRead:
    kind = ArtifactKind(record.kind)
    stored: dict[str, JsonValue] = json.loads(record.payload)
    return SavedArtifactRead(
        id=record.id,
        kind=kind,
        title=record.title,
        subtitle=record.subtitle,
        saved_by_user_id=record.user_id,
        workspace_id=record.workspace_id,
        payload=_validated(kind, stored),
        created_at=record.created_at,
        updated_at=record.updated_at,
    )


def save_artifact(
    db: Session,
    *,
    user_id: str,
    request: SaveArtifactRequest,
    workspace: Access | None = None,
) -> SavedArtifactRead:
    """Store one output, shared with the workspace the caller is working in if there is one."""
    if workspace is not None and not workspace.may_write:
        raise LibraryPermissionError("viewers of this workspace cannot save work into it")
    record = SavedArtifact(
        user_id=user_id,
        workspace_id=workspace.workspace_id if workspace is not None else None,
        kind=request.kind.value,
        title=request.title,
        subtitle=request.subtitle,
        payload=json.dumps(_validated(request.kind, request.payload)),
    )
    db.add(record)
    db.commit()
    db.refresh(record)
    return _read(record)


def _readable(user_id: str, workspace: Access | None) -> ColumnElement[bool]:
    """
    The rows this caller may see: their own private work, plus the active workspace's shared work.

    Their private work stays visible inside a workspace on purpose — a researcher switching into a
    workspace has not filed their own drafts away, and a picker that hid them would push people to
    re-save the same result twice.
    """
    private = and_(SavedArtifact.user_id == user_id, SavedArtifact.workspace_id.is_(None))
    if workspace is None:
        return private
    return or_(private, SavedArtifact.workspace_id == workspace.workspace_id)


def list_artifacts(
    db: Session,
    *,
    user_id: str,
    kind: ArtifactKind | None = None,
    workspace: Access | None = None,
) -> list[SavedArtifactSummary]:
    """The saved artifacts this caller can see, most recent first, optionally narrowed to a kind."""
    query = select(SavedArtifact).where(_readable(user_id, workspace))
    if kind is not None:
        query = query.where(SavedArtifact.kind == kind.value)
    rows = db.scalars(query.order_by(SavedArtifact.updated_at.desc()).limit(MAX_LISTED)).all()
    return [
        SavedArtifactSummary(
            id=row.id,
            kind=ArtifactKind(row.kind),
            title=row.title,
            subtitle=row.subtitle,
            saved_by_user_id=row.user_id,
            workspace_id=row.workspace_id,
            created_at=row.created_at,
            updated_at=row.updated_at,
        )
        for row in rows
    ]


def _visible(
    db: Session, *, artifact_id: str, user_id: str, workspace: Access | None
) -> SavedArtifact:
    record = db.get(SavedArtifact, artifact_id)
    # An artifact the caller cannot see is reported as missing rather than forbidden, so the
    # endpoint does not confirm that an id exists.
    if record is None:
        raise LibraryRequestError("no saved item with that id")
    own = record.user_id == user_id and record.workspace_id is None
    shared = workspace is not None and record.workspace_id == workspace.workspace_id
    if not own and not shared:
        raise LibraryRequestError("no saved item with that id")
    return record


def get_artifact(
    db: Session, *, artifact_id: str, user_id: str, workspace: Access | None = None
) -> SavedArtifactRead:
    return _read(_visible(db, artifact_id=artifact_id, user_id=user_id, workspace=workspace))


def delete_artifact(
    db: Session, *, artifact_id: str, user_id: str, workspace: Access | None = None
) -> None:
    """
    Remove a saved item.

    Shared work can be removed by whoever saved it and by the workspace's admins; a member cannot
    delete a colleague's contribution, which is the difference between a shared library and a
    shared drawer anyone can empty.
    """
    record = _visible(db, artifact_id=artifact_id, user_id=user_id, workspace=workspace)
    if record.user_id != user_id and not (workspace is not None and workspace.may_administer):
        raise LibraryPermissionError("only an admin can delete work someone else saved")
    db.delete(record)
    db.commit()
