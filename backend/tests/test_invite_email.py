"""Invitations that arrive by mail: what the message says, and what happens when it does not go.

The property worth protecting is that delivery is an addition to an invitation and never a
precondition for it. A mail service that throttles, suppresses an address or is not configured at
all must leave a usable seat behind, so every failure path here asserts that the token still
redeems.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

import pytest
from botocore.exceptions import ClientError
from fastapi.testclient import TestClient

from app.core.config import Settings
from app.core.mail import MailSendError, Message, SesMailer, mailer_for
from app.services.invite_mail import ACCEPT_PARAM, Invitation, accept_url, compose
from tests.test_workspaces_api import (
    COLLEAGUE,
    OWNER,
    accept,
    invite,
    make_workspace,
    register,
)

EXPIRES = datetime(2026, 9, 30, 12, 0, tzinfo=timezone.utc)


def an_invitation(**overrides: Any) -> Invitation:
    fields: dict[str, Any] = {
        "to": "bench@lab.org",
        "workspace_name": "Tox screen",
        "invited_by": "Dr Ada Lovelace",
        "role": "member",
        "token": "tok-abc123",
        "expires_at": EXPIRES,
    }
    fields.update(overrides)
    return Invitation(**fields)


class FakeSes:
    """A stand-in for the SES client, recording what it was asked to send."""

    def __init__(self, error: Exception | None = None) -> None:
        self.error = error
        self.sent: list[dict[str, Any]] = []

    def send_email(self, **request: Any) -> dict[str, str]:
        if self.error is not None:
            raise self.error
        self.sent.append(request)
        return {"MessageId": "ses-message-1"}


def throttled() -> ClientError:
    return ClientError(
        {"Error": {"Code": "Throttling", "Message": "Maximum sending rate exceeded"}}, "SendEmail"
    )


# --- what the message says -------------------------------------------------------------------


def test_the_link_carries_the_token_and_points_at_the_configured_host() -> None:
    url = accept_url("https://app.askgrey.ai/", "tok abc/123")
    # Configured host, one slash, and a token safe to put in a query string.
    assert url == "https://app.askgrey.ai/workspace?invite=tok%20abc%2F123"


def test_the_message_names_the_workspace_and_the_inviter_but_not_the_token_in_its_subject() -> None:
    message = compose(an_invitation(), app_name="askgrey.ai", base_url="https://app.askgrey.ai")

    assert "Tox screen" in message.subject
    assert "Dr Ada Lovelace" in message.subject
    # Subjects are shown in notifications, logged in transit and quoted in replies.
    assert "tok-abc123" not in message.subject
    assert message.to == "bench@lab.org"


def test_both_parts_carry_the_link_the_expiry_and_the_address_it_is_valid_for() -> None:
    message = compose(an_invitation(), app_name="askgrey.ai", base_url="https://app.askgrey.ai")
    url = accept_url("https://app.askgrey.ai", "tok-abc123")

    for part in (message.text, message.html):
        assert url in part
        assert "30 September 2026" in part
        assert "bench@lab.org" in part
    assert "member" in message.text


def test_a_name_with_newlines_in_it_stays_on_the_subject_line() -> None:
    """A subject is a header, and a header ends at a newline."""
    message = compose(
        an_invitation(workspace_name="Tox\r\nBcc: someone@else.org", invited_by="A\nB"),
        app_name="askgrey.ai",
        base_url="https://app.askgrey.ai",
    )

    assert "\n" not in message.subject
    assert "\r" not in message.subject
    assert "Tox Bcc: someone@else.org" in message.subject


def test_another_persons_workspace_name_cannot_become_markup() -> None:
    """Workspace names and display names are other people's input, in an HTML mail part."""
    message = compose(
        an_invitation(
            workspace_name='<script>alert("x")</script>',
            invited_by="<b>bold</b>",
        ),
        app_name="askgrey.ai",
        base_url="https://app.askgrey.ai",
    )

    assert "<script>" not in message.html
    assert "&lt;script&gt;" in message.html
    assert "<b>bold</b>" not in message.html
    # The text part is not markup, so it is left as written.
    assert '<script>alert("x")</script>' in message.text


# --- the mailer ------------------------------------------------------------------------------


def test_no_sender_configured_means_no_mailer_and_no_client_is_built() -> None:
    assert mailer_for(Settings(invite_email_sender="")) is None


def test_a_configured_sender_yields_one_reusable_mailer() -> None:
    settings = Settings(invite_email_sender="invites@askgrey.ai", aws_region="us-east-2")
    first = mailer_for(settings)
    assert first is not None
    # Building a boto3 client per request is the cost this cache exists to avoid.
    assert mailer_for(settings) is first


def test_send_passes_the_sender_recipient_and_both_body_parts() -> None:
    fake = FakeSes()
    mailer = SesMailer(
        "invites@askgrey.ai",
        reply_to="lab@askgrey.ai",
        configuration_set="askgrey-invites",
        client=fake,
    )

    message_id = mailer.send(
        Message(to="bench@lab.org", subject="Seat", text="plain", html="<p>rich</p>")
    )

    assert message_id == "ses-message-1"
    (request,) = fake.sent
    assert request["Source"] == "invites@askgrey.ai"
    assert request["Destination"] == {"ToAddresses": ["bench@lab.org"]}
    assert request["Message"]["Body"]["Text"]["Data"] == "plain"
    assert request["Message"]["Body"]["Html"]["Data"] == "<p>rich</p>"
    assert request["ReplyToAddresses"] == ["lab@askgrey.ai"]
    assert request["ConfigurationSetName"] == "askgrey-invites"


def test_a_text_only_message_sends_no_html_part() -> None:
    fake = FakeSes()
    SesMailer("invites@askgrey.ai", client=fake).send(
        Message(to="bench@lab.org", subject="Seat", text="plain")
    )

    (request,) = fake.sent
    assert "Html" not in request["Message"]["Body"]


def test_a_refused_message_raises_with_the_providers_code_and_not_the_address() -> None:
    mailer = SesMailer("invites@askgrey.ai", client=FakeSes(error=throttled()))

    with pytest.raises(MailSendError) as raised:
        mailer.send(Message(to="bench@lab.org", subject="Seat", text="plain"))

    assert "Throttling" in str(raised.value)
    assert "bench@lab.org" not in str(raised.value)


def test_an_unreachable_endpoint_raises_the_same_way() -> None:
    mailer = SesMailer("invites@askgrey.ai", client=FakeSes(error=OSError("no route to host")))

    with pytest.raises(MailSendError) as raised:
        mailer.send(Message(to="bench@lab.org", subject="Seat", text="plain"))

    assert "OSError" in str(raised.value)


# --- the invitation endpoint -----------------------------------------------------------------


def token_from(text: str) -> str:
    """The token as a recipient's mail client would hand it back: out of the link."""
    marker = f"?{ACCEPT_PARAM}="
    return text.split(marker, 1)[1].split()[0]


def test_with_no_mailer_the_invitation_stands_and_says_it_was_not_emailed(
    client: TestClient,
) -> None:
    owner = register(client, OWNER)
    workspace = make_workspace(client, owner)

    created = invite(client, owner, workspace["id"], email=COLLEAGUE["email"])

    assert created["delivered"] is False
    assert created["workspace_name"] == workspace["name"]
    colleague = register(client, COLLEAGUE)
    assert accept(client, colleague, created["token"]).status_code == 200


def test_a_configured_mailer_sends_one_message_whose_link_redeems_the_seat(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    fake = FakeSes()
    mailer = SesMailer("invites@askgrey.ai", client=fake)
    monkeypatch.setattr("app.api.workspaces.mailer_for", lambda _settings: mailer)

    owner = register(client, OWNER)
    workspace = make_workspace(client, owner, name="Tox screen")
    created = invite(client, owner, workspace["id"], email=COLLEAGUE["email"], role="viewer")

    assert created["delivered"] is True
    (request,) = fake.sent
    assert request["Destination"] == {"ToAddresses": [COLLEAGUE["email"]]}
    assert "Tox screen" in request["Message"]["Subject"]["Data"]

    # The link, and nothing else, is what the recipient has: it must redeem the seat.
    mailed = token_from(request["Message"]["Body"]["Text"]["Data"])
    colleague = register(client, COLLEAGUE)
    joined = accept(client, colleague, mailed)
    assert joined.status_code == 200, joined.text
    assert joined.json()["role"] == "viewer"


def test_a_refused_send_still_leaves_a_usable_invitation(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Throttling is the common case, and it must not cost the inviter a seat."""
    mailer = SesMailer("invites@askgrey.ai", client=FakeSes(error=throttled()))
    monkeypatch.setattr("app.api.workspaces.mailer_for", lambda _settings: mailer)

    owner = register(client, OWNER)
    workspace = make_workspace(client, owner)
    created = invite(client, owner, workspace["id"], email=COLLEAGUE["email"])

    assert created["delivered"] is False
    colleague = register(client, COLLEAGUE)
    assert accept(client, colleague, created["token"]).status_code == 200


def test_the_trail_records_whether_a_seat_offer_was_emailed_but_never_to_whom(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    mailer = SesMailer("invites@askgrey.ai", client=FakeSes())
    monkeypatch.setattr("app.api.workspaces.mailer_for", lambda _settings: mailer)

    owner = register(client, OWNER)
    workspace = make_workspace(client, owner)
    created = invite(client, owner, workspace["id"], email=COLLEAGUE["email"])

    events = client.get("/api/audit/events", headers=owner).json()["events"]
    invited = next(event for event in events if event["event"] == "workspace.invited")
    assert invited["detail"]["emailed"] is True

    body = client.get("/api/audit/events", headers=owner).text
    assert COLLEAGUE["email"] not in body
    assert created["token"] not in body
