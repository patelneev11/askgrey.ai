"""
Error tracking.

Runtime failures should reach us before a user reports them, but an error tracker sees
everything the app sees, so what leaves the process matters: request bodies carry document
text and credentials, and this app's whole security posture assumes neither is copied to a
third party. `send_default_pii=False` plus the scrubbing below is what makes reporting safe
to leave on in production.

With no DSN configured this is a no-op, which is how development and CI run.
"""

from __future__ import annotations

import logging

import sentry_sdk
from sentry_sdk.integrations.fastapi import FastApiIntegration
from sentry_sdk.integrations.logging import LoggingIntegration
from sentry_sdk.integrations.starlette import StarletteIntegration
from sentry_sdk.types import Event, Hint

from app.core.config import Settings

logger = logging.getLogger("askgrey.errors")

# Header and cookie names whose values must never leave the process. Sentry's own scrubber
# covers `Authorization`; the refresh cookie is ours to know about.
SENSITIVE_KEYS = frozenset(
    {"authorization", "cookie", "set-cookie", "x-api-key", "askgrey_refresh"}
)


def _scrub(event: Event, _hint: Hint) -> Event:
    request = event.get("request")
    if isinstance(request, dict):
        # The body of an extraction request is document text; the query string of a search is
        # the researcher's question. Neither is needed to fix a crash.
        request.pop("data", None)
        request.pop("cookies", None)
        headers = request.get("headers")
        if isinstance(headers, dict):
            for key in list(headers):
                if key.lower() in SENSITIVE_KEYS:
                    headers[key] = "[redacted]"
    return event


def init_error_tracking(settings: Settings) -> bool:
    """Start Sentry when a DSN is configured. Returns whether reporting is on."""
    if not settings.sentry_dsn:
        return False
    sentry_sdk.init(
        dsn=settings.sentry_dsn,
        environment=settings.environment,
        release=settings.release,
        traces_sample_rate=settings.sentry_traces_sample_rate,
        send_default_pii=False,
        max_request_body_size="never",
        before_send=_scrub,
        integrations=[
            StarletteIntegration(),
            FastApiIntegration(),
            # WARNING and above become events; INFO stays as breadcrumbs, which is what makes
            # the LLM spend alert visible in Sentry without shipping every request log there.
            LoggingIntegration(level=logging.INFO, event_level=logging.WARNING),
        ],
    )
    logger.info("error tracking enabled", extra={"release": settings.release})
    return True
