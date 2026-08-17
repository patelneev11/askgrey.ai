from __future__ import annotations

from decimal import Decimal

from app.services.regulatory.preclinical import (
    DiscrepancyKind,
    Measurement,
    SectionKey,
    Severity,
    StudyTable,
    audit_narrative,
    extract_numbers,
)
from tests.regulatory.conftest import quantity, section

CLEAN_RESULTS = (
    "Alanine aminotransferase was increased 2.4 x in 7/20 animals at 150 mg/kg/day, and body "
    "weight gain was reduced by 12.5 % in the same group. Hepatocellular hypertrophy was seen "
    "in 4/20 animals at 75 mg/kg/day. Each group comprised 10 animals per sex and dosing "
    "continued for 28 days."
)


def audit_text(study: StudyTable, text: str, key: SectionKey = SectionKey.RESULTS):
    return audit_narrative([section(key, text)], study)


def test_a_narrative_using_only_source_numbers_is_clean(study: StudyTable) -> None:
    flags, summary = audit_text(study, CLEAN_RESULTS)

    assert flags == []
    assert summary.numbers_checked == summary.numbers_matched > 8
    assert summary.numbers_flagged == 0
    assert "no language model" in summary.method.lower()


def test_a_wrong_noael_is_flagged_as_a_contradiction(study: StudyTable) -> None:
    flags, _ = audit_text(
        study,
        "Under the conditions of this study the NOAEL was 50 mg/kg/day in both sexes.",
        SectionKey.INTERPRETATION,
    )

    assert len(flags) == 1
    flag = flags[0]
    assert flag.kind is DiscrepancyKind.CONTRADICTED_VALUE
    assert flag.severity is Severity.CRITICAL
    assert flag.source_label == "NOAEL"
    assert flag.source_value == "25 mg/kg/day"
    assert flag.narrative_value == "50 mg/kg/day"
    assert "NOAEL was 50" in flag.context
    assert flag.section is SectionKey.INTERPRETATION


def test_a_contradiction_is_caught_through_a_declared_alias(study: StudyTable) -> None:
    flags, _ = audit_text(
        study, "The no-observed-adverse-effect level was 150 mg/kg/day.", SectionKey.INTERPRETATION
    )

    assert [flag.kind for flag in flags] == [DiscrepancyKind.CONTRADICTED_VALUE]
    assert flags[0].source_label == "NOAEL"


def test_the_measurement_name_matches_regardless_of_case(study: StudyTable) -> None:
    flags, _ = audit_text(study, "The noael was 60 mg/kg/day.")

    assert [flag.kind for flag in flags] == [DiscrepancyKind.CONTRADICTED_VALUE]


def test_a_number_absent_from_the_table_is_flagged_as_unsupported(study: StudyTable) -> None:
    flags, summary = audit_text(
        study, "Alanine aminotransferase was increased 3.9 x at the high dose."
    )

    assert [flag.kind for flag in flags] == [DiscrepancyKind.UNSUPPORTED_NUMBER]
    assert flags[0].severity is Severity.WARNING
    assert flags[0].narrative_value == "3.9 x"
    assert flags[0].source_value == ""
    assert summary.numbers_flagged == 1


def test_a_fabricated_incidence_is_flagged(study: StudyTable) -> None:
    flags, _ = audit_text(study, "Hepatocellular hypertrophy was observed in 9/20 animals.")

    assert [(flag.kind, flag.narrative_value) for flag in flags] == [
        (DiscrepancyKind.UNSUPPORTED_NUMBER, "9")
    ]


def test_a_labelled_value_in_the_wrong_unit_is_critical(study: StudyTable) -> None:
    flags, _ = audit_text(study, "Cmax at the NOAEL was 1.8 mg/kg/day.")

    assert [flag.kind for flag in flags] == [DiscrepancyKind.UNIT_MISMATCH]
    assert flags[0].severity is Severity.CRITICAL
    assert flags[0].source_value == "1.8 µg/mL"


def test_an_unlabelled_value_in_the_wrong_unit_is_a_warning(study: StudyTable) -> None:
    flags, _ = audit_text(study, "Body weight gain was reduced by 12.5 mg/kg/day.")

    assert [flag.kind for flag in flags] == [DiscrepancyKind.UNIT_MISMATCH]
    assert flags[0].severity is Severity.WARNING
    assert flags[0].source_value == "12.5 %"


def test_rounding_a_source_value_is_reported_but_not_treated_as_a_mismatch(
    study: StudyTable,
) -> None:
    flags, _ = audit_text(study, "Body weight gain was reduced by approximately 13 % .")

    assert [flag.kind for flag in flags] == [DiscrepancyKind.ROUNDED_VALUE]
    assert flags[0].severity is Severity.INFO
    assert flags[0].source_value == "12.5 %"


def test_a_number_only_present_in_a_free_text_field_still_counts_as_sourced(
    study: StudyTable,
) -> None:
    flags, _ = audit_text(study, "Animals were dosed daily for 28 days.")

    assert flags == []


def test_section_and_table_references_are_not_read_as_claims(study: StudyTable) -> None:
    flags, summary = audit_text(
        study,
        "Individual animal data are presented in Table 7 and summarised under 4.2.3.2; see "
        "also Figure 12.",
    )

    assert flags == []
    assert summary.numbers_checked == 0


def test_putting_a_number_on_a_value_the_table_records_as_text_is_a_contradiction() -> None:
    table = StudyTable(
        study_id="TOX-1",
        duration="28 days",
        measurements=[Measurement(name="NOAEL", text_value="not established")],
    )

    flags, _ = audit_narrative(
        [section(SectionKey.INTERPRETATION, "The NOAEL was 75 mg/kg/day.")], table
    )

    assert [flag.kind for flag in flags] == [DiscrepancyKind.CONTRADICTED_VALUE]
    assert flags[0].source_value == "not established"


def test_thousand_separators_and_trailing_zeros_compare_by_value() -> None:
    table = StudyTable(
        study_id="TOX-2",
        measurements=[
            Measurement(name="AUC", quantity=quantity("1200", "ng*h/mL")),
            Measurement(name="Cmax", quantity=quantity("12.40", "ng/mL")),
        ],
    )

    flags, summary = audit_narrative(
        [section(SectionKey.RESULTS, "AUC was 1,200 ng*h/mL and Cmax was 12.4 ng/mL.")], table
    )

    assert flags == []
    assert summary.numbers_matched == 2


def test_every_flagged_number_is_locatable_in_the_section_text(study: StudyTable) -> None:
    text = "The NOAEL was 50 mg/kg/day and ALT rose 3.9 x."
    flags, _ = audit_text(study, text)

    assert len(flags) == 2
    for flag in flags:
        assert text[flag.start_char : flag.end_char] == flag.narrative_value.split(" ")[0]


def test_flags_are_ordered_and_the_audit_is_deterministic(study: StudyTable) -> None:
    sections = [
        section(SectionKey.RESULTS, "ALT rose 3.9 x, then 4.7 x."),
        section(SectionKey.INTERPRETATION, "The NOAEL was 50 mg/kg/day."),
    ]

    first, first_summary = audit_narrative(sections, study)
    second, second_summary = audit_narrative(sections, study)

    assert [(flag.section, flag.start_char) for flag in first] == [
        (SectionKey.INTERPRETATION, 14),
        (SectionKey.RESULTS, 9),
        (SectionKey.RESULTS, 21),
    ]
    assert first == second
    assert first_summary == second_summary


def test_numbers_are_extracted_with_the_units_the_table_uses() -> None:
    tokens = extract_numbers("doses of 25 mg/kg/day and 7 kg", {"mg/kg/day"})

    assert [(token.value, token.unit) for token in tokens] == [
        (Decimal("25"), "mg/kg/day"),
        (Decimal("7"), ""),
    ]


def test_a_hyphenated_range_is_read_as_two_positive_numbers() -> None:
    tokens = extract_numbers("10-30 mg/kg/day", {"mg/kg/day"})

    assert [token.value for token in tokens] == [Decimal("10"), Decimal("30")]
