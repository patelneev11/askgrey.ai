"""
Structured audit logging for security-relevant events.

One line per event on the `askgrey.audit` logger, with the fields a reviewer actually needs:
who, what, from where, and the outcome. Never log credentials, tokens, API keys, document
contents or extracted values — the event records that a document was sent, not what it said.

A document's own name says what it is about, so values under a naming key are replaced by a
fingerprint before anything is written (see `_redacted`).

Pass `db` and `user_id` as well and the event is also kept as a row, which is what the Audit
Trails tab reads (`app.services.audit`). The log line is written either way: an event the
database rejected is still an event, and the aggregator is the record of last resort.
"""

from __future__ import annotations

import hashlib
import json
import logging
from typing import TYPE_CHECKING, Literal

if TYPE_CHECKING:  # pragma: no cover - import cycle: the service imports the models, not this.
    from sqlalchemy.orm import Session

logger = logging.getLogger("askgrey.audit")

Outcome = Literal["success", "failure", "denied"]

# Detail keys whose value would name the subject of the user's work. `trial_ziprasidone_qt.pdf`
# is the finding itself, not metadata about it, so the trail keeps a fingerprint instead: two
# events about the same document still line up, and neither says what the document is about.
NAMING_KEYS = frozenset(
    {
        "document_title",
        "file_name",
        "filename",
        "path",
        "query",
        "source",
        "source_url",
        "title",
        "url",
    }
)


def fingerprint(value: str) -> str:
    """A short, stable, one-way stand-in for a name — correlatable, not reversible."""
    return hashlib.sha256(value.encode("utf-8", "replace")).hexdigest()[:12]


def _redacted(
    detail: dict[str, str | int | float | bool | None],
) -> dict[str, str | int | float | bool | None]:
    redacted: dict[str, str | int | float | bool | None] = {}
    for key, value in detail.items():
        if key in NAMING_KEYS and isinstance(value, str) and value:
            redacted[f"{key}_fingerprint"] = fingerprint(value)
        else:
            redacted[key] = value
    return redacted


def record(
    event: str,
    *,
    outcome: Outcome = "success",
    actor: str | None = None,
    client_ip: str | None = None,
    detail: dict[str, str | int | float | bool | None] | None = None,
    db: Session | None = None,
    user_id: str | None = None,
) -> None:
    payload: dict[str, object] = {
        "event": event,
        "outcome": outcome,
        "actor": actor,
        "client_ip": client_ip,
    }
    safe_detail = _redacted(detail) if detail else {}
    payload.update(safe_detail)
    logger.info(json.dumps({key: value for key, value in payload.items() if value is not None}))
    if db is not None and user_id is not None:
        # Imported here, not at module scope: the service reaches the models and the settings,
        # and this module is imported by nearly everything that could be logged.
        from app.services import audit as audit_service

        audit_service.record_event(
            db,
            event=event,
            user_id=user_id,
            outcome=outcome,
            client_ip=client_ip,
            detail=dict(safe_detail),
        )
