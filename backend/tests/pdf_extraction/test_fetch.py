from __future__ import annotations

import httpx
import pytest

from app.services.pdf_extraction.errors import PdfFetchError
from app.services.pdf_extraction.fetch import PdfFetcher, is_public_address

PDF = b"%PDF-1.4 body"


class ScriptedTransport(httpx.AsyncBaseTransport):
    """Answers each request from a queue so redirect chains can be exercised."""

    def __init__(self, *responses: httpx.Response) -> None:
        self.responses = list(responses)
        self.requests: list[httpx.Request] = []

    async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        return self.responses.pop(0)


def public(_host: str) -> list[str]:
    return ["93.184.216.34"]


def internal(_host: str) -> list[str]:
    return ["10.0.0.7"]


def mixed(_host: str) -> list[str]:
    return ["93.184.216.34", "127.0.0.1"]


@pytest.mark.parametrize(
    ("address", "expected"),
    [
        ("93.184.216.34", True),
        ("127.0.0.1", False),
        ("10.0.0.7", False),
        ("192.168.1.10", False),
        ("172.16.0.1", False),
        ("169.254.169.254", False),  # cloud instance metadata
        ("100.64.0.1", False),  # carrier-grade NAT
        ("::1", False),
        ("::ffff:127.0.0.1", False),  # ipv4-mapped loopback
        ("2606:4700:4700::1111", True),
        ("not-an-address", False),
    ],
)
def test_public_address_classification(address: str, expected: bool) -> None:
    assert is_public_address(address) is expected


@pytest.mark.asyncio
async def test_a_public_host_is_fetched() -> None:
    transport = ScriptedTransport(httpx.Response(200, content=PDF))
    fetcher = PdfFetcher(transport=transport, resolver=public)

    content, url = await fetcher.fetch("https://example.org/paper.pdf")

    assert content == PDF
    assert url == "https://example.org/paper.pdf"


@pytest.mark.asyncio
async def test_a_literal_internal_address_never_reaches_the_network() -> None:
    transport = ScriptedTransport(httpx.Response(200, content=PDF))
    fetcher = PdfFetcher(transport=transport, resolver=public)

    with pytest.raises(PdfFetchError):
        await fetcher.fetch("http://169.254.169.254/latest/meta-data/")

    assert transport.requests == []


@pytest.mark.asyncio
async def test_a_host_resolving_internally_never_reaches_the_network() -> None:
    transport = ScriptedTransport(httpx.Response(200, content=PDF))
    fetcher = PdfFetcher(transport=transport, resolver=internal)

    with pytest.raises(PdfFetchError):
        await fetcher.fetch("https://internal.example.org/paper.pdf")

    assert transport.requests == []


@pytest.mark.asyncio
async def test_one_internal_address_among_several_blocks_the_host() -> None:
    fetcher = PdfFetcher(transport=ScriptedTransport(), resolver=mixed)

    with pytest.raises(PdfFetchError):
        await fetcher.fetch("https://split-horizon.example.org/paper.pdf")


@pytest.mark.asyncio
async def test_a_redirect_into_the_private_network_is_refused() -> None:
    transport = ScriptedTransport(
        httpx.Response(302, headers={"location": "http://169.254.169.254/latest/meta-data/"}),
        httpx.Response(200, content=PDF),
    )
    fetcher = PdfFetcher(transport=transport, resolver=public)

    with pytest.raises(PdfFetchError):
        await fetcher.fetch("https://example.org/paper.pdf")

    assert len(transport.requests) == 1


@pytest.mark.asyncio
async def test_a_redirect_to_another_public_host_is_followed() -> None:
    transport = ScriptedTransport(
        httpx.Response(302, headers={"location": "https://cdn.example.net/paper.pdf"}),
        httpx.Response(200, content=PDF),
    )
    fetcher = PdfFetcher(transport=transport, resolver=public)

    content, url = await fetcher.fetch("https://example.org/paper.pdf")

    assert content == PDF
    assert url == "https://cdn.example.net/paper.pdf"


@pytest.mark.asyncio
async def test_a_redirect_loop_stops() -> None:
    transport = ScriptedTransport(
        *[httpx.Response(302, headers={"location": "https://example.org/paper.pdf"})] * 8
    )
    fetcher = PdfFetcher(transport=transport, resolver=public)

    with pytest.raises(PdfFetchError, match="too many redirects"):
        await fetcher.fetch("https://example.org/paper.pdf")


@pytest.mark.asyncio
async def test_a_declared_oversize_body_is_refused_before_it_is_read() -> None:
    transport = ScriptedTransport(
        httpx.Response(200, content=PDF, headers={"content-length": str(50 * 1024 * 1024)})
    )
    fetcher = PdfFetcher(transport=transport, resolver=public, max_bytes=1024)

    with pytest.raises(PdfFetchError, match="larger than"):
        await fetcher.fetch("https://example.org/paper.pdf")


@pytest.mark.asyncio
async def test_a_body_that_outgrows_the_cap_mid_stream_is_refused() -> None:
    transport = ScriptedTransport(httpx.Response(200, content=b"%PDF-" + b"0" * 4096))
    fetcher = PdfFetcher(transport=transport, resolver=public, max_bytes=1024)

    with pytest.raises(PdfFetchError, match="larger than"):
        await fetcher.fetch("https://example.org/paper.pdf")


@pytest.mark.asyncio
async def test_a_transport_failure_is_not_distinguishable_from_a_blocked_target() -> None:
    class Failing(httpx.AsyncBaseTransport):
        async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
            raise httpx.ConnectError("connection refused", request=request)

    blocked = PdfFetcher(transport=Failing(), resolver=internal)
    unreachable = PdfFetcher(transport=Failing(), resolver=public)

    with pytest.raises(PdfFetchError) as blocked_error:
        await blocked.fetch("https://internal.example.org/paper.pdf")
    with pytest.raises(PdfFetchError) as unreachable_error:
        await unreachable.fetch("https://example.org/paper.pdf")

    assert str(blocked_error.value) == str(unreachable_error.value)
