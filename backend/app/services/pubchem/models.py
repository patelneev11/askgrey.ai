from __future__ import annotations

from enum import Enum

from pydantic import BaseModel, Field

from app.services.records import RecordSource, SourceRecord

PUBCHEM_COMPOUND_URL = "https://pubchem.ncbi.nlm.nih.gov/compound"


class IdentifierKind(str, Enum):
    """How an input string was interpreted when resolving it to a CID."""

    SMILES = "smiles"
    NAME = "name"
    CID = "cid"


class MatchQuality(str, Enum):
    """
    Why a candidate is in the result set, in descending confidence.

    `EXACT` means PubChem's own name index matched the string as given; `SYNONYM` means the
    string matched one of the compound's registered synonyms; `WORD` means it only matched
    after PubChem's looser word search, which is where ambiguity comes from.
    """

    EXACT = "exact"
    SYNONYM = "synonym"
    WORD = "word"


class CompoundRecord(BaseModel):
    """A PubChem compound normalized to the fields the rest of the product consumes."""

    cid: int
    title: str = ""
    iupac_name: str = ""
    molecular_formula: str = ""
    molecular_weight: float | None = None
    canonical_smiles: str = ""
    isomeric_smiles: str = ""
    xlogp: float | None = None
    synonyms: list[str] = Field(default_factory=list)
    pubchem_url: str = ""

    @property
    def display_name(self) -> str:
        return self.title or self.iupac_name or (self.synonyms[0] if self.synonyms else "")

    def to_source_record(self) -> SourceRecord:
        """Project into the review-table row shape shared with the literature services."""
        weight = f"{self.molecular_weight:g}" if self.molecular_weight is not None else ""
        return SourceRecord(
            source=RecordSource.PUBCHEM,
            record_id=str(self.cid),
            title=self.display_name,
            subtitle=self.molecular_formula,
            url=self.pubchem_url or f"{PUBCHEM_COMPOUND_URL}/{self.cid}",
            fields={
                "Formula": self.molecular_formula,
                "MW": weight,
                "XLogP": "" if self.xlogp is None else f"{self.xlogp:g}",
                "IUPAC name": self.iupac_name,
                "SMILES": self.isomeric_smiles or self.canonical_smiles,
            },
        )


class CompoundCandidate(BaseModel):
    """One possible interpretation of an ambiguous identifier, with why it ranked where it did."""

    compound: CompoundRecord
    rank: int
    quality: MatchQuality
    score: float


class CompoundLookup(BaseModel):
    """
    The outcome of resolving one identifier.

    An unambiguous lookup has a single candidate and `match` set. An ambiguous name keeps every
    candidate, ranked, and still sets `match` to the best one — callers that want a single
    answer stay simple, and callers that want to disambiguate have the full list.
    """

    query: str
    resolved_as: IdentifierKind
    ambiguous: bool = False
    total_matches: int = 0
    match: CompoundRecord | None = None
    candidates: list[CompoundCandidate] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
