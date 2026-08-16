from __future__ import annotations

from datetime import date
from enum import Enum

from pydantic import BaseModel, Field

from ..models import UnavailableProperty
from ..smiles import MAX_SMILES_LENGTH
from .query import MAX_KEYWORD_LENGTH

MAX_PAGE_SIZE = 50
DEFAULT_PAGE_SIZE = 25
# The upstream API paginates by offset; walking past this is a bulk-download pattern, which
# neither the researcher's workflow nor USPTO's terms of use call for.
MAX_OFFSET = 500

SOURCE_LABEL = "USPTO Open Data Portal — Patent Search (patent applications)"

# Carried in the payload rather than left to the frontend, so no client can render these hits
# without the sentence that says what they are not.
PATENT_CAVEAT = (
    "Keyword-based prior-art results from a text search of USPTO patent application titles, "
    "abstracts and bibliographic metadata. This is not a structural similarity search, not a "
    "novelty assessment and not a freedom-to-operate analysis; a registered patent attorney "
    "must review the landscape before any filing, licensing or FTO decision."
)
# An empty result set is the case most likely to be misread, so it gets its own sentence.
NO_MATCH_STATEMENT = (
    "No keyword matches found for this query. This is not evidence of novelty: the search "
    "covers only the keywords listed in query_used against one USPTO dataset, and prior art "
    "may exist under different wording, in unpublished applications, in pre-2001 US patents, "
    "or in non-US patent offices."
)
# Why a SMILES string still ends up as a text query.
STRUCTURE_TEXT_NOTE = (
    "The upstream API indexes text, not chemical structures, so the structure itself was never "
    "searched. The query below was derived from the structure's molecular formula (and any "
    "scaffold keywords supplied); a patent claiming this compound under a different formula "
    "expression, a Markush genus or a trade name will not match."
)

UNAVAILABLE_ANALYSES: tuple[UnavailableProperty, ...] = (
    UnavailableProperty(
        key="structural_similarity_search",
        label="Structural similarity / substructure prior-art search",
        reason=(
            "The integrated source is a keyword index over patent text and bibliographic "
            "metadata; it cannot be queried by structure, so no similarity or substructure "
            "match is performed and none is reported."
        ),
        requires=(
            "A structure-searchable patent chemistry database (e.g. CAS SciFinder, Reaxys, "
            "SureChEMBL or PubChem's patent annotations) plus a licence for it."
        ),
    ),
    UnavailableProperty(
        key="novelty_score",
        label="Novelty score",
        reason=(
            "Novelty is a legal determination over the whole body of prior art in any language, "
            "made claim by claim. A number computed from keyword hit counts would look like an "
            "answer while measuring only how a query was worded, so none is computed."
        ),
        requires=(
            "Claim-level analysis of the full prior-art corpus by a registered patent "
            "practitioner; it is not a computable quantity."
        ),
    ),
    UnavailableProperty(
        key="freedom_to_operate",
        label="Freedom-to-operate opinion",
        reason=(
            "FTO depends on in-force claims, their scope after prosecution, jurisdiction, "
            "assignments and licences — none of which this keyword search examines. Absence of "
            "hits here says nothing about whether a compound can be made, used or sold."
        ),
        requires=(
            "A formal FTO opinion from patent counsel, based on a full claim-scope and "
            "jurisdictional review."
        ),
    ),
)


class QueryDerivation(str, Enum):
    """Where the text that was actually searched came from."""

    KEYWORDS = "keywords"
    STRUCTURE_FORMULA = "structure_formula"
    STRUCTURE_FORMULA_AND_KEYWORDS = "structure_formula_and_keywords"


class PatentSort(str, Enum):
    """Result ordering. `RELEVANCE` leaves the upstream ranking untouched."""

    RELEVANCE = "relevance"
    FILING_DATE_DESC = "filing_date_desc"
    FILING_DATE_ASC = "filing_date_asc"
    GRANT_DATE_DESC = "grant_date_desc"


class StructureBasis(BaseModel):
    """RDKit's view of a submitted SMILES string, and why it became a text query."""

    input_smiles: str
    canonical_smiles: str
    molecular_formula: str
    inchikey: str = ""
    searched_by_structure: bool = False
    note: str = STRUCTURE_TEXT_NOTE


class DerivedQuery(BaseModel):
    """
    Exactly what was sent upstream, and how it was built from the caller's input.

    `query_used` is the query string as the upstream API received it, so a researcher can
    reproduce the search by hand and see which words the hit list is a function of.
    """

    query_used: str
    derived_from: QueryDerivation
    terms: list[str] = Field(default_factory=list)
    derivation: str
    field_scope: str = (
        "Free-form text search across the indexed USPTO application fields (title, abstract "
        "and bibliographic metadata). Full claim text is not searched."
    )
    structure: StructureBasis | None = None


class PatentSearch(BaseModel):
    """
    One patent landscape query: a structure, keywords, or both, plus paging and filters.

    Bounded here so the route rejects oversized input before the service runs, and re-validated
    inside the service, which is the only thing that decides what reaches the upstream API.
    """

    smiles: str = Field(default="", max_length=MAX_SMILES_LENGTH)
    keywords: str = Field(default="", max_length=MAX_KEYWORD_LENGTH)
    sort: PatentSort = PatentSort.RELEVANCE
    page_size: int = Field(default=DEFAULT_PAGE_SIZE, ge=1, le=MAX_PAGE_SIZE)
    offset: int = Field(default=0, ge=0, le=MAX_OFFSET)
    filed_from: date | None = None
    filed_to: date | None = None

    def is_empty(self) -> bool:
        return not (self.smiles.strip() or self.keywords.strip())


class PatentHit(BaseModel):
    """
    One upstream record, normalized. Every field is either verbatim from the API or empty.

    Nothing is inferred or filled in: a missing title stays empty rather than becoming a
    generated label, and `url` is the deterministic USPTO permalink for the record's own
    application number.
    """

    application_number: str = ""
    patent_number: str = ""
    publication_number: str = ""
    title: str = ""
    abstract: str = ""
    filing_date: str = ""
    grant_date: str = ""
    publication_date: str = ""
    status: str = ""
    applicants: list[str] = Field(default_factory=list)
    inventors: list[str] = Field(default_factory=list)
    cpc_classifications: list[str] = Field(default_factory=list)
    url: str = ""


class PatentLandscape(BaseModel):
    """
    One page of keyword prior-art results, with the honesty fields the UI must render.

    `source_available=False` is a normal outcome, not an error: the upstream API needs a key,
    and a degraded upstream should leave the tab usable rather than failing the request. In
    that case `hits` is empty and `source_status` says why — it must never be read as
    "nothing found".
    """

    source: str = SOURCE_LABEL
    source_available: bool
    source_status: str = ""
    query: DerivedQuery
    sort: PatentSort = PatentSort.RELEVANCE
    page_size: int = DEFAULT_PAGE_SIZE
    offset: int = 0
    returned: int = 0
    # Upstream's count of the whole result set, or None when it did not report one.
    total_found: int | None = None
    hits: list[PatentHit] = Field(default_factory=list)
    # Non-empty only when the search ran and matched nothing.
    no_match_statement: str = ""
    caveat: str = PATENT_CAVEAT
    unavailable: list[UnavailableProperty] = Field(
        default_factory=lambda: list(UNAVAILABLE_ANALYSES)
    )

    @property
    def has_more(self) -> bool:
        if self.total_found is None:
            return False
        return self.offset + self.returned < self.total_found
