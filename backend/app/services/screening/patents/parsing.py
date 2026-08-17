"""
Normalizing ODP search records into `PatentHit`.

The rule for this module is that it only ever *moves* values: every field is read from the
upstream record or left empty. Nothing is inferred, defaulted to a plausible value, or
reconstructed from another field, because a fabricated patent number or assignee in a prior-art
list is worse than a blank cell. The one derived value is `url`, a deterministic USPTO
permalink built from the record's own application number.
"""

from __future__ import annotations

from typing import Any

from .models import PatentHit

APPLICATION_URL = "https://data.uspto.gov/ui/patent/applications"


def parse_record(record: dict[str, Any]) -> PatentHit:
    """One `patentFileWrapperDataBag` entry as a `PatentHit`."""
    metadata = record.get("applicationMetaData")
    meta: dict[str, Any] = metadata if isinstance(metadata, dict) else {}
    application_number = _text(record.get("applicationNumberText"))
    return PatentHit(
        application_number=application_number,
        patent_number=_text(meta.get("patentNumber")),
        publication_number=_text(meta.get("earliestPublicationNumber")),
        title=_text(meta.get("inventionTitle")),
        filing_date=_text(meta.get("filingDate")),
        grant_date=_text(meta.get("grantDate")),
        publication_date=_text(meta.get("earliestPublicationDate")),
        status=_text(meta.get("applicationStatusDescriptionText")),
        applicants=_names(meta.get("applicantBag"), ("applicantNameText", "organizationNameText")),
        inventors=_names(meta.get("inventorBag"), ("inventorNameText",)),
        cpc_classifications=_classifications(meta.get("cpcClassificationBag")),
        url=f"{APPLICATION_URL}/{application_number}" if application_number else "",
    )


def parse_records(payload: dict[str, Any]) -> list[PatentHit]:
    """Every parseable record in a search payload, in upstream order."""
    bag = payload.get("patentFileWrapperDataBag")
    if not isinstance(bag, list):
        return []
    return [parse_record(record) for record in bag if isinstance(record, dict)]


def total_found(payload: dict[str, Any]) -> int | None:
    """
    Upstream's count of the whole result set, or None when it did not report one.

    `count` is the size of the whole match set, not of the page: a `limit=2` request over seven
    matches returns two records and `count: 7`. `totalNumFound` is read as a fallback because
    other ODP endpoints report the total under that name.

    None rather than 0: "the API did not say" and "the API said none" are different claims,
    and only one of them belongs in a prior-art report.
    """
    value = payload.get("count")
    if value is None:
        value = payload.get("totalNumFound")
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, str) and value.isdigit():
        return int(value)
    return None


def _text(value: object) -> str:
    """A string field, trimmed. Anything non-scalar becomes empty rather than a repr."""
    if isinstance(value, str):
        return value.strip()
    if isinstance(value, int) and not isinstance(value, bool):
        return str(value)
    return ""


def _names(value: object, keys: tuple[str, ...]) -> list[str]:
    """Party names from an ODP `*Bag`, which holds either objects or bare strings."""
    if not isinstance(value, list):
        return []
    names: list[str] = []
    for entry in value:
        if isinstance(entry, str):
            name = entry.strip()
        elif isinstance(entry, dict):
            name = next((_text(entry.get(key)) for key in keys if _text(entry.get(key))), "")
            if not name:
                name = _joined_person_name(entry)
        else:
            continue
        if name and name not in names:
            names.append(name)
    return names


def _joined_person_name(entry: dict[str, Any]) -> str:
    """`firstName`/`lastName` joined, for records that carry no pre-formatted name text."""
    parts = [_text(entry.get("firstName")), _text(entry.get("lastName"))]
    return " ".join(part for part in parts if part)


def _classifications(value: object) -> list[str]:
    if not isinstance(value, list):
        return []
    symbols: list[str] = []
    for entry in value:
        if isinstance(entry, str):
            symbol = entry.strip()
        elif isinstance(entry, dict):
            symbol = _text(entry.get("cpcSymbol")) or _text(entry.get("cpcClassificationSymbol"))
        else:
            continue
        # Upstream pads symbols to a fixed width (`A61K  31/616`); the padding is presentation,
        # not part of the symbol.
        symbol = " ".join(symbol.split())
        if symbol and symbol not in symbols:
            symbols.append(symbol)
    return symbols
