from __future__ import annotations

from app.core.config import Settings, get_settings

from .client import EntrezClient
from .errors import EntrezResponseError
from .models import Article, SearchResult
from .parsing import parse_article_set
from .rate_limit import RateLimiter
from .translation import (
    ClaudeQueryTranslator,
    FallbackQueryTranslator,
    QueryTranslator,
    RuleBasedQueryTranslator,
)

MAX_PAGE_SIZE = 100


class PubMedService:
    """
    The module's entry point: natural language in, normalized PubMed records out.

    Each search is `translate -> esearch -> efetch -> normalize`. `esummary` is exposed
    separately for callers that only need lightweight metadata for known PMIDs.
    """

    def __init__(self, *, client: EntrezClient, translator: QueryTranslator) -> None:
        self.client = client
        self.translator = translator

    @classmethod
    def from_settings(cls, settings: Settings | None = None) -> PubMedService:
        settings = settings or get_settings()
        client = EntrezClient(
            api_key=settings.ncbi_api_key,
            tool=settings.ncbi_tool_name,
            email=settings.ncbi_contact_email,
            timeout=settings.ncbi_timeout_seconds,
            rate_limiter=RateLimiter(settings.entrez_rate_limit),
        )
        rule_based = RuleBasedQueryTranslator()
        translator: QueryTranslator = rule_based
        if settings.llm_translation_enabled:
            translator = FallbackQueryTranslator(
                ClaudeQueryTranslator(
                    api_key=settings.anthropic_api_key,
                    model=settings.llm_model,
                    base_url=settings.anthropic_base_url,
                    anthropic_version=settings.anthropic_version,
                    max_tokens=settings.llm_max_tokens,
                    timeout=settings.llm_timeout_seconds,
                ),
                rule_based,
            )
        return cls(client=client, translator=translator)

    async def aclose(self) -> None:
        await self.client.aclose()

    async def search(
        self,
        query: str,
        *,
        limit: int = 20,
        offset: int = 0,
        sort: str = "relevance",
    ) -> SearchResult:
        translated = await self.translator.translate(query)
        retmax = max(1, min(limit, MAX_PAGE_SIZE))
        retstart = max(0, offset)

        payload = await self.client.esearch(
            translated.term, retmax=retmax, retstart=retstart, sort=sort
        )
        try:
            total = int(payload.get("count", 0))
        except (TypeError, ValueError) as exc:
            raise EntrezResponseError("esearch returned a non-numeric count") from exc
        pmids = [str(pmid) for pmid in payload.get("idlist", []) if str(pmid).strip()]

        warnings: list[str] = []
        errors = payload.get("errorlist")
        if isinstance(errors, dict):
            for field in ("phrasesnotfound", "fieldsnotfound"):
                warnings.extend(f"not found: {item}" for item in errors.get(field, []))

        articles: list[Article] = []
        if pmids:
            articles = parse_article_set(await self.client.efetch(pmids))
            # EFetch does not guarantee input order; relevance ranking comes from ESearch.
            by_pmid = {article.pmid: article for article in articles}
            articles = [by_pmid[pmid] for pmid in pmids if pmid in by_pmid]

        return SearchResult(
            query=translated,
            total_results=total,
            returned=len(articles),
            retstart=retstart,
            articles=articles,
            warnings=warnings,
        )

    async def summaries(self, pmids: list[str]) -> dict[str, object]:
        """Raw ESummary payload for known PMIDs, keyed by PMID (plus a `uids` list)."""
        return await self.client.esummary(pmids)
