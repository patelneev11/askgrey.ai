from __future__ import annotations

import html
import re
from datetime import date, datetime
from typing import Any

from .models import GrantProgram, GrantStatus

# The two providers publish dates in three different shapes, none of them ISO: search2 uses
# `MM/DD/YYYY`, fetchOpportunity uses `Mon DD, YYYY hh:mm:ss AM TZ`, SBIR.gov uses ISO or a
# `Month DD, YYYY` string depending on the field.
_DATE_FORMATS = ("%m/%d/%Y", "%Y-%m-%d", "%b %d, %Y", "%B %d, %Y", "%d-%b-%Y", "%m/%d/%y")
_MONEY = re.compile(r"[^\d.]")


def parse_date(value: object) -> date | None:
    """Best-effort date parse; unknown or placeholder values become `None`."""
    if isinstance(value, date) and not isinstance(value, datetime):
        return value
    if isinstance(value, datetime):
        return value.date()
    if not isinstance(value, str):
        return None
    text = value.strip()
    if not text or text.lower() in {"none", "n/a", "tbd", "null"}:
        return None
    # Drop the clock and timezone fetchOpportunity appends: "Apr 05, 2027 12:00:00 AM EDT".
    head = re.split(r"\s+\d{1,2}:\d{2}", text, maxsplit=1)[0].strip()
    for fmt in _DATE_FORMATS:
        try:
            return datetime.strptime(head, fmt).date()
        except ValueError:
            continue
    try:
        return datetime.fromisoformat(text.replace("Z", "+00:00")).date()
    except ValueError:
        return None


def parse_money(value: object) -> int | None:
    """`"450000"`, `"$450,000"` and `450000` all become `450000`; `"none"` becomes `None`."""
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        return int(value)
    if not isinstance(value, str):
        return None
    digits = _MONEY.sub("", value)
    if not digits:
        return None
    try:
        return int(float(digits))
    except ValueError:
        return None


def parse_program(value: object) -> GrantProgram | None:
    """SBIR.gov states the program explicitly; grants.gov only implies it in the title."""
    if not isinstance(value, str):
        return None
    text = value.strip().upper()
    if not text:
        return None
    if text in {"BOTH", "SBIR/STTR", "SBIR STTR"}:
        return GrantProgram.BOTH
    if text.startswith("STTR"):
        return GrantProgram.STTR
    if text.startswith("SBIR"):
        return GrantProgram.SBIR
    return GrantProgram.OTHER


def infer_program(title: str, description: str = "") -> GrantProgram | None:
    """Infer the set-aside program for providers that do not label it, e.g. grants.gov."""
    text = f"{title} {description}".upper()
    has_sbir = "SBIR" in text or "SMALL BUSINESS INNOVATION RESEARCH" in text
    has_sttr = "STTR" in text or "SMALL BUSINESS TECHNOLOGY TRANSFER" in text
    if has_sbir and has_sttr:
        return GrantProgram.BOTH
    if has_sttr:
        return GrantProgram.STTR
    if has_sbir:
        return GrantProgram.SBIR
    return None


def parse_status(value: object, close_date: date | None, today: date) -> GrantStatus | None:
    """
    Normalize a provider status string, falling back to the deadline.

    grants.gov reports `posted`/`forecasted`/`closed`/`archived`; SBIR.gov reports
    `open`/`closed`/`future`. Anything unrecognized is decided by the close date so the UI
    never shows a blank status for an obviously expired call.
    """
    text = value.strip().lower() if isinstance(value, str) else ""
    if text in {"posted", "open", "active"}:
        return GrantStatus.OPEN
    if text in {"forecasted", "future", "upcoming"}:
        return GrantStatus.FORECASTED
    if text in {"closed", "archived", "expired"}:
        return GrantStatus.CLOSED
    if close_date is None:
        return None
    return GrantStatus.OPEN if close_date >= today else GrantStatus.CLOSED


def clean_text(value: object, *, limit: int = 4000) -> str:
    """Collapse provider HTML/whitespace into plain text the matcher can read."""
    if not isinstance(value, str):
        return ""
    # Tags first, then entities: unescaping first would let `&lt;b&gt;` become a strippable tag.
    without_tags = re.sub(r"<[^>]+>", " ", value)
    collapsed = " ".join(html.unescape(without_tags).split())
    return collapsed[:limit]


def as_dict(value: Any) -> dict[str, Any]:
    """Providers occasionally send `null` where an object is documented."""
    return value if isinstance(value, dict) else {}
