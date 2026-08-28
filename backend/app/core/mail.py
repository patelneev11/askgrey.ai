"""Outbound email, which the app has exactly one use for: handing someone a seat.

Everything else the product says to a person, it says in the browser. An invitation is the one
message that must reach an address the app has never seen, because the person it names has no
account yet and therefore nowhere to be told anything.

Unconfigured, this module sends nothing and says so, which is not a degraded mode: the
invitation still exists and its token is still returned to the inviter to pass on however they
like. Set `INVITE_EMAIL_SENDER` to a verified SES identity and the same token also arrives by
mail. Delivery is therefore an addition to the invitation, never a precondition for it — a
throttled or rejected send must not destroy a seat that was already offered.

Two rules the callers depend on:

- A failure to send is raised, not swallowed, so the caller can record that the mail did not go
  out and tell the inviter to pass the link on themselves. It is never fatal to the invitation.
- What SES is told about a failure is not what the API tells the world. `MailSendError` carries
  a provider-shaped reason for the log; the response says only that the mail did not go, because
  "address rejected" and "address suppressed" are facts about a person the caller may not have.
"""

from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache
from typing import Any

from botocore.exceptions import ClientError

from app.core.config import Settings

# Mail is not on the critical path of a page render, but the request that triggers it is: an
# invitation POST waits for this, so a silent endpoint has to fail long before the browser does.
CONNECT_TIMEOUT_SECONDS = 3
READ_TIMEOUT_SECONDS = 5
MAX_ATTEMPTS = 2


class MailSendError(Exception):
    """SES would not take the message. The caller keeps whatever the message was about."""


@dataclass(frozen=True)
class Message:
    """One message to one recipient. No bcc, no bulk: this sends invitations."""

    to: str
    subject: str
    text: str
    html: str = ""


class SesMailer:
    """Amazon SES via boto3, one recipient at a time."""

    def __init__(
        self,
        sender: str,
        *,
        region: str = "",
        reply_to: str = "",
        configuration_set: str = "",
        client: Any | None = None,
    ) -> None:
        self._sender = sender
        self._region = region
        self._reply_to = reply_to
        self._configuration_set = configuration_set
        self._client = client

    @property
    def client(self) -> Any:
        if self._client is None:
            self._client = _build_client(self._region)
        return self._client

    def send(self, message: Message) -> str:
        """Hand the message to SES, returning its id for the log. Raises `MailSendError`."""
        body: dict[str, Any] = {"Text": {"Data": message.text, "Charset": "UTF-8"}}
        if message.html:
            body["Html"] = {"Data": message.html, "Charset": "UTF-8"}
        request: dict[str, Any] = {
            "Source": self._sender,
            "Destination": {"ToAddresses": [message.to]},
            "Message": {
                "Subject": {"Data": message.subject, "Charset": "UTF-8"},
                "Body": body,
            },
        }
        if self._reply_to:
            request["ReplyToAddresses"] = [self._reply_to]
        if self._configuration_set:
            request["ConfigurationSetName"] = self._configuration_set
        try:
            response = self.client.send_email(**request)
        except Exception as exc:
            raise MailSendError(_reason(exc)) from exc
        message_id = response.get("MessageId", "")
        return str(message_id)


def _reason(exc: Exception) -> str:
    """A reason for the log: the provider's code, never the recipient's address."""
    if isinstance(exc, ClientError):
        code = str(exc.response.get("Error", {}).get("Code", "")) or "unknown"
        return f"the mail service refused the message ({code})"
    return f"the mail service could not be reached: {type(exc).__name__}"


def _build_client(region: str) -> Any:
    """Imported here, not at module scope, so a deployment that sends no mail builds no client."""
    import boto3
    from botocore.config import Config

    config = Config(
        connect_timeout=CONNECT_TIMEOUT_SECONDS,
        read_timeout=READ_TIMEOUT_SECONDS,
        retries={"max_attempts": MAX_ATTEMPTS, "mode": "standard"},
    )
    return boto3.client("ses", config=config, **({"region_name": region} if region else {}))


@lru_cache(maxsize=4)
def _mailer_for(sender: str, region: str, reply_to: str, configuration_set: str) -> SesMailer:
    """One mailer (and one boto3 client, which is not cheap to build) per configuration."""
    return SesMailer(sender, region=region, reply_to=reply_to, configuration_set=configuration_set)


def mailer_for(settings: Settings) -> SesMailer | None:
    """The configured mailer, or None when the app sends no mail and says so instead."""
    sender = settings.invite_email_sender.strip()
    if not sender:
        return None
    return _mailer_for(
        sender,
        settings.aws_region.strip(),
        settings.invite_email_reply_to.strip(),
        settings.ses_configuration_set.strip(),
    )


__all__ = ["MailSendError", "Message", "SesMailer", "mailer_for"]
