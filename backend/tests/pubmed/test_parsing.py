from __future__ import annotations

import pytest

from app.services.pubmed.errors import EntrezResponseError
from app.services.pubmed.parsing import parse_article_set
from tests.pubmed.conftest import load_fixture


@pytest.fixture
def articles() -> list:
    return parse_article_set(load_fixture("efetch_semaglutide.xml"))


def test_normalizes_every_documented_field(articles: list) -> None:
    article = articles[0]

    assert article.pmid == "37733246"
    assert article.title.startswith("Semaglutide in Patients with Heart Failure")
    assert article.journal == "The New England journal of medicine"
    assert article.journal_abbreviation == "N Engl J Med"
    assert article.publication_date == "2023-12-14"
    assert article.doi == "10.1056/NEJMoa2306963"
    assert article.pmcid == "PMC10685891"
    assert article.pubmed_url == "https://pubmed.ncbi.nlm.nih.gov/37733246/"
    assert article.doi_url == "https://doi.org/10.1056/NEJMoa2306963"
    assert article.full_text_url == "https://www.ncbi.nlm.nih.gov/pmc/articles/PMC10685891/"
    assert "Randomized Controlled Trial" in article.publication_types


def test_joins_labeled_abstract_sections(articles: list) -> None:
    abstract = articles[0].abstract
    assert abstract.startswith("BACKGROUND: Obesity-related heart failure")
    assert "RESULTS: Semaglutide led to larger reductions" in abstract
    # Escaped entities survive as literal text rather than markup.
    assert "(P<0.001)" in abstract


def test_parses_personal_and_collective_authors(articles: list) -> None:
    names = [author.display_name for author in articles[0].authors]
    assert names == [
        "Mikhail N Kosiborod",
        "Steen Z Abildstrøm",
        "STEP-HFpEF Trial Committees and Investigators",
    ]


def test_falls_back_to_medline_date_and_elocation_doi(articles: list) -> None:
    article = articles[1]
    assert article.publication_date == "2021"
    assert article.doi == "10.1056/NEJMoa2032183"
    assert article.pmcid is None
    assert article.full_text_url is None


@pytest.mark.parametrize("xml", ["", "   ", "<PubmedArticleSet></PubmedArticleSet>"])
def test_empty_documents_yield_no_articles(xml: str) -> None:
    assert parse_article_set(xml) == []


def test_malformed_xml_raises() -> None:
    with pytest.raises(EntrezResponseError):
        parse_article_set("<PubmedArticleSet><PubmedArticle>")
