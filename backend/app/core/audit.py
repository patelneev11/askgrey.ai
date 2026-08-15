"""
Structured audit logging for security-relevant events.

One line per event on the `askgrey.audit` logger, with the fields a reviewer actually needs:
who, what, from where, and the outcome. Never log credentials, tokens, API keys, document
contents or extracted values — the event records that a document was sent, not what it said.
"""

from __future__ import annotations

import json
import logging
from typing import Literal

logger = logging.getLogger("askgrey.audit")

Outcome = Literal["success", "failure", "denied"]


def record(
    event: str,
    *,
    outcome: Outcome = "success",
    actor: str | None = None,
    client_ip: str | None = None,
    detail: dict[str, str | int | float | bool | None] | None = None,
) -> None:
    payload: dict[str, object] = {
        "event": event,
        "outcome": outcome,
        "actor": actor,
        "client_ip": client_ip,
    }
    if detail:
        payload.update(detail)
    logger.info(json.dumps({key: value for key, value in payload.items() if value is not None}))
