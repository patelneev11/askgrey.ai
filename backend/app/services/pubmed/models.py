from __future__ import annotations

from datetime import date

from pydantic import BaseModel, Field


class PublicationTypeFilter(BaseModel):
    """A publication-type constraint, e.g. `Review` -> `Review[Publication Type]`."""

    values: list[str] = Field(default_factory=list)

    def to_entrez(self) -> str:
        if not self.values:
            return ""
        clauses = [f'"{value}"[Publication Type]' for value in self.values]
        return clauses[0] if len(clauses) == 1 else "(" + " OR ".join(clauses) + ")"


class DateRangeFilter(BaseModel):
    """A publication-date constraint. Either bound may be omitted."""

    start: date | None = None
    end: date | None = None

    def to_entrez(self) -> str:
        if self.start is None and self.end is None:
            return ""
        start = self.start.strftime("%Y/%m/%d") if self.start else "1800/01/01"
        end = self.end.strftime("%Y/%m/%d") if self.end else "3000/01/01"
        return f'("{start}"[Date - Publication] : "{end}"[Date - Publication])'


class TranslatedQuery(BaseModel):
    """The structured form of a natural-language question, plus how it was produced."""

    original: str
    term: str
    mesh_terms: list[str] = Field(default_factory=list)
    keywords: list[str] = Field(default_factory=list)
    publication_types: PublicationTypeFilter = Field(default_factory=PublicationTypeFilter)
    date_range: DateRangeFilter = Field(default_factory=DateRangeFilter)
    translator: str
    rationale: str = ""


class Author(BaseModel):
    last_name: str = ""
    fore_name: str = ""
    initials: str = ""
    collective_name: str = ""

    @property
    def display_name(self) -> str:
        if self.collective_name:
            return self.collective_name
        parts = [part for part in (self.fore_name or self.initials, self.last_name) if part]
        return " ".join(parts)


class Article(BaseModel):
    """A PubMed record normalized to the fields the rest of the product consumes."""

    pmid: str
    title: str = ""
    abstract: str = ""
    authors: list[Author] = Field(default_factory=list)
    journal: str = ""
    journal_abbreviation: str = ""
    publication_date: str = ""
    publication_types: list[str] = Field(default_factory=list)
    doi: str | None = None
    pmcid: str | None = None
    pubmed_url: str = ""
    doi_url: str | None = None
    full_text_url: str | None = None


class SearchResult(BaseModel):
    """The outcome of one natural-language search: what was asked, what was run, what came back."""

    query: TranslatedQuery
    total_results: int
    returned: int
    retstart: int
    articles: list[Article] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
