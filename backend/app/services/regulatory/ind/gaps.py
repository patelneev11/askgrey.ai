from __future__ import annotations

from .models import EvidenceKind, EvidenceRecord, Gap, GapKind
from .structure import Section


def evidence_for(section: Section, evidence: list[EvidenceRecord]) -> list[EvidenceRecord]:
    """
    The submitted records a section may be drafted from.

    A record tagged with a `section_id` is only offered to that section (and its descendants),
    so batch data the caller filed under 3.2.S.4.4 does not leak into a Module 4 section.
    """
    chosen = []
    for record in evidence:
        if record.kind not in section.requires:
            continue
        if record.section_id and not (
            section.id == record.section_id or section.id.startswith(f"{record.section_id}.")
        ):
            continue
        chosen.append(record)
    return chosen


def gaps_for(section: Section, chosen: list[EvidenceRecord]) -> list[Gap]:
    """
    Everything this section is missing, computed from the submitted data alone.

    Deliberately deterministic and independent of the drafter: a model asked what it lacked
    would answer from the text it just wrote. Missing means the caller sent no record of that
    kind, which is a fact about the request.
    """
    if not chosen:
        gaps = [
            Gap(
                kind=GapKind.NO_EVIDENCE_SUBMITTED,
                description=(
                    "No data of any kind this section is drafted from was submitted, so no text "
                    "was drafted. Required kinds: "
                    + ", ".join(kind.value for kind in section.requires)
                    + "."
                ),
            )
        ]
    else:
        present = {record.kind for record in chosen}
        gaps = [
            Gap(
                kind=GapKind.MISSING_EVIDENCE_KIND,
                description=(
                    f"No {kind.value.replace('_', ' ')} data was submitted for this section; "
                    "the draft says so rather than describing it."
                ),
                evidence_kind=kind,
            )
            for kind in section.requires
            if kind not in present
        ]
    gaps.extend(
        Gap(kind=GapKind.AUTHOR_MUST_SUPPLY, description=description)
        for description in section.author_supplied()
    )
    return gaps


def unused(evidence: list[EvidenceRecord], used: set[int]) -> list[str]:
    """
    Records no drafted section consumed.

    Reported because silently ignoring submitted manufacturing or study data is worse than
    saying which section it would need to be filed under.
    """
    return [
        f"{record.kind.value}: {record.label}"
        for index, record in enumerate(evidence)
        if index not in used
    ]


def kinds_present(evidence: list[EvidenceRecord]) -> set[EvidenceKind]:
    return {record.kind for record in evidence}
