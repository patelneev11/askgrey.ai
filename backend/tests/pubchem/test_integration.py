from __future__ import annotations

import httpx
import pytest

from app.services.pubchem.client import PugRestClient
from app.services.pubchem.errors import PubChemRequestError, PubChemResponseError
from app.services.pubchem.service import PubChemService
from app.services.rate_limit import RateLimiter
from tests.pubchem.conftest import (
    Body,
    RecordingTransport,
    fault_response,
    fixture_response,
    json_response,
    sequence,
)

SMILES_CIDS = "compound/smiles/cids/JSON"
PROPERTIES = (
    "compound/cid/property/"
    "Title,MolecularFormula,MolecularWeight,SMILES,ConnectivitySMILES,IUPACName,XLogP/JSON"
)
SYNONYMS = "compound/cid/synonyms/JSON"

ASPIRIN_SMILES = "CC(=O)Oc1ccccc1C(=O)O"


def build_client(
    transport: httpx.AsyncBaseTransport, *, max_attempts: int = 4, base_delay: float = 0.5
) -> PugRestClient:
    return PugRestClient(
        transport=transport,
        rate_limiter=RateLimiter(1000.0),
        max_attempts=max_attempts,
        base_delay=base_delay,
    )


def backoff_delays(delays: list[float]) -> list[float]:
    """Retry backoff only; the rate limiter's sub-interval waits share the same sleep hook."""
    return [delay for delay in delays if delay >= 0.1]


class FakeClock:
    """A clock that only advances by the time the (patched) sleeps claim to have taken."""

    def __init__(self, slept: list[float]) -> None:
        self.slept = slept

    def now(self) -> float:
        return sum(self.slept)


class FailingTransport(httpx.AsyncBaseTransport):
    """Raises a transport error for the first `failures` requests, then delegates."""

    def __init__(self, failures: int, inner: httpx.AsyncBaseTransport, error: Exception) -> None:
        self.remaining = failures
        self.inner = inner
        self.error = error
        self.attempts = 0

    async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
        self.attempts += 1
        if self.remaining > 0:
            self.remaining -= 1
            raise self.error
        return await self.inner.handle_async_request(request)


class TestRecordedLookups:
    @pytest.mark.asyncio
    async def test_full_lookup_against_recorded_responses(self) -> None:
        transport = RecordingTransport(
            {
                SMILES_CIDS: fixture_response("cids_smiles_aspirin.json"),
                PROPERTIES: fixture_response("properties_aspirin.json"),
                SYNONYMS: fixture_response("synonyms_aspirin.json"),
            }
        )
        service = PubChemService(client=build_client(transport), max_candidates=10)

        result = await service.lookup(ASPIRIN_SMILES)

        assert result.match is not None
        assert result.match.title == "Aspirin"
        assert result.match.canonical_smiles == "CC(=O)OC1=CC=CC=C1C(=O)O"
        row = result.match.to_source_record()
        assert row.fields["Formula"] == "C9H8O4"

    @pytest.mark.asyncio
    async def test_identifiers_are_sent_as_form_bodies_not_path_segments(self) -> None:
        transport = RecordingTransport(
            {
                SMILES_CIDS: fixture_response("cids_smiles_aspirin.json"),
                PROPERTIES: fixture_response("properties_aspirin.json"),
                SYNONYMS: fixture_response("synonyms_aspirin.json"),
            }
        )

        await PubChemService(client=build_client(transport)).lookup("C1=CC=C(C=C1)C/C=C/C(=O)O")

        # `/` and `#` in a structure would otherwise be read as PUG-REST path syntax.
        assert all(request.method == "POST" for request in transport.requests)
        assert transport.bodies_for(SMILES_CIDS) == [{"smiles": ["C1=CC=C(C=C1)C/C=C/C(=O)O"]}]


class TestDowntimeHandling:
    @pytest.mark.asyncio
    async def test_retries_service_unavailable_then_succeeds(self, no_sleep: list[float]) -> None:
        transport = RecordingTransport(
            {
                SMILES_CIDS: sequence(
                    fault_response("PUGREST.ServerBusy", 503),
                    fault_response("PUGREST.ServerBusy", 503),
                    fixture_response("cids_smiles_aspirin.json"),
                ),
                PROPERTIES: fixture_response("properties_aspirin.json"),
                SYNONYMS: fixture_response("synonyms_aspirin.json"),
            }
        )

        result = await PubChemService(client=build_client(transport)).lookup(ASPIRIN_SMILES)

        assert result.match is not None
        assert len(transport.bodies_for(SMILES_CIDS)) == 3
        assert backoff_delays(no_sleep) == [0.5, 1.0]

    @pytest.mark.asyncio
    async def test_retries_throttling(self, no_sleep: list[float]) -> None:
        transport = RecordingTransport(
            {
                SMILES_CIDS: sequence(
                    fault_response("PUGREST.ServerBusy", 429),
                    fixture_response("cids_smiles_aspirin.json"),
                ),
                PROPERTIES: fixture_response("properties_aspirin.json"),
                SYNONYMS: fixture_response("synonyms_aspirin.json"),
            }
        )

        await PubChemService(client=build_client(transport)).lookup(ASPIRIN_SMILES)

        assert backoff_delays(no_sleep) == [0.5]

    @pytest.mark.asyncio
    async def test_gives_up_after_max_attempts(self, no_sleep: list[float]) -> None:
        transport = RecordingTransport({SMILES_CIDS: fault_response("PUGREST.ServerBusy", 503)})
        client = build_client(transport, max_attempts=3, base_delay=0.1)

        with pytest.raises(PubChemRequestError) as excinfo:
            await client.cids_for_smiles(ASPIRIN_SMILES)

        assert excinfo.value.status_code == 503
        assert len(transport.requests) == 3

    @pytest.mark.asyncio
    async def test_timeout_is_retried_and_then_surfaced(self, no_sleep: list[float]) -> None:
        inner = RecordingTransport({SMILES_CIDS: fixture_response("cids_smiles_aspirin.json")})
        transport = FailingTransport(2, inner, httpx.ConnectTimeout("timed out"))
        client = PugRestClient(transport=transport, rate_limiter=RateLimiter(1000.0))

        cids = await client.cids_for_smiles(ASPIRIN_SMILES)

        assert cids == [2244]
        assert transport.attempts == 3

    @pytest.mark.asyncio
    async def test_persistent_timeout_raises(self, no_sleep: list[float]) -> None:
        inner = RecordingTransport({})
        transport = FailingTransport(10, inner, httpx.ConnectTimeout("timed out"))
        client = PugRestClient(
            transport=transport, rate_limiter=RateLimiter(1000.0), max_attempts=2
        )

        with pytest.raises(PubChemRequestError) as excinfo:
            await client.cids_for_smiles(ASPIRIN_SMILES)

        assert excinfo.value.status_code is None
        assert transport.attempts == 2

    @pytest.mark.asyncio
    async def test_client_errors_are_not_retried(self, no_sleep: list[float]) -> None:
        transport = RecordingTransport({SMILES_CIDS: fault_response("PUGREST.BadRequest", 400)})

        with pytest.raises(PubChemRequestError) as excinfo:
            await build_client(transport).cids_for_smiles("not_a_smiles((")

        assert excinfo.value.code == "PUGREST.BadRequest"
        assert len(transport.requests) == 1
        assert backoff_delays(no_sleep) == []


class TestMalformedResponses:
    @pytest.mark.asyncio
    async def test_non_json_body(self) -> None:
        def html(_body: Body) -> httpx.Response:
            return httpx.Response(200, text="<html>maintenance</html>")

        transport = RecordingTransport({SMILES_CIDS: html})

        with pytest.raises(PubChemResponseError):
            await build_client(transport).cids_for_smiles(ASPIRIN_SMILES)

    @pytest.mark.asyncio
    async def test_payload_missing_expected_keys(self) -> None:
        transport = RecordingTransport({SMILES_CIDS: lambda _body: json_response({"Waiting": {}})})

        with pytest.raises(PubChemResponseError):
            await build_client(transport).cids_for_smiles(ASPIRIN_SMILES)

    @pytest.mark.asyncio
    async def test_property_table_missing(self) -> None:
        transport = RecordingTransport({PROPERTIES: lambda _body: json_response({})})

        with pytest.raises(PubChemResponseError):
            await build_client(transport).properties([2244])


class TestRateLimiting:
    @pytest.mark.asyncio
    async def test_requests_are_spaced_at_the_pubchem_limit(self, no_sleep: list[float]) -> None:
        transport = RecordingTransport(
            {
                SMILES_CIDS: fixture_response("cids_smiles_aspirin.json"),
                PROPERTIES: fixture_response("properties_aspirin.json"),
                SYNONYMS: fixture_response("synonyms_aspirin.json"),
            }
        )
        clock = FakeClock(no_sleep)
        client = PugRestClient(
            transport=transport,
            rate_limiter=RateLimiter(5.0, time_source=clock.now),
        )

        await PubChemService(client=client).lookup(ASPIRIN_SMILES)

        # A lookup is three sequential calls; at 5/s the first is free and the rest wait 200ms.
        assert len(transport.requests) == 3
        assert no_sleep == pytest.approx([0.2, 0.2])
