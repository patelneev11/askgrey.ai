from __future__ import annotations

import re
from dataclasses import dataclass
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation

from .models import (
    AuditSummary,
    Discrepancy,
    DiscrepancyKind,
    Measurement,
    NarrativeSection,
    Quantity,
    Severity,
    StudyTable,
)

# Bump when matching behaviour changes, so a stored report says which auditor produced it.
AUDITOR_VERSION = "preclinical-audit-1"

# How much narrative text is quoted around a flagged number.
CONTEXT_CHARS = 70
# How far after a measurement name a number may sit and still be read as that measurement's
# value. One clause, not one paragraph: past this the association is guesswork.
CLAIM_WINDOW_CHARS = 80

_NUMBER_RE = re.compile(r"[-+]?(?:\d{1,3}(?:,\d{3})+|\d+)(?:\.\d+)?(?:[eE][-+]?\d+)?")
# `4.2.3.2`, `2.6.6` — a section reference, not a measurement.
_DOTTED_REFERENCE_RE = re.compile(r"\b\d+(?:\.\d+){2,}\b")
_IGNORE_PREFIX_RE = re.compile(
    r"(?:table|tables|figure|figures|fig\.|section|sections|module|appendix|volume|part|no\.|#)"
    r"[\s:]*$",
    re.IGNORECASE,
)
_UNIT_RE = re.compile(r"[ \t]*(%|[A-Za-zµμ°][\w/·%°µμ.\-]*)")
# A sentence boundary, ignoring the period inside a decimal.
_SENTENCE_BREAK_RE = re.compile(r"(?<!\d)[.!?](?:\s|$)")
_WHITESPACE_RE = re.compile(r"\s+")


def normalize_unit(unit: str) -> str:
    """Fold the spellings of one unit together: `MG/KG/day `, `mg/kg/day.` -> `mg/kg/day`."""
    folded = unit.strip().strip(".,;:)(").lower().replace(" ", "")
    return folded.replace("μ", "µ")


def _to_decimal(text: str) -> Decimal | None:
    try:
        return Decimal(text.replace(",", ""))
    except InvalidOperation:
        return None


@dataclass(frozen=True)
class NumberToken:
    """A number as it appears in the narrative, with the unit written next to it."""

    text: str
    value: Decimal
    unit: str
    start: int
    end: int


@dataclass(frozen=True)
class SourceValue:
    """A number the study table actually contains, with where it came from."""

    label: str
    value: Decimal
    unit: str


def _skip(text: str, start: int, end: int, ignored: list[tuple[int, int]]) -> bool:
    if any(span_start <= start < span_end for span_start, span_end in ignored):
        return True
    if start > 0 and (text[start - 1].isalpha() or text[start - 1] == "."):
        # Part of an identifier (`R4521`) or a version-like token, not a reported value.
        return True
    return bool(_IGNORE_PREFIX_RE.search(text[max(0, start - 16) : start]))


def extract_numbers(text: str, known_units: set[str]) -> list[NumberToken]:
    """
    Pull every reported number out of `text`.

    Two things are deliberately excluded: dotted section references, and numbers introduced by
    a word like "Table" or "Figure". Everything else counts as a claim, because a number in a
    regulatory narrative that nobody can trace to the study record is exactly what this
    auditor exists to surface.

    A unit is only recognised if it is `%` or a unit the study table itself uses. Inventing a
    unit vocabulary here would let the auditor disagree with the source over spelling rather
    than over substance.
    """
    ignored = [(match.start(), match.end()) for match in _DOTTED_REFERENCE_RE.finditer(text)]
    tokens: list[NumberToken] = []
    for match in _NUMBER_RE.finditer(text):
        start, end = match.start(), match.end()
        raw = match.group(0)
        if raw[0] in "+-" and start > 0 and (text[start - 1].isdigit() or text[start - 1] == "."):
            # `10-30`: the hyphen is a range, not the sign of the second number.
            start += 1
            raw = raw[1:]
        if _skip(text, start, end, ignored):
            continue
        value = _to_decimal(raw)
        if value is None:
            continue
        unit = ""
        unit_match = _UNIT_RE.match(text, end)
        if unit_match:
            candidate = normalize_unit(unit_match.group(1))
            if candidate == "%" or candidate in known_units:
                unit = candidate
        tokens.append(NumberToken(text=raw, value=value, unit=unit, start=start, end=end))
    return tokens


def _string_fields(table: StudyTable) -> list[tuple[str, str]]:
    fields: list[tuple[str, str]] = [
        ("study id", table.study_id),
        ("title", table.title),
        ("test article", table.test_article),
        ("species", table.species),
        ("strain", table.strain),
        ("route", table.route),
        ("duration", table.duration),
    ]
    for group in table.groups:
        fields.append((f"group {group.label}", f"{group.label} {group.notes}"))
    for finding in table.findings:
        fields.append(
            (
                f"finding: {finding.endpoint}",
                f"{finding.endpoint} {finding.severity} {finding.notes}",
            )
        )
    for measurement in table.measurements:
        fields.append(
            (measurement.name, f"{measurement.text_value} {measurement.notes}"),
        )
    return [(label, value) for label, value in fields if value.strip()]


def _quantities(table: StudyTable) -> list[Quantity]:
    found: list[Quantity] = []
    for group in table.groups:
        if group.dose:
            found.append(group.dose)
    for finding in table.findings:
        if finding.quantity:
            found.append(finding.quantity)
    for measurement in table.measurements:
        if measurement.quantity:
            found.append(measurement.quantity)
    return found


def collect_units(table: StudyTable) -> set[str]:
    """The unit vocabulary the narrative is allowed to be read against: the table's own."""
    units = {normalize_unit(quantity.unit) for quantity in _quantities(table)}
    units.discard("")
    return units


def collect_source_values(table: StudyTable) -> list[SourceValue]:
    """
    Flatten the study table into every number it states.

    Free-text fields are mined too — a duration of "28 days" or a note saying "recovery over
    14 days" is source data, and treating it as absent would make the auditor cry wolf on
    numbers the narrative legitimately took from the record.
    """
    units = collect_units(table)
    values: list[SourceValue] = []

    for group in table.groups:
        if group.dose:
            values.append(
                SourceValue(
                    label=f"dose for {group.label}",
                    value=group.dose.value,
                    unit=normalize_unit(group.dose.unit),
                )
            )
        if group.animals_per_sex is not None:
            values.append(
                SourceValue(
                    label=f"animals per sex in {group.label}",
                    value=Decimal(group.animals_per_sex),
                    unit="",
                )
            )
    for finding in table.findings:
        if finding.quantity:
            values.append(
                SourceValue(
                    label=f"{finding.endpoint} ({finding.group_label})".strip(),
                    value=finding.quantity.value,
                    unit=normalize_unit(finding.quantity.unit),
                )
            )
        if finding.incidence:
            label = f"incidence of {finding.endpoint}"
            values.append(
                SourceValue(label=label, value=Decimal(finding.incidence.affected), unit="")
            )
            values.append(
                SourceValue(label=label, value=Decimal(finding.incidence.examined), unit="")
            )
    for measurement in table.measurements:
        if measurement.quantity:
            values.append(
                SourceValue(
                    label=measurement.name,
                    value=measurement.quantity.value,
                    unit=normalize_unit(measurement.quantity.unit),
                )
            )

    for label, text in _string_fields(table):
        for token in extract_numbers(text, units):
            values.append(SourceValue(label=label, value=token.value, unit=token.unit))
    return values


def _context(text: str, start: int, end: int) -> str:
    left = max(0, start - CONTEXT_CHARS)
    right = min(len(text), end + CONTEXT_CHARS)
    snippet = _WHITESPACE_RE.sub(" ", text[left:right]).strip()
    return f"{'…' if left else ''}{snippet}{'…' if right < len(text) else ''}"


def _decimals(value: Decimal) -> int:
    exponent = value.as_tuple().exponent
    return -exponent if isinstance(exponent, int) and exponent < 0 else 0


def _rounds_to(source: Decimal, claimed: Decimal) -> bool:
    """True when `claimed` is `source` rounded to the precision the narrative used."""
    places = _decimals(claimed)
    if _decimals(source) <= places:
        return False
    try:
        quantum = Decimal(1).scaleb(-places)
        return source.quantize(quantum, rounding=ROUND_HALF_UP) == claimed
    except InvalidOperation:
        return False


def _units_compatible(source_unit: str, claimed_unit: str) -> bool:
    """An unrecorded unit on either side cannot be judged, so it is not called a mismatch."""
    if not source_unit or not claimed_unit:
        return True
    return source_unit == claimed_unit


def _name_pattern(name: str) -> re.Pattern[str] | None:
    parts = [re.escape(part) for part in re.split(r"[\s\-]+", name.strip()) if part]
    if not parts:
        return None
    return re.compile(r"(?<![\w-])" + r"[\s\-]+".join(parts) + r"(?![\w-])", re.IGNORECASE)


def _claimed_number(text: str, tokens: list[NumberToken], after: int) -> NumberToken | None:
    """The number a measurement name is claiming, i.e. the next one in the same clause."""
    for token in tokens:
        if token.start < after:
            continue
        if token.start - after > CLAIM_WINDOW_CHARS:
            return None
        if _SENTENCE_BREAK_RE.search(text[after : token.start]):
            return None
        return token
    return None


def _measurement_flags(
    section: NarrativeSection,
    tokens: list[NumberToken],
    measurements: list[Measurement],
) -> tuple[list[Discrepancy], set[int]]:
    """
    Check named claims: "a NOAEL of 50 mg/kg/day" against the NOAEL the table records.

    This is the severe case. A number that merely fails to appear in the table might be a
    dose the narrative restated oddly; a number attached to the name of a value the table
    defines differently is the narrative asserting something the study did not find.
    """
    flags: list[Discrepancy] = []
    consumed: set[int] = set()
    # Longest name first, so "Cmax at the NOAEL" claims its number before "NOAEL" does, and a
    # name found inside an already-matched name is not read as a second claim.
    named = sorted(
        (
            (measurement, name)
            for measurement in measurements
            for name in [measurement.name, *measurement.aliases]
        ),
        key=lambda pair: len(pair[1]),
        reverse=True,
    )
    matched_names: list[tuple[int, int]] = []
    for measurement, name in named:
        pattern = _name_pattern(name)
        if pattern is not None:
            for occurrence in pattern.finditer(section.text):
                if any(
                    start < occurrence.end() and occurrence.start() < end
                    for start, end in matched_names
                ):
                    continue
                token = _claimed_number(section.text, tokens, occurrence.end())
                if token is None or token.start in consumed:
                    continue
                matched_names.append((occurrence.start(), occurrence.end()))
                quantity = measurement.quantity
                if quantity is None:
                    if not measurement.text_value.strip():
                        continue
                    consumed.add(token.start)
                    flags.append(
                        Discrepancy(
                            kind=DiscrepancyKind.CONTRADICTED_VALUE,
                            severity=Severity.CRITICAL,
                            section=section.key,
                            narrative_value=f"{token.text} {token.unit}".strip(),
                            source_value=measurement.text_value,
                            source_label=measurement.name,
                            context=_context(section.text, token.start, token.end),
                            start_char=token.start,
                            end_char=token.end,
                            explanation=(
                                f"The narrative gives {measurement.name} as a number, but the "
                                f"study table records it as {measurement.text_value!r}."
                            ),
                        )
                    )
                    continue
                source_unit = normalize_unit(quantity.unit)
                if token.value != quantity.value:
                    consumed.add(token.start)
                    flags.append(
                        Discrepancy(
                            kind=DiscrepancyKind.CONTRADICTED_VALUE,
                            severity=Severity.CRITICAL,
                            section=section.key,
                            narrative_value=f"{token.text} {token.unit}".strip(),
                            source_value=quantity.render(),
                            source_label=measurement.name,
                            context=_context(section.text, token.start, token.end),
                            start_char=token.start,
                            end_char=token.end,
                            explanation=(
                                f"The narrative states {measurement.name} as {token.text}, but "
                                f"the study table records {quantity.render()}."
                            ),
                        )
                    )
                elif not _units_compatible(source_unit, token.unit):
                    consumed.add(token.start)
                    flags.append(
                        Discrepancy(
                            kind=DiscrepancyKind.UNIT_MISMATCH,
                            severity=Severity.CRITICAL,
                            section=section.key,
                            narrative_value=f"{token.text} {token.unit}".strip(),
                            source_value=quantity.render(),
                            source_label=measurement.name,
                            context=_context(section.text, token.start, token.end),
                            start_char=token.start,
                            end_char=token.end,
                            explanation=(
                                f"{measurement.name} matches in magnitude but the narrative "
                                f"reports it in {token.unit}, not {quantity.unit}."
                            ),
                        )
                    )
    return flags, consumed


def _value_flag(
    section: NarrativeSection, token: NumberToken, sources: list[SourceValue]
) -> Discrepancy | None:
    same_value = [source for source in sources if source.value == token.value]
    if same_value:
        if any(_units_compatible(source.unit, token.unit) for source in same_value):
            return None
        expected = same_value[0]
        return Discrepancy(
            kind=DiscrepancyKind.UNIT_MISMATCH,
            severity=Severity.WARNING,
            section=section.key,
            narrative_value=f"{token.text} {token.unit}".strip(),
            source_value=f"{expected.value} {expected.unit}".strip(),
            source_label=expected.label,
            context=_context(section.text, token.start, token.end),
            start_char=token.start,
            end_char=token.end,
            explanation=(
                f"{token.text} appears in the study table as {expected.value} "
                f"{expected.unit}, not {token.unit}."
            ),
        )

    rounded = next(
        (
            source
            for source in sources
            if _units_compatible(source.unit, token.unit) and _rounds_to(source.value, token.value)
        ),
        None,
    )
    if rounded is not None:
        return Discrepancy(
            kind=DiscrepancyKind.ROUNDED_VALUE,
            severity=Severity.INFO,
            section=section.key,
            narrative_value=f"{token.text} {token.unit}".strip(),
            source_value=f"{rounded.value} {rounded.unit}".strip(),
            source_label=rounded.label,
            context=_context(section.text, token.start, token.end),
            start_char=token.start,
            end_char=token.end,
            explanation=(
                f"The narrative rounds {rounded.value} to {token.text}. Confirm the precision "
                "is the one the study report should carry."
            ),
        )

    return Discrepancy(
        kind=DiscrepancyKind.UNSUPPORTED_NUMBER,
        severity=Severity.WARNING,
        section=section.key,
        narrative_value=f"{token.text} {token.unit}".strip(),
        context=_context(section.text, token.start, token.end),
        start_char=token.start,
        end_char=token.end,
        explanation=f"{token.text} does not appear anywhere in the submitted study table.",
    )


def audit_narrative(
    sections: list[NarrativeSection], table: StudyTable
) -> tuple[list[Discrepancy], AuditSummary]:
    """
    Cross-check every number in the drafted narrative against the study table.

    Deterministic on purpose: no second model call reviews the first one's arithmetic, because
    a check that can hallucinate is not a check. The whole audit is string and decimal
    comparison, so the same narrative and table always produce the same flags.
    """
    units = collect_units(table)
    sources = collect_source_values(table)
    flags: list[Discrepancy] = []
    checked = 0
    matched = 0

    for section in sections:
        tokens = extract_numbers(section.text, units)
        checked += len(tokens)
        named_flags, consumed = _measurement_flags(section, tokens, table.measurements)
        flags.extend(named_flags)
        for token in tokens:
            if token.start in consumed:
                continue
            flag = _value_flag(section, token, sources)
            if flag is None:
                matched += 1
            else:
                flags.append(flag)

    flags.sort(key=lambda flag: (flag.section.value, flag.start_char))
    summary = AuditSummary(
        auditor_version=AUDITOR_VERSION,
        numbers_checked=checked,
        numbers_matched=matched,
        numbers_flagged=len(flags),
        source_values=len(sources),
    )
    return flags, summary
