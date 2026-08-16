import json
import logging

import pytest
from fastapi.testclient import TestClient

from app.core.logging import (
    REQUEST_ID_HEADER,
    JsonFormatter,
    configure_logging,
    current_request_id,
)


def record(**extra: object) -> logging.LogRecord:
    made = logging.LogRecord("askgrey.test", logging.INFO, "f.py", 1, "hello", None, None)
    made.__dict__.update(extra)
    return made


def test_a_line_is_one_json_object_with_the_standard_fields() -> None:
    payload = json.loads(JsonFormatter().format(record(status_code=200)))

    assert payload["level"] == "INFO"
    assert payload["logger"] == "askgrey.test"
    assert payload["message"] == "hello"
    assert payload["status_code"] == 200
    assert payload["timestamp"].endswith("Z")


def test_audit_events_are_flattened_into_queryable_fields() -> None:
    # The audit logger already emits JSON; nesting it as a string would make it ungreppable.
    audited = logging.LogRecord(
        "askgrey.audit",
        logging.INFO,
        "f.py",
        1,
        json.dumps({"event": "login", "ok": True}),
        None,
        None,
    )

    payload = json.loads(JsonFormatter().format(audited))

    assert payload["event"] == "login"
    assert payload["ok"] is True


def test_a_traceback_travels_as_a_field_rather_than_extra_lines() -> None:
    try:
        raise ValueError("boom")
    except ValueError:
        formatted = JsonFormatter().format(
            logging.LogRecord(
                "askgrey.test",
                logging.ERROR,
                "f.py",
                1,
                "failed",
                None,
                __import__("sys").exc_info(),
            )
        )

    payload = json.loads(formatted)
    assert "ValueError: boom" in payload["exception"]
    assert "\n" not in formatted.strip()


def test_plain_text_mode_is_available_for_a_human_reading_a_terminal() -> None:
    configure_logging(level="DEBUG", json_logs=False)
    root = logging.getLogger()
    try:
        assert not isinstance(root.handlers[0].formatter, JsonFormatter)
        assert root.level == logging.DEBUG
    finally:
        configure_logging()


def test_the_response_carries_the_request_id_that_the_logs_are_keyed_by(
    client: TestClient, caplog: pytest.LogCaptureFixture
) -> None:
    with caplog.at_level(logging.INFO, logger="askgrey.request"):
        response = client.get("/api/health")

    request_id = response.headers[REQUEST_ID_HEADER]
    assert request_id
    logged = [r for r in caplog.records if r.name == "askgrey.request"]
    assert logged and logged[0].__dict__["path"] == "/api/health"
    assert logged[0].__dict__["status_code"] == 200
    assert isinstance(logged[0].__dict__["duration_ms"], float)


def test_an_inbound_request_id_is_kept_so_a_trace_spans_the_proxy(client: TestClient) -> None:
    response = client.get("/api/health", headers={REQUEST_ID_HEADER: "abc123"})

    assert response.headers[REQUEST_ID_HEADER] == "abc123"


def test_the_id_does_not_leak_between_requests(client: TestClient) -> None:
    first = client.get("/api/health").headers[REQUEST_ID_HEADER]
    second = client.get("/api/health").headers[REQUEST_ID_HEADER]

    assert first != second
    # Outside a request there is nothing to attribute a log line to.
    assert current_request_id() is None
