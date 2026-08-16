from __future__ import annotations

from typing import Any, TypeVar

from .models import STUDY_URL, Intervention, TrialPhase, TrialRecord, TrialStatus

E = TypeVar("E", TrialPhase, TrialStatus)


def _section(payload: dict[str, Any], *keys: str) -> dict[str, Any]:
    node: dict[str, Any] = payload
    for key in keys:
        value = node.get(key)
        if not isinstance(value, dict):
            return {}
        node = value
    return node


def _text(node: dict[str, Any], key: str) -> str:
    value = node.get(key)
    return value if isinstance(value, str) else ""


def _string_list(node: dict[str, Any], key: str) -> list[str]:
    values = node.get(key)
    if not isinstance(values, list):
        return []
    return [value for value in values if isinstance(value, str)]


def _dict_list(node: dict[str, Any], key: str) -> list[dict[str, Any]]:
    values = node.get(key)
    if not isinstance(values, list):
        return []
    return [value for value in values if isinstance(value, dict)]


def _date(node: dict[str, Any], key: str) -> str:
    """Date structs are `{"date": "2024-01", "type": "ESTIMATED"}`; precision varies by study."""
    struct = node.get(key)
    return _text(struct, "date") if isinstance(struct, dict) else ""


def parse_study(study: dict[str, Any]) -> TrialRecord:
    """Normalize one v2 study document, tolerating any module being absent."""
    protocol = _section(study, "protocolSection")
    identification = _section(protocol, "identificationModule")
    status_module = _section(protocol, "statusModule")
    sponsors = _section(protocol, "sponsorCollaboratorsModule")
    design = _section(protocol, "designModule")
    enrollment = _section(design, "enrollmentInfo")

    nct_id = _text(identification, "nctId")
    interventions = [
        Intervention(name=_text(item, "name"), type=_text(item, "type"))
        for item in _dict_list(_section(protocol, "armsInterventionsModule"), "interventions")
        if _text(item, "name")
    ]
    count = enrollment.get("count")

    return TrialRecord(
        nct_id=nct_id,
        title=_text(identification, "briefTitle"),
        official_title=_text(identification, "officialTitle"),
        status=_as_enum(TrialStatus, _text(status_module, "overallStatus")),
        phases=[
            phase
            for phase in (_as_enum(TrialPhase, value) for value in _string_list(design, "phases"))
            if phase is not None
        ],
        study_type=_text(design, "studyType"),
        sponsor=_text(_section(sponsors, "leadSponsor"), "name"),
        collaborators=[
            _text(item, "name")
            for item in _dict_list(sponsors, "collaborators")
            if _text(item, "name")
        ],
        conditions=_string_list(_section(protocol, "conditionsModule"), "conditions"),
        interventions=interventions,
        enrollment=count if isinstance(count, int) else None,
        enrollment_type=_text(enrollment, "type"),
        start_date=_date(status_module, "startDateStruct"),
        primary_completion_date=_date(status_module, "primaryCompletionDateStruct"),
        completion_date=_date(status_module, "completionDateStruct"),
        url=f"{STUDY_URL}/{nct_id}" if nct_id else "",
    )


def _as_enum(enum: type[E], value: str) -> E | None:
    """Unknown vocabulary from a newer API revision degrades to `None` rather than raising."""
    try:
        return enum(value)
    except ValueError:
        return None
