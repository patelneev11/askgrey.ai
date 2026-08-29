"""What an invitation says when it arrives by mail.

The token in this message is the seat: whoever holds it can redeem the invitation from any
account whose address it was issued to. That constrains the wording more than it looks.

- The link is built from `PUBLIC_APP_URL`, not from the request, so a forwarded `Host` header
  cannot rewrite where an invitation points.
- The workspace name and the inviter's name come from other people's input, so both are escaped
  into the HTML part and neither is allowed to become markup.
- The subject names the workspace but never the token, because subjects are what mail clients
  show in notifications, log in transit and quote in replies. Both names are collapsed onto one
  line first: a subject is a header, and a header ends at a newline.
- The message states who invited them and when the link stops working, since a recipient who
  cannot tell an invitation from a phishing attempt is right to ignore it.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime
from html import escape
from urllib.parse import quote

from app.core.mail import Message

# Where the app's workspace page redeems a token it finds in the query string.
ACCEPT_PATH = "/workspace"
ACCEPT_PARAM = "invite"


@dataclass(frozen=True)
class Invitation:
    """Everything the message needs, with no database row reaching the template."""

    to: str
    workspace_name: str
    invited_by: str
    role: str
    token: str
    expires_at: datetime


def _one_line(value: str) -> str:
    """A name as a subject can hold it: no newlines, whatever the account called itself."""
    return re.sub(r"\s+", " ", value).strip()


def accept_url(base_url: str, token: str) -> str:
    """The link that redeems this invitation, or the bare path if no base URL is configured."""
    return f"{base_url.strip().rstrip('/')}{ACCEPT_PATH}?{ACCEPT_PARAM}={quote(token, safe='')}"


def compose(invitation: Invitation, *, app_name: str, base_url: str) -> Message:
    """The invitation as one message: plain text, and the same words as HTML."""
    url = accept_url(base_url, invitation.token)
    day = invitation.expires_at.strftime("%d %B %Y")
    subject = (
        f"{_one_line(invitation.invited_by)} invited you to "
        f"{_one_line(invitation.workspace_name)} on {app_name}"
    )
    text = (
        f"{invitation.invited_by} has given you a seat in the {invitation.workspace_name} "
        f"workspace on {app_name}, as a {invitation.role}.\n\n"
        f"Open this link to accept it:\n{url}\n\n"
        f"The link works once, only for {invitation.to}, and stops working on {day}.\n\n"
        f"If you were not expecting this, ignore it — nothing is shared with you until you "
        f"accept, and an unused invitation expires on its own.\n"
    )
    safe_workspace = escape(invitation.workspace_name)
    safe_inviter = escape(invitation.invited_by)
    safe_url = escape(url, quote=True)
    html = (
        f"<p>{safe_inviter} has given you a seat in the <strong>{safe_workspace}</strong> "
        f"workspace on {escape(app_name)}, as a {escape(invitation.role)}.</p>"
        f'<p><a href="{safe_url}">Accept the invitation</a></p>'
        f"<p>The link works once, only for {escape(invitation.to)}, and stops working on "
        f"{day}.</p>"
        f"<p>If you were not expecting this, ignore it — nothing is shared with you until you "
        f"accept, and an unused invitation expires on its own.</p>"
    )
    return Message(to=invitation.to, subject=subject, text=text, html=html)


__all__ = ["ACCEPT_PARAM", "ACCEPT_PATH", "Invitation", "accept_url", "compose"]
