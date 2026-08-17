"""
Structured logging.

Every line is one JSON object, so a log search can filter on fields instead of grepping
prose. Each line carries the request id that produced it, which is what makes a user-reported
"it failed at 14:32" answerable: the id is returned on the response as `X-Request-ID`, and
every service call, audit event and traceback for that request shares it.
"""

from __future__ import annotations

import json
import logging
import time
import uuid
from collections.abc import Awaitable, Callable
from contextvars import ContextVar

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response
from starlette.types import ASGIApp

REQUEST_ID_HEADER = "X-Request-ID"

_request_id: ContextVar[str | None] = ContextVar("request_id", default=None)

# Attributes `logging` puts on every record; anything else a caller passed via `extra` is
# theirs and belongs in the JSON payload.
_RESERVED = frozenset(logging.LogRecord("", 0, "", 0, "", None, None).__dict__) | {
    "asctime",
    "message",
    "taskName",
}


def current_request_id() -> str | None:
    return _request_id.get()


class JsonFormatter(logging.Formatter):
    """Renders a record as a single JSON object, tracebacks included as a string field."""

    def format(self, record: logging.LogRecord) -> str:
        message = record.getMessage()
        payload: dict[str, object] = {
            "timestamp": time.strftime("%Y-%m-%dT%H:%M:%S", time.gmtime(record.created))
            + f".{int(record.msecs):03d}Z",
            "level": record.levelname,
            "logger": record.name,
        }
        # Audit events already serialise themselves; keep them queryable as fields rather
        # than as a JSON string nested inside a JSON string.
        if record.name == "askgrey.audit":
            try:
                payload.update(json.loads(message))
            except ValueError:
                payload["message"] = message
        else:
            payload["message"] = message

        request_id = current_request_id()
        if request_id:
            payload["request_id"] = request_id
        for key, value in record.__dict__.items():
            if key not in _RESERVED:
                payload[key] = value
        if record.exc_info:
            payload["exception"] = self.formatException(record.exc_info)
        return json.dumps(payload, default=str)


def configure_logging(*, level: str = "INFO", json_logs: bool = True) -> None:
    """Install one handler on the root logger, so library logs get the same treatment.

    Uvicorn installs its own handlers on `uvicorn.*`; propagating instead keeps a single
    output format rather than two interleaved ones.
    """
    handler = logging.StreamHandler()
    handler.setFormatter(
        JsonFormatter()
        if json_logs
        else logging.Formatter("%(asctime)s %(levelname)-8s %(name)s %(message)s")
    )
    root = logging.getLogger()
    root.handlers = [handler]
    root.setLevel(level.upper())
    for name in ("uvicorn", "uvicorn.error", "uvicorn.access"):
        uvicorn_logger = logging.getLogger(name)
        uvicorn_logger.handlers = []
        uvicorn_logger.propagate = True
    # Uvicorn's access line duplicates the structured one below, without the request id.
    logging.getLogger("uvicorn.access").disabled = True
    # httpx logs every outbound request at INFO with the full URL, which puts user query text
    # (search terms, compound identifiers) into the logs. Service clients log their own line
    # with the provider, outcome and status instead, so only httpx's warnings are wanted.
    logging.getLogger("httpx").setLevel(logging.WARNING)


class RequestLoggingMiddleware(BaseHTTPMiddleware):
    """Tags each request with an id and logs one access line with its outcome and duration."""

    def __init__(self, app: ASGIApp) -> None:
        super().__init__(app)
        self.logger = logging.getLogger("askgrey.request")

    async def dispatch(
        self, request: Request, call_next: Callable[[Request], Awaitable[Response]]
    ) -> Response:
        # An inbound id lets a trace span the proxy and the app; ours is a fallback.
        request_id = request.headers.get(REQUEST_ID_HEADER) or uuid.uuid4().hex
        token = _request_id.set(request_id)
        started = time.perf_counter()
        try:
            response = await call_next(request)
        except Exception:
            self.logger.exception(
                "request failed",
                extra={
                    "http_method": request.method,
                    "path": request.url.path,
                    "duration_ms": round((time.perf_counter() - started) * 1000, 1),
                },
            )
            _request_id.reset(token)
            raise
        response.headers[REQUEST_ID_HEADER] = request_id
        self.logger.info(
            "request",
            extra={
                "http_method": request.method,
                "path": request.url.path,
                "status_code": response.status_code,
                "duration_ms": round((time.perf_counter() - started) * 1000, 1),
            },
        )
        _request_id.reset(token)
        return response
