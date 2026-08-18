from __future__ import annotations

from collections.abc import Mapping, Sequence
from datetime import date
from pathlib import Path

from .config import GuidelineDataset, Requirement, load_reference_library
from .errors import GuidelineInputError
from .models import (
    GuidelineCheckReport,
    Jurisdiction,
    JurisdictionFindings,
    ReferenceJurisdiction,
    ReferenceLibrary,
    ReferenceRequirement,
    RequirementFinding,
    RequirementStatus,
    SignalEvidence,
    SnapshotFreshness,
    assess_freshness,
    oldest,
)
from .text import PhraseMatch, find_phrase, normalise, word_count

# Below this many words a section cannot carry a requirement's content in any meaningful way, and a
# short section that happens to contain a signal phrase (a heading, a placeholder sentence, a
# to-do list) would otherwise read as `addressed`. 40 words is roughly two sentences of prose,
# well under the length of the thinnest real Module 3 subsection, so the cost of the bound is that
# stub sections come back `indeterminate` instead of confidently wrong.
MIN_WORDS_TO_JUDGE = 40

MAX_SECTION_ID_LENGTH = 40


class GuidelineChecker:
    """
    Compares one draft CTD section against the shipped requirement snapshots.

    Wholly deterministic and offline: the same section text always produces the same report, no
    model is consulted, and nothing is fetched at runtime. Matching is literal phrase matching over
    normalised text, and every status carries the signal and offset that produced it so a reviewer
    can check the engine's reasoning instead of trusting it.
    """

    def __init__(
        self,
        datasets: Mapping[Jurisdiction, GuidelineDataset],
        *,
        min_words_to_judge: int = MIN_WORDS_TO_JUDGE,
    ) -> None:
        self.datasets = dict(datasets)
        self.min_words_to_judge = min_words_to_judge

    @classmethod
    def from_reference_files(cls, directory: Path | None = None) -> GuidelineChecker:
        return cls(load_reference_library(directory))

    def reference(self, today: date | None = None) -> ReferenceLibrary:
        """What is being checked and how old the data is, for display before any draft exists."""
        asked = today or date.today()
        entries = [
            ReferenceJurisdiction(
                jurisdiction=jurisdiction,
                version=dataset.version,
                retrieved=dataset.retrieved,
                freshness=_freshness(dataset, asked),
                notes=dataset.notes,
                requirements=[
                    ReferenceRequirement(
                        id=requirement.id,
                        title=requirement.title,
                        ctd_sections=requirement.ctd_sections,
                        citation=requirement.citation,
                        expectation=requirement.expectation,
                    )
                    for requirement in dataset.requirements
                ],
            )
            for jurisdiction, dataset in self.datasets.items()
        ]
        return ReferenceLibrary(
            jurisdictions=entries,
            snapshot=oldest([entry.freshness for entry in entries]),
        )

    def check(
        self,
        section_id: str,
        text: str,
        jurisdictions: Sequence[Jurisdiction],
        today: date | None = None,
    ) -> GuidelineCheckReport:
        if not section_id.strip():
            raise GuidelineInputError("a CTD section id is required")
        if len(section_id) > MAX_SECTION_ID_LENGTH:
            raise GuidelineInputError("that section id is too long to be a CTD section id")
        if not jurisdictions:
            raise GuidelineInputError("at least one jurisdiction is required")
        unknown = [
            jurisdiction.value
            for jurisdiction in jurisdictions
            if jurisdiction not in self.datasets
        ]
        if unknown:
            raise GuidelineInputError("no reference data for: " + ", ".join(sorted(unknown)))

        normalised = normalise(text)
        words = word_count(normalised)
        asked = today or date.today()
        findings = [
            self._for_jurisdiction(jurisdiction, section_id, normalised, words, asked)
            for jurisdiction in dict.fromkeys(jurisdictions)
        ]
        return GuidelineCheckReport(
            section_id=section_id.strip(),
            word_count=words,
            min_words_to_judge=self.min_words_to_judge,
            jurisdictions=findings,
            snapshot=oldest([entry.freshness for entry in findings]),
        )

    def _for_jurisdiction(
        self,
        jurisdiction: Jurisdiction,
        section_id: str,
        normalised: str,
        words: int,
        today: date,
    ) -> JurisdictionFindings:
        dataset = self.datasets[jurisdiction]
        scoped = dataset.in_scope(section_id)
        in_scope_ids = {requirement.id for requirement, _ in scoped}
        return JurisdictionFindings(
            jurisdiction=jurisdiction,
            version=dataset.version,
            retrieved=dataset.retrieved,
            freshness=_freshness(dataset, today),
            findings=[
                self._evaluate(requirement, scope, normalised, words)
                for requirement, scope in scoped
            ],
            out_of_scope_requirement_ids=[
                requirement.id
                for requirement in dataset.requirements
                if requirement.id not in in_scope_ids
            ],
        )

    def _evaluate(
        self,
        requirement: Requirement,
        scope: str,
        normalised: str,
        words: int,
    ) -> RequirementFinding:
        def finding(
            status: RequirementStatus,
            explanation: str,
            *,
            matched: SignalEvidence | None = None,
            suppressed_by: PhraseMatch | None = None,
        ) -> RequirementFinding:
            return RequirementFinding(
                requirement_id=requirement.id,
                title=requirement.title,
                ctd_sections=requirement.ctd_sections,
                matched_scope=scope,
                citation=requirement.citation,
                expectation=requirement.expectation,
                status=status,
                explanation=explanation,
                matched_signal=matched,
                suppressed_by=suppressed_by,
            )

        if words < self.min_words_to_judge:
            return finding(
                RequirementStatus.INDETERMINATE,
                f"Section holds {words} words, under the {self.min_words_to_judge}-word floor for "
                "judging it; too short to tell whether this is addressed.",
            )

        matched = _first_matching_group(requirement, normalised)
        negative = _first_negative(requirement, normalised)
        if negative is not None:
            detail = (
                "a signal did match, but the phrase overrides it"
                if matched is not None
                else "so the section cannot be judged as written"
            )
            return finding(
                RequirementStatus.INDETERMINATE,
                f"Section contains '{negative.phrase}', which marks the content as not yet "
                f"written or not applicable; {detail}.",
                matched=matched,
                suppressed_by=negative,
            )
        if matched is None:
            return finding(
                RequirementStatus.MISSING,
                "None of the phrase groups for this requirement appear in the section. The content "
                "may still be present in wording the engine does not look for.",
            )
        phrases = ", ".join(f"'{match.phrase}'" for match in matched.phrases)
        return finding(
            RequirementStatus.ADDRESSED,
            f"Signal group {matched.group_index} matched on {phrases}. That the phrases are "
            "present is not a judgement that the requirement is met.",
            matched=matched,
        )


def _freshness(dataset: GuidelineDataset, today: date) -> SnapshotFreshness:
    return assess_freshness(dataset.version, dataset.retrieved, today)


def _first_matching_group(requirement: Requirement, normalised: str) -> SignalEvidence | None:
    """First group whose every phrase is present, in declared order, so the result is stable."""
    for index, group in enumerate(requirement.signals):
        matches = [find_phrase(normalised, phrase) for phrase in group.all_of]
        if all(match is not None for match in matches):
            return SignalEvidence(
                group_index=index,
                phrases=[match for match in matches if match is not None],
            )
    return None


def _first_negative(requirement: Requirement, normalised: str) -> PhraseMatch | None:
    for phrase in requirement.negative_signals:
        match = find_phrase(normalised, phrase)
        if match is not None:
            return match
    return None
