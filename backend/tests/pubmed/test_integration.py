from __future__ import annotations

from datetime import date

import httpx
import pytest

from app.services.pubmed.client import EntrezClient
from app.services.pubmed.errors import EntrezRequestError, EntrezResponseError
from app.services.pubmed.service import PubMedService
from app.services.pubmed.translation import RuleBasedQueryTranslator
from app.services.rate_limit import RateLimiter
from tests.pubmed.conftest import (
    RecordingTransport,
    json_response,
    load_fixture,
    load_json_fixture,
    xml_response,
)

TODAY = date(2024, 6, 1)


def recorded_transport(
    *,
    esearch: str = "esearch_semaglutide.json",
    efetch: str = "efetch_semaglutide.xml",
) -> RecordingTransport:
    return RecordingTransport(
        {
            "esearch.fcgi": lambda _: json_response(load_json_fixture(esearch)),
            "efetch.fcgi": lambda _: xml_response(load_fixture(efetch)),
            "esummary.fcgi": lambda _: json_response(
                load_json_fixture("esummary_semaglutide.json")
            ),
        }
    )


def build_service(transport: httpx.AsyncBaseTransport, *, api_key: str = "") -> PubMedService:
    client = EntrezClient(
        api_key=api_key,
        email="dev@askgrey.ai",
        transport=transport,
        rate_limiter=RateLimiter(1000.0),
        base_delay=0.0,
    )
    return PubMedService(client=client, translator=RuleBasedQueryTranslator(today=TODAY))


class TestEntrezClient:
    @pytest.mark.asyncio
    async def test_sends_required_ncbi_parameters(self) -> None:
        transport = recorded_transport()
        client = EntrezClient(
            api_key="secret-key",
            email="dev@askgrey.ai",
            transport=transport,
            rate_limiter=RateLimiter(1000.0),
        )
        await client.esearch("obesity[tiab]", retmax=5, retstart=10)
        await client.aclose()

        params = transport.params_for("esearch.fcgi")[0]
        assert params["db"] == ["pubmed"]
        assert params["tool"] == ["askgrey"]
        assert params["email"] == ["dev@askgrey.ai"]
        assert params["api_key"] == ["secret-key"]
        assert params["term"] == ["obesity[tiab]"]
        assert params["retmax"] == ["5"]
        assert params["retstart"] == ["10"]
        assert params["retmode"] == ["json"]

    @pytest.mark.asyncio
    async def test_omits_credentials_when_unset(self) -> None:
        transport = recorded_transport()
        client = EntrezClient(transport=transport, rate_limiter=RateLimiter(1000.0))
        await client.esearch("obesity[tiab]")
        await client.aclose()

        params = transport.params_for("esearch.fcgi")[0]
        assert "api_key" not in params
        assert "email" not in params

    @pytest.mark.asyncio
    async def test_retries_throttled_responses_then_succeeds(self, no_sleep: list[float]) -> None:
        calls = {"n": 0}

        def handler(_: dict[str, list[str]]) -> httpx.Response:
            calls["n"] += 1
            if calls["n"] < 3:
                return httpx.Response(429, text="too many requests")
            return json_response(load_json_fixture("esearch_semaglutide.json"))

        transport = RecordingTransport({"esearch.fcgi": handler})
        client = EntrezClient(transport=transport, rate_limiter=RateLimiter(1000.0), base_delay=0.5)
        result = await client.esearch("obesity[tiab]")
        await client.aclose()

        assert calls["n"] == 3
        assert result["count"] == "412"
        assert 0.5 in no_sleep and 1.0 in no_sleep

    @pytest.mark.asyncio
    async def test_gives_up_and_reports_status(self, no_sleep: list[float]) -> None:
        transport = RecordingTransport({"esearch.fcgi": lambda _: httpx.Response(503)})
        client = EntrezClient(
            transport=transport, rate_limiter=RateLimiter(1000.0), max_attempts=2, base_delay=0.1
        )
        with pytest.raises(EntrezRequestError) as excinfo:
            await client.esearch("obesity[tiab]")
        await client.aclose()

        assert excinfo.value.status_code == 503
        assert len(transport.requests) == 2

    @pytest.mark.asyncio
    async def test_client_errors_are_not_retried(self, no_sleep: list[float]) -> None:
        transport = RecordingTransport({"esearch.fcgi": lambda _: httpx.Response(400)})
        client = EntrezClient(transport=transport, rate_limiter=RateLimiter(1000.0))
        with pytest.raises(EntrezRequestError):
            await client.esearch("obesity[tiab]")
        await client.aclose()

        assert len(transport.requests) == 1

    @pytest.mark.asyncio
    async def test_non_json_body_raises_response_error(self) -> None:
        transport = RecordingTransport(
            {"esearch.fcgi": lambda _: httpx.Response(200, text="<html>")}
        )
        client = EntrezClient(transport=transport, rate_limiter=RateLimiter(1000.0))
        with pytest.raises(EntrezResponseError):
            await client.esearch("obesity[tiab]")
        await client.aclose()

    @pytest.mark.asyncio
    async def test_esummary_returns_result_payload(self) -> None:
        transport = recorded_transport()
        client = EntrezClient(transport=transport, rate_limiter=RateLimiter(1000.0))
        summaries = await client.esummary(["37733246"])
        await client.aclose()

        assert summaries["37733246"]["source"] == "N Engl J Med"
        assert transport.params_for("esummary.fcgi")[0]["id"] == ["37733246"]

    @pytest.mark.asyncio
    async def test_no_request_is_made_for_empty_id_lists(self) -> None:
        transport = recorded_transport()
        client = EntrezClient(transport=transport, rate_limiter=RateLimiter(1000.0))
        assert await client.efetch([]) == ""
        assert await client.esummary([]) == {}
        await client.aclose()

        assert transport.requests == []


class TestPubMedServiceSearch:
    @pytest.mark.asyncio
    async def test_returns_normalized_articles_for_a_natural_language_query(self) -> None:
        transport = recorded_transport()
        service = build_service(transport)
        result = await service.search(
            "randomized controlled trials of semaglutide for obesity since 2021", limit=2
        )
        await service.aclose()

        assert result.total_results == 412
        assert result.returned == 2
        assert [article.pmid for article in result.articles] == ["37733246", "34499262"]
        assert result.articles[0].full_text_url is not None
        assert '"Randomized Controlled Trial"[Publication Type]' in result.query.term

        search_params = transport.params_for("esearch.fcgi")[0]
        assert search_params["term"] == [result.query.term]
        assert transport.params_for("efetch.fcgi")[0]["id"] == ["37733246,34499262"]

    @pytest.mark.asyncio
    async def test_empty_result_skips_efetch_and_surfaces_warnings(self) -> None:
        transport = recorded_transport(esearch="esearch_empty.json")
        service = build_service(transport)
        result = await service.search("zzzzqqqq")
        await service.aclose()

        assert result.total_results == 0
        assert result.returned == 0
        assert result.articles == []
        assert result.warnings == ["not found: zzzzqqqq"]
        assert transport.params_for("efetch.fcgi") == []

    @pytest.mark.asyncio
    async def test_results_follow_esearch_relevance_order(self) -> None:
        reversed_ids = {
            "esearch.fcgi": lambda _: json_response(
                {"esearchresult": {"count": "2", "idlist": ["34499262", "37733246"]}}
            ),
            "efetch.fcgi": lambda _: xml_response(load_fixture("efetch_semaglutide.xml")),
        }
        service = build_service(RecordingTransport(reversed_ids))
        result = await service.search("semaglutide obesity")
        await service.aclose()

        assert [article.pmid for article in result.articles] == ["34499262", "37733246"]

    @pytest.mark.asyncio
    async def test_page_size_is_clamped(self) -> None:
        transport = recorded_transport()
        service = build_service(transport)
        await service.search("semaglutide obesity", limit=5000, offset=-3)
        await service.aclose()

        params = transport.params_for("esearch.fcgi")[0]
        assert params["retmax"] == ["100"]
        assert params["retstart"] == ["0"]
