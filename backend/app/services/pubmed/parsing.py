from __future__ import annotations

from xml.etree import ElementTree

from .errors import EntrezResponseError
from .models import Article, Author

PUBMED_URL = "https://pubmed.ncbi.nlm.nih.gov/{pmid}/"
PMC_URL = "https://www.ncbi.nlm.nih.gov/pmc/articles/{pmcid}/"
DOI_URL = "https://doi.org/{doi}"

MONTHS = {
    "jan": "01",
    "feb": "02",
    "mar": "03",
    "apr": "04",
    "may": "05",
    "jun": "06",
    "jul": "07",
    "aug": "08",
    "sep": "09",
    "oct": "10",
    "nov": "11",
    "dec": "12",
}


def _text(element: ElementTree.Element | None) -> str:
    if element is None:
        return ""
    # itertext() keeps the content of inline markup such as <i> and <sup>.
    return " ".join("".join(element.itertext()).split())


def _parse_abstract(article: ElementTree.Element) -> str:
    sections: list[str] = []
    for node in article.findall(".//Abstract/AbstractText"):
        body = _text(node)
        if not body:
            continue
        label = node.get("Label")
        sections.append(f"{label}: {body}" if label else body)
    return "\n\n".join(sections)


def _parse_authors(article: ElementTree.Element) -> list[Author]:
    authors: list[Author] = []
    for node in article.findall(".//AuthorList/Author"):
        author = Author(
            last_name=_text(node.find("LastName")),
            fore_name=_text(node.find("ForeName")),
            initials=_text(node.find("Initials")),
            collective_name=_text(node.find("CollectiveName")),
        )
        if author.display_name:
            authors.append(author)
    return authors


def _parse_publication_date(article: ElementTree.Element) -> str:
    """
    Normalize a publication date to as much of `YYYY-MM-DD` as the record provides.

    PubMed dates are frequently partial (year only, or a `MedlineDate` string such as
    "2019 Nov-Dec"), so the precision of the input is preserved rather than invented.
    """
    node = article.find(".//Journal/JournalIssue/PubDate")
    if node is None:
        return ""
    year = _text(node.find("Year"))
    if not year:
        medline = _text(node.find("MedlineDate"))
        return medline.split()[0] if medline else ""
    raw_month = _text(node.find("Month"))
    month = MONTHS.get(raw_month[:3].lower(), raw_month if raw_month.isdigit() else "")
    if not month:
        return year
    day = _text(node.find("Day"))
    parts = [year, month.zfill(2)]
    if day:
        parts.append(day.zfill(2))
    return "-".join(parts)


def _parse_identifiers(entry: ElementTree.Element) -> tuple[str | None, str | None]:
    doi: str | None = None
    pmcid: str | None = None
    # Anchored rather than descendant: every <Reference> carries its own ArticleIdList, so
    # a wildcard search picks up the PMC id of a cited paper.
    for node in entry.findall("PubmedData/ArticleIdList/ArticleId"):
        id_type = node.get("IdType")
        value = _text(node)
        if not value:
            continue
        if id_type == "doi":
            doi = value
        elif id_type == "pmc":
            pmcid = value
    if doi is None:
        doi = _text(entry.find("MedlineCitation/Article/ELocationID[@EIdType='doi']")) or None
    return doi, pmcid


def parse_article_set(xml: str) -> list[Article]:
    """Parse an EFetch `PubmedArticleSet` document into normalized `Article` records."""
    if not xml.strip():
        return []
    try:
        root = ElementTree.fromstring(xml)
    except ElementTree.ParseError as exc:
        raise EntrezResponseError(f"efetch returned malformed XML: {exc}") from exc

    articles: list[Article] = []
    for entry in root.findall("PubmedArticle"):
        pmid = _text(entry.find(".//MedlineCitation/PMID"))
        if not pmid:
            continue
        article_node = entry.find(".//MedlineCitation/Article")
        if article_node is None:
            continue
        doi, pmcid = _parse_identifiers(entry)
        articles.append(
            Article(
                pmid=pmid,
                title=_text(article_node.find("ArticleTitle")),
                abstract=_parse_abstract(article_node),
                authors=_parse_authors(article_node),
                journal=_text(article_node.find(".//Journal/Title")),
                journal_abbreviation=_text(article_node.find(".//Journal/ISOAbbreviation")),
                publication_date=_parse_publication_date(article_node),
                publication_types=[
                    _text(node)
                    for node in article_node.findall(".//PublicationTypeList/PublicationType")
                    if _text(node)
                ],
                doi=doi,
                pmcid=pmcid,
                pubmed_url=PUBMED_URL.format(pmid=pmid),
                doi_url=DOI_URL.format(doi=doi) if doi else None,
                full_text_url=PMC_URL.format(pmcid=pmcid) if pmcid else None,
            )
        )
    return articles
