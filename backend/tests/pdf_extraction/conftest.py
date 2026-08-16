from __future__ import annotations

from pathlib import Path

import pytest

from app.services.pdf_extraction import (
    DataPointExtractor,
    ExtractionField,
    ParsedDocument,
    RawDataPoint,
    parse_pdf,
)

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures" / "pdf_extraction"

REAL_PAPERS = (
    "trial_ziprasidone",
    "trial_mipomersen",
    "trial_linaclotide",
    "trial_silymarin",
)


def fixture_bytes(name: str) -> bytes:
    return (FIXTURES / f"{name}.pdf").read_bytes()


def parse_fixture(name: str) -> ParsedDocument:
    return parse_pdf(fixture_bytes(name), filename=f"{name}.pdf")


class StubExtractor:
    """Returns canned data points, standing in for Claude in every test."""

    name = "stub"

    def __init__(self, *points: RawDataPoint, error: Exception | None = None) -> None:
        self.points = list(points)
        self.error = error
        self.calls: list[tuple[ParsedDocument, list[ExtractionField]]] = []

    async def extract(
        self, document: ParsedDocument, fields: list[ExtractionField]
    ) -> list[RawDataPoint]:
        self.calls.append((document, fields))
        if self.error is not None:
            raise self.error
        return self.points


def as_extractor(stub: StubExtractor) -> DataPointExtractor:
    return stub


@pytest.fixture(scope="session")
def ziprasidone() -> ParsedDocument:
    return parse_fixture("trial_ziprasidone")
