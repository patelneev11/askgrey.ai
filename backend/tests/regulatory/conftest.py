from __future__ import annotations

from decimal import Decimal

import pytest

from app.services.regulatory.preclinical import (
    DoseGroup,
    DraftedSection,
    Finding,
    GlpStatus,
    Incidence,
    Measurement,
    NarrativeDrafter,
    NarrativeSection,
    Quantity,
    SectionKey,
    Sex,
    StudyTable,
)
from app.services.regulatory.preclinical.models import SECTION_HEADINGS


def quantity(value: str, unit: str = "") -> Quantity:
    return Quantity(value=Decimal(value), unit=unit)


@pytest.fixture
def study() -> StudyTable:
    """
    A 28-day rat repeat-dose study. Every number a narrative may legitimately state is here.

    Values are invented for testing; they are not taken from any real study.
    """
    return StudyTable(
        study_id="TOX-2024-014",
        title="28-day repeat-dose oral toxicity study in rats",
        test_article="AG-4471",
        species="Rat",
        strain="Sprague-Dawley",
        route="Oral gavage",
        duration="28 days",
        glp_status=GlpStatus.COMPLIANT,
        groups=[
            DoseGroup(
                label="Control", dose=quantity("0", "mg/kg/day"), sex=Sex.BOTH, animals_per_sex=10
            ),
            DoseGroup(
                label="Low", dose=quantity("25", "mg/kg/day"), sex=Sex.BOTH, animals_per_sex=10
            ),
            DoseGroup(
                label="Mid", dose=quantity("75", "mg/kg/day"), sex=Sex.BOTH, animals_per_sex=10
            ),
            DoseGroup(
                label="High", dose=quantity("150", "mg/kg/day"), sex=Sex.BOTH, animals_per_sex=10
            ),
        ],
        findings=[
            Finding(
                group_label="High",
                endpoint="Alanine aminotransferase increase",
                quantity=quantity("2.4", "x"),
                incidence=Incidence(affected=7, examined=20),
                severity="moderate",
            ),
            Finding(
                group_label="High",
                endpoint="Body weight gain reduction",
                quantity=quantity("12.5", "%"),
                severity="mild",
            ),
            Finding(
                group_label="Mid",
                endpoint="Hepatocellular hypertrophy",
                incidence=Incidence(affected=4, examined=20),
                severity="minimal",
            ),
        ],
        measurements=[
            Measurement(
                name="NOAEL",
                aliases=["no observed adverse effect level"],
                quantity=quantity("25", "mg/kg/day"),
            ),
            Measurement(name="LOAEL", quantity=quantity("75", "mg/kg/day")),
            Measurement(name="Cmax at the NOAEL", quantity=quantity("1.8", "µg/mL")),
        ],
    )


def section(key: SectionKey, text: str) -> NarrativeSection:
    return NarrativeSection(key=key, heading=SECTION_HEADINGS[key], text=text)


class StubDrafter:
    """Returns canned narrative sections, standing in for Claude in every test."""

    name = "stub"

    def __init__(self, *sections: DraftedSection, error: Exception | None = None) -> None:
        self.sections = list(sections)
        self.error = error
        self.calls: list[StudyTable] = []

    async def draft(self, table: StudyTable) -> list[DraftedSection]:
        self.calls.append(table)
        if self.error is not None:
            raise self.error
        return self.sections


def as_drafter(stub: StubDrafter) -> NarrativeDrafter:
    return stub
