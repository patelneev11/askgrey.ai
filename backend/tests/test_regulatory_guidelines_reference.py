from __future__ import annotations

from datetime import date
from pathlib import Path

import pytest

from app.services.regulatory.guidelines import (
    DEFAULT_REFERENCE_DIR,
    GuidelineChecker,
    GuidelineConfigError,
    Jurisdiction,
    load_guideline_dataset,
    load_reference_library,
)

SOURCES_DOC = Path(__file__).resolve().parents[2] / "docs" / "regulatory-sources.md"


@pytest.fixture(scope="module")
def library() -> dict[Jurisdiction, object]:
    return dict(load_reference_library())


def test_every_jurisdiction_ships_a_dataset(library: dict[Jurisdiction, object]) -> None:
    assert set(library) == set(Jurisdiction)


@pytest.mark.parametrize("jurisdiction", list(Jurisdiction))
def test_shipped_dataset_is_versioned_dated_and_cited(jurisdiction: Jurisdiction) -> None:
    dataset = load_guideline_dataset(DEFAULT_REFERENCE_DIR / f"{jurisdiction.value}.json")

    assert dataset.jurisdiction is jurisdiction
    assert dataset.version.strip()
    assert isinstance(dataset.retrieved, date)
    assert dataset.retrieved <= date.today()
    assert dataset.requirements

    for requirement in dataset.requirements:
        assert requirement.id.startswith(f"{jurisdiction.value}.")
        assert requirement.title.strip()
        assert requirement.expectation.strip()
        assert requirement.ctd_sections
        assert requirement.signals
        citation = requirement.citation
        assert citation.document.strip()
        assert citation.document_date.strip()
        assert citation.url.startswith("https://")


@pytest.mark.parametrize("jurisdiction", list(Jurisdiction))
def test_every_cited_url_appears_in_the_sources_document(jurisdiction: Jurisdiction) -> None:
    """No requirement may cite a document that docs/regulatory-sources.md does not list."""
    sources = SOURCES_DOC.read_text()
    dataset = load_guideline_dataset(DEFAULT_REFERENCE_DIR / f"{jurisdiction.value}.json")

    for requirement in dataset.requirements:
        assert requirement.citation.url in sources, requirement.id


def test_reference_listing_reports_vintage_and_contents() -> None:
    listing = GuidelineChecker.from_reference_files().reference()

    assert {block.jurisdiction for block in listing.jurisdictions} == set(Jurisdiction)
    assert listing.requires_expert_review is True
    assert "dated snapshot" in listing.limitations
    for block in listing.jurisdictions:
        assert block.version.strip()
        assert block.requirements
        assert all(entry.citation.url.startswith("https://") for entry in block.requirements)


def test_a_missing_dataset_raises_a_config_error(tmp_path: Path) -> None:
    with pytest.raises(GuidelineConfigError):
        load_reference_library(tmp_path)


def test_a_malformed_dataset_raises_a_config_error(tmp_path: Path) -> None:
    (tmp_path / "fda.json").write_text("{ not json")

    with pytest.raises(GuidelineConfigError):
        load_guideline_dataset(tmp_path / "fda.json")


def test_a_dataset_declaring_the_wrong_jurisdiction_is_rejected(tmp_path: Path) -> None:
    for jurisdiction in Jurisdiction:
        source = (DEFAULT_REFERENCE_DIR / f"{jurisdiction.value}.json").read_text()
        (tmp_path / f"{jurisdiction.value}.json").write_text(source)
    swapped = (DEFAULT_REFERENCE_DIR / "ema.json").read_text()
    (tmp_path / "fda.json").write_text(swapped)

    with pytest.raises(GuidelineConfigError, match="declares jurisdiction"):
        load_reference_library(tmp_path)


def test_shipped_datasets_scope_to_the_modules_they_claim() -> None:
    """A Module 3 requirement must not be evaluated against a Module 4 section, and vice versa."""
    engine = GuidelineChecker.from_reference_files()
    quality = engine.check("3.2.S.4", "x " * 200, list(Jurisdiction))
    nonclinical = engine.check("4.2.3", "x " * 200, list(Jurisdiction))

    quality_ids = {
        finding.requirement_id for block in quality.jurisdictions for finding in block.findings
    }
    nonclinical_ids = {
        finding.requirement_id for block in nonclinical.jurisdictions for finding in block.findings
    }

    assert quality_ids
    assert nonclinical_ids
    # Quality-only and nonclinical-only requirements stay on their own side. A few requirements
    # (e.g. that toxicology batches are representative) legitimately apply to both modules.
    assert "fda.ds.limits_and_methods" not in nonclinical_ids
    assert "ema.quality.impd_module3_form" not in nonclinical_ids
    assert "fda.nonclinical.glp_statement" not in quality_ids
    assert "pmda.nonclinical.noael_margin" not in quality_ids
