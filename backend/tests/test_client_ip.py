from collections.abc import Callable

import pytest
from fastapi import Request
from fastapi.testclient import TestClient

from app.api import deps
from app.core.config import Settings


def _request(peer: str, forwarded: str | None = None) -> Request:
    headers = [(b"x-forwarded-for", forwarded.encode())] if forwarded is not None else []
    return Request(
        {
            "type": "http",
            "http_version": "1.1",
            "method": "GET",
            "scheme": "http",
            "path": "/api/auth/login",
            "raw_path": b"/api/auth/login",
            "query_string": b"",
            "root_path": "",
            "headers": headers,
            "client": (peer, 51234),
            "server": ("testserver", 80),
        }
    )


TrustHops = Callable[[int], None]


@pytest.fixture
def hops(monkeypatch: pytest.MonkeyPatch) -> TrustHops:
    """Run `client_ip` as if the app were deployed behind `count` proxies it controls."""

    def _set(count: int) -> None:
        settings = Settings(trusted_proxy_hops=count)
        monkeypatch.setattr(deps, "get_settings", lambda: settings)

    return _set


def test_without_a_trusted_proxy_the_peer_address_wins(hops: TrustHops) -> None:
    hops(0)

    # A client that sets the header itself must not be able to choose its own rate-limit key.
    assert deps.client_ip(_request("10.0.0.1", "203.0.113.9")) == "10.0.0.1"


def test_one_trusted_proxy_uses_the_address_the_proxy_recorded(hops: TrustHops) -> None:
    hops(1)

    assert deps.client_ip(_request("10.0.0.1", "203.0.113.9")) == "203.0.113.9"


def test_spoofed_entries_to_the_left_are_ignored(hops: TrustHops) -> None:
    hops(1)

    # The attacker prepends whatever it likes; only the entry the edge proxy appended counts.
    forwarded = "127.0.0.1, 198.51.100.7, 203.0.113.9"
    assert deps.client_ip(_request("10.0.0.1", forwarded)) == "203.0.113.9"


def test_two_trusted_proxies_step_two_entries_back(hops: TrustHops) -> None:
    hops(2)

    forwarded = "203.0.113.9, 198.51.100.7"
    assert deps.client_ip(_request("10.0.0.1", forwarded)) == "203.0.113.9"


def test_a_chain_shorter_than_the_claimed_hops_falls_back_to_the_leftmost(hops: TrustHops) -> None:
    hops(3)

    # Trusting position -3 of a one-entry chain would read past the end; the leftmost entry is
    # the most conservative answer available.
    assert deps.client_ip(_request("10.0.0.1", "203.0.113.9")) == "203.0.113.9"


def test_a_missing_header_behind_a_proxy_falls_back_to_the_peer(hops: TrustHops) -> None:
    hops(1)

    assert deps.client_ip(_request("10.0.0.1")) == "10.0.0.1"


@pytest.mark.parametrize("forwarded", ["", " ", " , "])
def test_an_empty_forwarded_chain_falls_back_to_the_peer(forwarded: str, hops: TrustHops) -> None:
    hops(1)

    assert deps.client_ip(_request("10.0.0.1", forwarded)) == "10.0.0.1"


def test_a_request_without_a_peer_is_still_keyable(hops: TrustHops) -> None:
    hops(0)
    scope = dict(_request("10.0.0.1").scope)
    scope["client"] = None

    assert deps.client_ip(Request(scope)) == "unknown"


def test_negative_hops_are_rejected_at_boot() -> None:
    with pytest.raises(ValueError, match="TRUSTED_PROXY_HOPS"):
        Settings(trusted_proxy_hops=-1)


def test_forwarded_clients_get_separate_auth_allowances(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The regression this guards: behind a proxy every visitor shared one bucket.

    With one trusted hop, exhausting the sign-in allowance from one forwarded address must not
    lock out a different one.
    """
    monkeypatch.setattr(deps, "get_settings", lambda: Settings(trusted_proxy_hops=1))
    deps.auth_ip_limiter.limit = 1
    try:
        attacker = {"X-Forwarded-For": "203.0.113.9"}
        first = client.post("/api/auth/login", json=_CREDENTIALS, headers=attacker)
        blocked = client.post("/api/auth/login", json=_CREDENTIALS, headers=attacker)
        bystander = client.post(
            "/api/auth/login", json=_CREDENTIALS, headers={"X-Forwarded-For": "198.51.100.7"}
        )
    finally:
        deps.auth_ip_limiter.limit = deps._settings.auth_rate_limit_per_minute

    assert first.status_code == 401
    assert blocked.status_code == 429
    assert bystander.status_code == 401


_CREDENTIALS = {"email": "proxy@example.com", "password": "correct horse battery"}
