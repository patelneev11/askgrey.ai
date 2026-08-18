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
"""

from __future__ import annotations

import json
from datetime import datetime
from enum import Enum

from pydantic import BaseModel, Field, JsonValue, ValidationError
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.library import SavedArtifact
from app.services.grants.budget import GrantBudget
from app.services.grants.eligibility import EligibilityReport
from app.services.grants.review_board import BoardReport
from app.services.regulatory.ind import IndDraft
from app.services.regulatory.preclinical import PreclinicalReport
from app.services.screening.admet import AdmetProfile
from app.services.screening.patents import PatentLandscape
from app.services.screening.sar import DescriptorProfile, SuggestionSet

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
        payload=_validated(kind, stored),
        created_at=record.created_at,
        updated_at=record.updated_at,
    )


def save_artifact(db: Session, *, user_id: str, request: SaveArtifactRequest) -> SavedArtifactRead:
    """Store one output under the calling account."""
    record = SavedArtifact(
        user_id=user_id,
        kind=request.kind.value,
        title=request.title,
        subtitle=request.subtitle,
        payload=json.dumps(_validated(request.kind, request.payload)),
    )
    db.add(record)
    db.commit()
    db.refresh(record)
    return _read(record)


def list_artifacts(
    db: Session, *, user_id: str, kind: ArtifactKind | None = None
) -> list[SavedArtifactSummary]:
    """The caller's saved artifacts, most recent first, optionally narrowed to one kind."""
    query = select(SavedArtifact).where(SavedArtifact.user_id == user_id)
    if kind is not None:
        query = query.where(SavedArtifact.kind == kind.value)
    rows = db.scalars(query.order_by(SavedArtifact.updated_at.desc()).limit(MAX_LISTED)).all()
    return [
        SavedArtifactSummary(
            id=row.id,
            kind=ArtifactKind(row.kind),
            title=row.title,
            subtitle=row.subtitle,
            created_at=row.created_at,
            updated_at=row.updated_at,
        )
        for row in rows
    ]


def _owned(db: Session, *, artifact_id: str, user_id: str) -> SavedArtifact:
    record = db.get(SavedArtifact, artifact_id)
    # Someone else's artifact is reported as missing rather than forbidden, so the endpoint does
    # not confirm that an id exists.
    if record is None or record.user_id != user_id:
        raise LibraryRequestError("no saved item with that id")
    return record


def get_artifact(db: Session, *, artifact_id: str, user_id: str) -> SavedArtifactRead:
    return _read(_owned(db, artifact_id=artifact_id, user_id=user_id))


def delete_artifact(db: Session, *, artifact_id: str, user_id: str) -> None:
    db.delete(_owned(db, artifact_id=artifact_id, user_id=user_id))
    db.commit()
