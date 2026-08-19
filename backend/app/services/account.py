"""What this account actually is: its identity, what it is storing, and how it is configured.

Every number here is counted from this account's own rows or read from deployed configuration.
The Workspace and Settings tabs used to state a plan, a seat count and a compliance posture that
nothing produced; the point of this module is that those pages can only say what is true of the
running deployment.

Nothing here is editable. Seats, roles and third-party integrations are genuinely not built, so
they are absent rather than shown as controls that do nothing.
"""

from __future__ import annotations

from datetime import datetime, timezone

from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.config import Settings, get_settings
from app.models.audit import AuditEvent
from app.models.library import SavedArtifact
from app.models.literature import LiteratureDocument
from app.models.session import RefreshSession
from app.models.user import User
from app.services import literature as literature_service


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _as_utc(value: datetime) -> datetime:
    """SQLite hands back naive datetimes even for timezone-aware columns."""
    return value if value.tzinfo is not None else value.replace(tzinfo=timezone.utc)


class AccountIdentity(BaseModel):
    email: str
    full_name: str
    role: str
    # "password" or "oidc": which credential this account actually signs in with.
    provider: str
    created_at: datetime


class StorageUsage(BaseModel):
    """The papers this account is storing, and when they stop being served."""

    stored_papers: int
    stored_bytes: int
    retention_days: int
    # None when nothing is stored, rather than a date the account cannot see the basis for.
    next_expiry: datetime | None


class SavedWork(BaseModel):
    """Saved artifacts per tab, so Workspace can show what work exists to reference."""

    counts: dict[str, int]
    total: int
    last_saved_at: datetime | None


class ActiveSession(BaseModel):
    """One unexpired, unrevoked refresh session.

    Deliberately no device or location: the app never collected either, and inventing them is
    exactly the kind of claim this module exists to remove.
    """

    id: str
    issued_at: datetime
    expires_at: datetime


class UpstreamStatus(BaseModel):
    """Whether a data source this app calls is configured, and what follows from that."""

    name: str
    detail: str
    configured: bool


class PlatformFacts(BaseModel):
    environment: str
    release: str
    llm_model: str
    extraction_available: bool
    # "kms", "local-key" or "derived-from-jwt-secret" — the last is development only.
    document_encryption: str
    access_token_ttl_minutes: int
    refresh_token_ttl_days: int
    audit_retention_days: int
    llm_daily_call_budget: int


class AccountOverview(BaseModel):
    account: AccountIdentity
    storage: StorageUsage
    saved_work: SavedWork
    audit_events: int
    sessions: list[ActiveSession]
    upstreams: list[UpstreamStatus]
    platform: PlatformFacts


def active_sessions(db: Session, user_id: str) -> list[ActiveSession]:
    rows = db.scalars(
        select(RefreshSession)
        .where(
            RefreshSession.user_id == user_id,
            RefreshSession.revoked_at.is_(None),
            RefreshSession.expires_at > _now(),
        )
        .order_by(RefreshSession.issued_at.desc())
    ).all()
    return [
        ActiveSession(
            id=row.id,
            issued_at=_as_utc(row.issued_at),
            expires_at=_as_utc(row.expires_at),
        )
        for row in rows
    ]


def _storage(db: Session, user_id: str, settings: Settings) -> StorageUsage:
    live = (
        LiteratureDocument.user_id == user_id,
        LiteratureDocument.expires_at > _now(),
    )
    count = db.scalar(select(func.count()).select_from(LiteratureDocument).where(*live)) or 0
    soonest = db.scalar(select(func.min(LiteratureDocument.expires_at)).where(*live))
    return StorageUsage(
        stored_papers=int(count),
        stored_bytes=literature_service.stored_bytes(db, user_id),
        retention_days=settings.document_retention_days,
        next_expiry=_as_utc(soonest) if soonest is not None else None,
    )


def _saved_work(db: Session, user_id: str) -> SavedWork:
    rows = db.execute(
        select(SavedArtifact.kind, func.count(), func.max(SavedArtifact.updated_at))
        .where(SavedArtifact.user_id == user_id)
        .group_by(SavedArtifact.kind)
    ).all()
    counts = {str(kind): int(total) for kind, total, _ in rows}
    latest = [updated for *_, updated in rows if updated is not None]
    return SavedWork(
        counts=counts,
        total=sum(counts.values()),
        last_saved_at=_as_utc(max(latest)) if latest else None,
    )


def _upstreams(settings: Settings) -> list[UpstreamStatus]:
    """The external systems the agents read from, and whether this deployment can reach them.

    Read from configuration, so an unkeyed deployment says so instead of showing a connected
    integration that would fail on first use.
    """
    return [
        UpstreamStatus(
            name="Anthropic",
            detail=(
                f"{settings.llm_model} — query translation, extraction, drafting and review"
                if settings.anthropic_api_key
                else "No API key: extraction, drafting and review are unavailable"
            ),
            configured=bool(settings.anthropic_api_key),
        ),
        UpstreamStatus(
            name="PubMed (NCBI Entrez)",
            detail=(
                "Keyed — 10 requests per second"
                if settings.ncbi_api_key
                else "Unkeyed — 3 requests per second, shared across this deployment"
            ),
            configured=True,
        ),
        UpstreamStatus(
            name="PubChem",
            detail="Compound lookup and descriptors for Screening",
            configured=True,
        ),
        UpstreamStatus(
            name="ClinicalTrials.gov",
            detail="Trial search, v2 API",
            configured=True,
        ),
        UpstreamStatus(
            name="Grants.gov and SBIR.gov",
            detail="Federal opportunity search",
            configured=True,
        ),
        UpstreamStatus(
            name="USPTO Open Data",
            detail=(
                "Keyed — patent search in Screening"
                if settings.uspto_odp_api_key
                else "No API key: patent search returns an unavailable state"
            ),
            configured=bool(settings.uspto_odp_api_key),
        ),
    ]


def overview(db: Session, user: User) -> AccountOverview:
    """Everything the Workspace and Settings tabs render, counted per request.

    The counts are small aggregates over one account's rows, and the pages are not polled, so
    there is nothing here worth caching and going stale over.
    """
    settings = get_settings()
    user_id = str(user.id)
    events = (
        db.scalar(select(func.count()).select_from(AuditEvent).where(AuditEvent.user_id == user_id))
        or 0
    )
    return AccountOverview(
        account=AccountIdentity(
            email=user.email,
            full_name=user.full_name,
            role=user.role.value,
            provider=user.provider.value,
            created_at=_as_utc(user.created_at),
        ),
        storage=_storage(db, user_id, settings),
        saved_work=_saved_work(db, user_id),
        audit_events=int(events),
        sessions=active_sessions(db, user_id),
        upstreams=_upstreams(settings),
        platform=PlatformFacts(
            environment=settings.environment,
            release=settings.release,
            llm_model=settings.llm_model,
            extraction_available=bool(settings.anthropic_api_key),
            document_encryption=settings.document_encryption_scheme,
            access_token_ttl_minutes=settings.access_token_ttl_minutes,
            refresh_token_ttl_days=settings.refresh_token_ttl_days,
            audit_retention_days=settings.audit_retention_days,
            llm_daily_call_budget=settings.llm_daily_call_budget,
        ),
    )


__all__ = [
    "AccountOverview",
    "ActiveSession",
    "active_sessions",
    "overview",
]
