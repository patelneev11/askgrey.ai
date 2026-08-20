from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import Session

from app.core import audit as audit_log
from app.core.config import get_settings
from app.models.audit import AuditEvent
from app.services import audit as service

CREDENTIALS = {"email": "librarian@askgrey.ai", "password": "obsidian-workspace-1"}
OTHER = {"email": "stranger@askgrey.ai", "password": "obsidian-workspace-2"}


def auth_header(client: TestClient, credentials: dict[str, str]) -> dict[str, str]:
    tokens = client.post("/api/auth/register", json=credentials).json()
    return {"Authorization": f"Bearer {tokens['access_token']}"}


def feed(client: TestClient, headers: dict[str, str], query: str = "") -> dict[str, object]:
    response = client.get(f"/api/audit/events{query}", headers=headers)
    assert response.status_code == 200
    body: dict[str, object] = response.json()
    return body


def events(client: TestClient, headers: dict[str, str], query: str = "") -> list[dict[str, object]]:
    listed = feed(client, headers, query)["events"]
    assert isinstance(listed, list)
    return listed


def test_the_feed_requires_authentication(client: TestClient) -> None:
    assert client.get("/api/audit/events").status_code == 401


def test_signing_in_is_on_the_account_s_own_feed(client: TestClient) -> None:
    headers = auth_header(client, CREDENTIALS)

    names = [event["event"] for event in events(client, headers)]

    assert "auth.register" in names


def test_one_account_never_sees_another_s_events(client: TestClient) -> None:
    owner = auth_header(client, CREDENTIALS)
    client.post("/api/auth/login", json=CREDENTIALS)
    stranger = auth_header(client, OTHER)

    # There is no parameter for whose events to read, so the only reachable scope is your own.
    assert [event["event"] for event in events(client, stranger)] == ["auth.register"]
    assert len(events(client, owner)) >= 2


def test_a_failed_sign_in_for_an_unknown_address_is_served_to_nobody(
    client: TestClient, db: Session
) -> None:
    headers = auth_header(client, CREDENTIALS)
    client.post("/api/auth/login", json={"email": "ghost@askgrey.ai", "password": "x" * 14})

    assert not [event for event in events(client, headers) if "ghost" in str(event)]
    # It is in the log (`app.core.audit`), but no row claims it: attributing an attempt on an
    # address that does not exist would mean guessing whose event it was.
    assert db.execute(select(AuditEvent).where(AuditEvent.user_id.is_(None))).all() == []


def test_exports_and_agent_calls_are_filterable_apart(client: TestClient, db: Session) -> None:
    headers = auth_header(client, CREDENTIALS)
    user_id = db.execute(select(AuditEvent.user_id)).scalars().first()
    assert user_id is not None
    for event in ("export.downloaded", "document.sent_to_llm", "literature.document_read"):
        service.record_event(db, event=event, user_id=user_id, client_ip="203.0.113.7")

    assert [event["event"] for event in events(client, headers, "?kind=export")] == [
        "export.downloaded"
    ]
    assert [event["event"] for event in events(client, headers, "?kind=agent")] == [
        "document.sent_to_llm"
    ]
    human = [event["event"] for event in events(client, headers, "?kind=human")]
    assert "literature.document_read" in human
    assert "export.downloaded" not in human


def test_an_unknown_kind_is_rejected_rather_than_ignored(client: TestClient) -> None:
    headers = auth_header(client, CREDENTIALS)

    assert client.get("/api/audit/events?kind=everything", headers=headers).status_code == 422


def test_the_page_size_is_bounded(client: TestClient) -> None:
    headers = auth_header(client, CREDENTIALS)

    assert client.get("/api/audit/events?limit=0", headers=headers).status_code == 422
    assert client.get("/api/audit/events?limit=100000", headers=headers).status_code == 422


def test_the_feed_reports_the_configured_retention_window(client: TestClient) -> None:
    headers = auth_header(client, CREDENTIALS)

    assert feed(client, headers)["retention_days"] == get_settings().audit_retention_days


def test_the_newest_event_is_first(client: TestClient, db: Session) -> None:
    headers = auth_header(client, CREDENTIALS)
    user_id = db.execute(select(AuditEvent.user_id)).scalars().first()
    assert user_id is not None
    service.record_event(db, event="literature.workspace_deleted", user_id=user_id)

    assert events(client, headers)[0]["event"] == "literature.workspace_deleted"


def test_an_event_carries_provenance_and_not_content(client: TestClient, db: Session) -> None:
    headers = auth_header(client, CREDENTIALS)
    user_id = db.execute(select(AuditEvent.user_id)).scalars().first()
    assert user_id is not None
    service.record_event(
        db,
        event="document.sent_to_llm",
        user_id=user_id,
        client_ip="203.0.113.7",
        detail={"source": "trial.pdf", "bytes": 4096, "vendor": "anthropic"},
    )

    served = events(client, headers, "?kind=agent")[0]

    assert served["detail"] == {"source": "trial.pdf", "bytes": 4096, "vendor": "anthropic"}
    assert served["client_ip"] == "203.0.113.7"
    assert served["outcome"] == "success"


def test_a_database_failure_degrades_the_tab_and_not_the_request(
    client: TestClient, db: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    headers = auth_header(client, CREDENTIALS)

    def broken_commit() -> None:
        raise OperationalError("INSERT INTO audit_events", {}, Exception("disk full"))

    monkeypatch.setattr(db, "commit", broken_commit)

    # No exception: an audit row the database refused must not turn a working action into a 500.
    assert service.record_event(db, event="auth.login", user_id="u1") is None
    assert client.get("/api/literature/workspace", headers=headers).status_code == 200


def test_the_log_line_is_written_even_with_no_session(caplog: pytest.LogCaptureFixture) -> None:
    with caplog.at_level("INFO", logger="askgrey.audit"):
        audit_log.record("auth.login", actor="u1", client_ip="203.0.113.7")

    assert "auth.login" in caplog.text


def test_a_document_name_never_reaches_the_log_or_the_feed(
    client: TestClient, db: Session, caplog: pytest.LogCaptureFixture
) -> None:
    """The name of an uploaded paper is the finding itself, so only a fingerprint is kept."""
    headers = auth_header(client, CREDENTIALS)
    user_id = db.execute(select(AuditEvent.user_id)).scalars().first()
    assert user_id is not None

    with caplog.at_level("INFO", logger="askgrey.audit"):
        audit_log.record(
            "document.sent_to_llm",
            actor=user_id,
            detail={"source": "trial_ziprasidone_qt.pdf", "source_kind": "upload", "bytes": 4096},
            db=db,
            user_id=user_id,
        )

    assert "ziprasidone" not in caplog.text
    detail = events(client, headers, "?kind=agent")[0]["detail"]
    assert isinstance(detail, dict)
    assert "source" not in detail
    assert detail["source_kind"] == "upload"
    assert detail["bytes"] == 4096
    assert detail["source_fingerprint"] == audit_log.fingerprint("trial_ziprasidone_qt.pdf")


def test_the_same_document_fingerprints_the_same_way_across_events() -> None:
    """Correlation is the point of keeping anything at all: two events must line up."""
    assert audit_log.fingerprint("trial.pdf") == audit_log.fingerprint("trial.pdf")
    assert audit_log.fingerprint("trial.pdf") != audit_log.fingerprint("trial-2.pdf")
    assert "trial" not in audit_log.fingerprint("trial.pdf")


def test_a_provenance_field_that_names_nothing_is_kept_as_it_is(
    caplog: pytest.LogCaptureFixture,
) -> None:
    with caplog.at_level("INFO", logger="askgrey.audit"):
        audit_log.record(
            "document.sent_to_llm",
            actor="u1",
            detail={"source_host": "pubmed.ncbi.nlm.nih.gov", "vendor": "anthropic"},
        )

    assert "pubmed.ncbi.nlm.nih.gov" in caplog.text


def test_events_past_the_retention_window_are_deleted(
    client: TestClient, db: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    headers = auth_header(client, CREDENTIALS)
    row = db.execute(select(AuditEvent)).scalar_one()
    user_id = row.user_id
    assert user_id is not None
    row.created_at = datetime.now(timezone.utc) - timedelta(days=400)
    db.commit()

    # The next write prunes; there is no scheduler in this deployment.
    service.record_event(db, event="auth.login", user_id=user_id)

    assert [event["event"] for event in events(client, headers)] == ["auth.login"]


def test_an_account_keeps_at_most_its_ceiling_of_events(
    client: TestClient, db: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    headers = auth_header(client, CREDENTIALS)
    user_id = db.execute(select(AuditEvent.user_id)).scalars().first()
    assert user_id is not None
    settings = get_settings()
    monkeypatch.setattr(settings, "audit_max_events_per_user", 3)
    monkeypatch.setattr(service, "get_settings", lambda: settings)

    for index in range(5):
        service.record_event(db, event=f"auth.login.{index}", user_id=user_id)

    assert len(events(client, headers)) == 3


def test_classification_covers_the_three_workflows() -> None:
    assert service.classify("document.sent_to_llm") == "agent"
    assert service.classify("export.downloaded") == "export"
    assert service.classify("grants.budget_exported") == "export"
    assert service.classify("auth.login") == "human"
    assert service.classify("literature.document_read") == "human"
