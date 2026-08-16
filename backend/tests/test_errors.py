from typing import cast

from sentry_sdk.types import Event

from app.core.config import Settings
from app.core.errors import _scrub, init_error_tracking


def test_reporting_stays_off_until_a_dsn_is_configured() -> None:
    # Development and CI must not need a Sentry project to boot.
    assert init_error_tracking(Settings()) is False


def test_the_request_body_and_cookies_never_leave_the_process() -> None:
    event = cast(
        Event,
        {
            "request": {
                "data": "the full text of an uploaded paper",
                "cookies": {"askgrey_refresh": "a-valid-session"},
                "headers": {
                    "Authorization": "Bearer token",
                    "Cookie": "askgrey_refresh=a-valid-session",
                    "X-Api-Key": "sk-ant-secret",
                    "User-Agent": "Chrome",
                },
            }
        },
    )

    scrubbed = _scrub(event, {})

    request = scrubbed["request"]
    assert "data" not in request
    assert "cookies" not in request
    headers = request["headers"]
    assert headers["Authorization"] == "[redacted]"
    assert headers["Cookie"] == "[redacted]"
    assert headers["X-Api-Key"] == "[redacted]"
    # Scrubbing has to leave enough behind to debug with.
    assert headers["User-Agent"] == "Chrome"


def test_an_event_without_a_request_passes_through_untouched() -> None:
    event = cast(Event, {"message": "background job failed"})

    assert _scrub(event, {}) == {"message": "background job failed"}
