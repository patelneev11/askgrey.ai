from __future__ import annotations

import json
from datetime import date
from pathlib import Path

from pydantic import BaseModel, Field, ValidationError, field_validator

from .errors import GuidelineConfigError
from .models import Citation, Jurisdiction
from .text import normalise

DEFAULT_REFERENCE_DIR = Path(__file__).parent / "reference"


def _clean_phrases(phrases: list[str]) -> list[str]:
    """Reject a phrase that normalises to nothing: it would match every section."""
    cleaned = []
    for phrase in phrases:
        if not normalise(phrase):
            raise ValueError(f"signal phrase '{phrase}' is empty once normalised")
        cleaned.append(phrase)
    return cleaned


class SignalGroup(BaseModel):
    """
    One way a requirement can be recognised: every phrase in `all_of` must be present.

    Groups are alternatives, so `[{all_of: [a, b]}, {all_of: [c]}]` reads "a and b, or else c".
    There is no `any_of` because a one-phrase group already expresses it, and keeping the shape
    flat keeps the recorded evidence readable.
    """

    all_of: list[str] = Field(min_length=1)

    _check_all_of = field_validator("all_of")(_clean_phrases)


class Requirement(BaseModel):
    """
    One expectation transcribed from an authority, plus the literal signals that recognise it.

    `ctd_sections` scopes the requirement: it is only evaluated against a section whose id shares a
    dotted prefix with one of them, in either direction — a `4.2.3` requirement is evaluated
    against `4.2.3.2` (a subsection of it) and against `4.2` (a section broad enough to contain
    it), but never against `3.2.S.4`.
    """

    id: str = Field(min_length=1, max_length=100)
    title: str = Field(min_length=1, max_length=300)
    ctd_sections: list[str] = Field(min_length=1)
    citation: Citation
    expectation: str = Field(min_length=1, max_length=2000)
    signals: list[SignalGroup] = Field(min_length=1)
    negative_signals: list[str] = Field(default_factory=list)

    _check_negative = field_validator("negative_signals")(_clean_phrases)

    @field_validator("ctd_sections")
    @classmethod
    def _check_sections(cls, sections: list[str]) -> list[str]:
        for section in sections:
            if not section.strip():
                raise ValueError("ctd_sections entries must be non-empty")
        return sections

    def scope_for(self, section_id: str) -> str | None:
        """The `ctd_sections` entry this section falls under, or None if out of scope."""
        wanted = _segments(section_id)
        if not wanted:
            return None
        for section in self.ctd_sections:
            if _shares_prefix(_segments(section), wanted):
                return section
        return None


class GuidelineDataset(BaseModel):
    """
    One jurisdiction's requirement snapshot as written in `reference/<jurisdiction>.json`.

    `version` and `retrieved` are mandatory and are stamped onto every report: a comparison whose
    vintage cannot be stated is worse than no comparison, because nobody can tell how stale it is.
    """

    jurisdiction: Jurisdiction
    version: str = Field(min_length=1, max_length=50)
    retrieved: date
    notes: str = ""
    requirements: list[Requirement] = Field(min_length=1)

    @field_validator("requirements")
    @classmethod
    def _check_unique_ids(cls, requirements: list[Requirement]) -> list[Requirement]:
        ids = [requirement.id for requirement in requirements]
        duplicates = sorted({name for name in ids if ids.count(name) > 1})
        if duplicates:
            raise ValueError("duplicate requirement ids: " + ", ".join(duplicates))
        return requirements

    def in_scope(self, section_id: str) -> list[tuple[Requirement, str]]:
        scoped = (
            (requirement, requirement.scope_for(section_id)) for requirement in self.requirements
        )
        return [(requirement, scope) for requirement, scope in scoped if scope is not None]


def _segments(section_id: str) -> list[str]:
    return [part for part in section_id.strip().upper().split(".") if part]


def _shares_prefix(left: list[str], right: list[str]) -> bool:
    depth = min(len(left), len(right))
    return depth > 0 and left[:depth] == right[:depth]


def load_guideline_dataset(path: Path) -> GuidelineDataset:
    """Load and validate one jurisdiction file. Nothing is fetched: the data is shipped."""
    try:
        payload = json.loads(path.read_text())
    except FileNotFoundError as exc:
        raise GuidelineConfigError(f"no guideline reference data at {path}") from exc
    except json.JSONDecodeError as exc:
        raise GuidelineConfigError(f"guideline reference data at {path} is not valid JSON") from exc

    try:
        return GuidelineDataset.model_validate(payload)
    except ValidationError as exc:
        raise GuidelineConfigError(
            f"guideline reference data at {path} is malformed: {exc}"
        ) from exc


def load_reference_library(directory: Path | None = None) -> dict[Jurisdiction, GuidelineDataset]:
    """Load one dataset per jurisdiction from `<directory>/<jurisdiction>.json`."""
    source = directory or DEFAULT_REFERENCE_DIR
    library: dict[Jurisdiction, GuidelineDataset] = {}
    for jurisdiction in Jurisdiction:
        dataset = load_guideline_dataset(source / f"{jurisdiction.value}.json")
        if dataset.jurisdiction is not jurisdiction:
            raise GuidelineConfigError(
                f"{jurisdiction.value}.json declares jurisdiction '{dataset.jurisdiction.value}'"
            )
        library[jurisdiction] = dataset
    return library
