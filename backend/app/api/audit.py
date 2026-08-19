from typing import Annotated

from fastapi import APIRouter, Query
from pydantic import BaseModel, Field

from app.api.deps import DbSession, ThrottledUser
from app.core.config import get_settings
from app.services import audit as audit_service
from app.services.audit import Kind

router = APIRouter(prefix="/audit", tags=["audit"])


class AuditEventRead(BaseModel):
    id: str
    occurred_at: str
    event: str
    kind: Kind
    outcome: str
    client_ip: str
    # Provenance only: which document id, how many bytes, which model, which scope. Never
    # document text, an extracted value or a prompt — see app.core.audit.
    detail: dict[str, object] = Field(default_factory=dict)


class AuditFeed(BaseModel):
    events: list[AuditEventRead]
    # What the tab may honestly claim about retention, read from configuration rather than
    # written into the page.
    retention_days: int


@router.get("/events", response_model=AuditFeed)
def read_events(
    user: ThrottledUser,
    db: DbSession,
    kind: Kind | None = None,
    limit: Annotated[int, Query(ge=1, le=audit_service.MAX_EVENTS_PER_PAGE)] = 100,
) -> AuditFeed:
    """This account's own security events, newest first.

    Scoped to the caller: there is no parameter for whose events to read, so one tenant cannot
    ask for another's. Events with no account attached (a sign-in attempt for an address that
    does not exist, a rate limit hit before any account is known) are in the logs but are
    served to nobody.
    """
    rows = audit_service.recent_events(db, str(user.id), kind=kind, limit=limit)
    return AuditFeed(
        events=[
            AuditEventRead(
                id=row.id,
                occurred_at=audit_service.occurred_at(row).isoformat(),
                event=row.event,
                kind=audit_service.kind_of(row),
                outcome=row.outcome,
                client_ip=row.client_ip,
                detail=audit_service.detail_of(row),
            )
            for row in rows
        ],
        retention_days=get_settings().audit_retention_days,
    )
