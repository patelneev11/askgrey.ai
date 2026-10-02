"""When an account's refusals stop being worth a classifier call."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy.orm import Session

from app.core.config import Settings, get_settings
from app.models.audit import AuditEvent
from app.services.chat.scope_abuse import OUT_OF_SCOPE_EVENT, classifier_available


def refusals(db: Session, user_id: str, count: int, *, age: timedelta = timedelta()) -> None:
    created = datetime.now(timezone.utc) - age
    for _ in range(count):
        db.add(
            AuditEvent(
                user_id=user_id,
                event=OUT_OF_SCOPE_EVENT,
                outcome="denied",
                kind="agent",
                created_at=created,
            )
        )
    db.commit()


@pytest.fixture
def cooldown_after_three(monkeypatch: pytest.MonkeyPatch) -> Settings:
    settings = get_settings().model_copy(
        update={"chat_scope_refusals_before_cooldown": 3, "chat_scope_cooldown_minutes": 60}
    )
    monkeypatch.setattr("app.services.chat.scope_abuse.get_settings", lambda: settings)
    return settings


def test_a_researcher_who_has_not_been_refused_gets_the_classifier(
    db: Session, cooldown_after_three: Settings
) -> None:
    assert classifier_available(db, "u1")


def test_repeated_refusals_withhold_the_classifier(
    db: Session, cooldown_after_three: Settings
) -> None:
    refusals(db, "u1", 2)
    assert classifier_available(db, "u1")

    refusals(db, "u1", 1)
    assert not classifier_available(db, "u1")


def test_the_window_expires_on_its_own(db: Session, cooldown_after_three: Settings) -> None:
    refusals(db, "u1", 5, age=timedelta(hours=2))

    assert classifier_available(db, "u1")


def test_one_account_cannot_withhold_another_account_s_classifier(
    db: Session, cooldown_after_three: Settings
) -> None:
    refusals(db, "u1", 5)

    assert not classifier_available(db, "u1")
    assert classifier_available(db, "u2")


def test_a_zero_threshold_turns_the_cooldown_off(
    db: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    settings = get_settings().model_copy(update={"chat_scope_refusals_before_cooldown": 0})
    monkeypatch.setattr("app.services.chat.scope_abuse.get_settings", lambda: settings)
    refusals(db, "u1", 50)

    assert classifier_available(db, "u1")
