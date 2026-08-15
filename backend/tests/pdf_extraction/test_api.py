from __future__ import annotations

from collections.abc import Callable, Iterator

import httpx
import pytest
from fastapi.testclient import TestClient

from app.api.pdf_extraction import MAX_UPLOAD_BYTES, get_pdf_extraction_service
from app.main import app
from app.services.pdf_extraction import PdfExtractionService, PdfFetcher, RawDataPoint
from tests.pdf_extraction.conftest import StubExtractor, fixture_bytes

CREDENTIALS = {"email": "reader@askgrey.ai", "password": "obsidian-workspace-1"}
GOAL = "sample size, dosing regimen"
POINT = RawDataPoint(
    field="sample_size",
    value="73 patients",
    quote="73 patients were randomized in a double-blinded, placebo-controlled study",
    block_id="p1-b4",
)


# The fetcher rejects any host that does not resolve to a public address, so tests that are
# not about SSRF stub the lookup rather than depending on live DNS.
def public_resolver(host: str) -> list[str]:
    return ["93.184.216.34"]


class FetchTransport(httpx.AsyncBaseTransport):
    def __init__(self, response: httpx.Response) -> None:
        self.response = response
        self.requests: list[httpx.Request] = []

    async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        return self.response


@pytest.fixture
def install() -> Iterator[Callable[..., FetchTransport]]:
    def _install(
        *points: RawDataPoint,
        fetch: httpx.Response | None = None,
        extractor: StubExtractor | None = None,
    ) -> FetchTransport:
        transport = FetchTransport(fetch or httpx.Response(200, content=b""))
        app.dependency_overrides[get_pdf_extraction_service] = lambda: PdfExtractionService(
            extractor or StubExtractor(*points),
            PdfFetcher(transport=transport, resolver=public_resolver),
        )
        return transport

    yield _install
    app.dependency_overrides.pop(get_pdf_extraction_service, None)


def auth_header(client: TestClient) -> dict[str, str]:
    tokens = client.post("/api/auth/register", json=CREDENTIALS).json()
    return {"Authorization": f"Bearer {tokens['access_token']}"}


def upload(client: TestClient, name: str, **kwargs: object) -> httpx.Response:
    return client.post(
        "/api/pdf-extraction/upload",
        files={"file": (f"{name}.pdf", fixture_bytes(name), "application/pdf")},
        data={"goal": GOAL},
        **kwargs,
    )


def test_upload_requires_authentication(
    client: TestClient, install: Callable[..., FetchTransport]
) -> None:
    install(POINT)

    assert upload(client, "trial_ziprasidone").status_code == 401


def test_upload_returns_a_cited_table(
    client: TestClient, install: Callable[..., FetchTransport]
) -> None:
    install(POINT)

    response = upload(client, "trial_ziprasidone", headers=auth_header(client))

    assert response.status_code == 200
    body = response.json()
    assert [column["key"] for column in body["columns"]] == ["sample_size", "dosing_regimen"]
    cell = body["rows"][0]["cells"]["sample_size"]
    assert cell["value"] == "73 patients"
    assert cell["citation"]["page_number"] == 1
    assert cell["citation"]["rects"]
    assert body["rows"][0]["filename"] == "trial_ziprasidone.pdf"


def test_scanned_upload_is_415(client: TestClient, install: Callable[..., FetchTransport]) -> None:
    install(POINT)

    response = upload(client, "scanned_no_text_layer", headers=auth_header(client))

    assert response.status_code == 415
    assert "OCR" in response.json()["detail"]


def test_empty_goal_is_422(client: TestClient, install: Callable[..., FetchTransport]) -> None:
    install(POINT)

    response = client.post(
        "/api/pdf-extraction/upload",
        files={"file": ("x.pdf", fixture_bytes("trial_ziprasidone"), "application/pdf")},
        data={"goal": "   "},
        headers=auth_header(client),
    )

    assert response.status_code == 422


def test_url_extraction_fetches_and_extracts(
    client: TestClient, install: Callable[..., FetchTransport]
) -> None:
    transport = install(
        POINT, fetch=httpx.Response(200, content=fixture_bytes("trial_ziprasidone"))
    )

    response = client.post(
        "/api/pdf-extraction/url",
        json={"url": "https://pmc.ncbi.nlm.nih.gov/articles/PMC1234567/", "goal": GOAL},
        headers=auth_header(client),
    )

    assert response.status_code == 200
    assert str(transport.requests[0].url) == (
        "https://pmc.ncbi.nlm.nih.gov/articles/PMC1234567/pdf/"
    )
    citation = response.json()["rows"][0]["cells"]["sample_size"]["citation"]
    assert citation["source_url"].endswith("/pdf/")


def test_unreachable_url_is_502(client: TestClient, install: Callable[..., FetchTransport]) -> None:
    install(POINT, fetch=httpx.Response(404, text="missing"))

    response = client.post(
        "/api/pdf-extraction/url",
        json={"url": "https://example.org/missing.pdf", "goal": GOAL},
        headers=auth_header(client),
    )

    assert response.status_code == 502


def test_a_non_pdf_upload_is_415(
    client: TestClient, install: Callable[..., FetchTransport]
) -> None:
    install(POINT)

    response = client.post(
        "/api/pdf-extraction/upload",
        files={"file": ("payload.pdf", b"<html>not a pdf</html>", "application/pdf")},
        data={"goal": GOAL},
        headers=auth_header(client),
    )

    assert response.status_code == 415
    assert response.json()["detail"] == "the uploaded file is not a PDF"


def test_an_oversized_upload_is_413(
    client: TestClient, install: Callable[..., FetchTransport]
) -> None:
    install(POINT)

    response = client.post(
        "/api/pdf-extraction/upload",
        files={"file": ("big.pdf", b"%PDF-" + b"0" * (MAX_UPLOAD_BYTES + 1), "application/pdf")},
        data={"goal": GOAL},
        headers=auth_header(client),
    )

    assert response.status_code == 413


def test_an_internal_url_is_refused_without_a_request(
    client: TestClient, install: Callable[..., FetchTransport]
) -> None:
    transport = install(POINT, fetch=httpx.Response(200, content=b"%PDF-1.4"))

    response = client.post(
        "/api/pdf-extraction/url",
        json={"url": "http://169.254.169.254/latest/meta-data/", "goal": GOAL},
        headers=auth_header(client),
    )

    assert response.status_code == 502
    assert transport.requests == []


def test_missing_llm_credentials_is_503(
    client: TestClient, install: Callable[..., FetchTransport]
) -> None:
    app.dependency_overrides[get_pdf_extraction_service] = lambda: PdfExtractionService(None)

    response = upload(client, "trial_ziprasidone", headers=auth_header(client))

    assert response.status_code == 503
