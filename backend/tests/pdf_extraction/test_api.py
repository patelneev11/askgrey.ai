from __future__ import annotations

from collections.abc import Callable, Iterator

import httpx
import pytest
from fastapi.testclient import TestClient

from app.api import deps
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


OTHER_CREDENTIALS = {"email": "second@askgrey.ai", "password": "obsidian-workspace-2"}


def second_user(client: TestClient) -> dict[str, str]:
    tokens = client.post("/api/auth/register", json=OTHER_CREDENTIALS).json()
    return {"Authorization": f"Bearer {tokens['access_token']}"}


def test_an_uploaded_paper_can_be_read_back_for_its_citations(
    client: TestClient, install: Callable[..., FetchTransport]
) -> None:
    install(POINT)
    headers = auth_header(client)

    document_id = upload(client, "trial_ziprasidone", headers=headers).json()["rows"][0][
        "document_id"
    ]
    served = client.get(f"/api/literature/documents/{document_id}/pdf", headers=headers)

    assert served.status_code == 200
    assert served.headers["content-type"] == "application/pdf"
    assert served.content == fixture_bytes("trial_ziprasidone")


def test_a_linked_paper_is_stored_so_its_pages_render_like_an_upload(
    client: TestClient, install: Callable[..., FetchTransport]
) -> None:
    install(POINT, fetch=httpx.Response(200, content=fixture_bytes("trial_ziprasidone")))
    headers = auth_header(client)

    response = client.post(
        "/api/pdf-extraction/url",
        json={"url": "https://pmc.ncbi.nlm.nih.gov/articles/PMC1234567/", "goal": GOAL},
        headers=headers,
    )
    document_id = response.json()["rows"][0]["document_id"]

    served = client.get(f"/api/literature/documents/{document_id}/pdf", headers=headers)
    assert served.status_code == 200
    assert served.content.startswith(b"%PDF-")


def test_another_users_stored_paper_is_not_served(
    client: TestClient, install: Callable[..., FetchTransport]
) -> None:
    install(POINT)
    owner = auth_header(client)
    document_id = upload(client, "trial_ziprasidone", headers=owner).json()["rows"][0][
        "document_id"
    ]

    served = client.get(f"/api/literature/documents/{document_id}/pdf", headers=second_user(client))

    assert served.status_code == 404


def test_a_stored_paper_can_be_re_extracted_after_the_browser_forgot_it(
    client: TestClient, install: Callable[..., FetchTransport]
) -> None:
    install(POINT)
    headers = auth_header(client)
    document_id = upload(client, "trial_ziprasidone", headers=headers).json()["rows"][0][
        "document_id"
    ]

    response = client.post(
        f"/api/pdf-extraction/documents/{document_id}",
        json={"goal": "sample size"},
        headers=headers,
    )

    assert response.status_code == 200
    assert response.json()["rows"][0]["document_id"] == document_id


def test_re_extracting_someone_elses_document_is_404(
    client: TestClient, install: Callable[..., FetchTransport]
) -> None:
    install(POINT)
    document_id = upload(client, "trial_ziprasidone", headers=auth_header(client)).json()["rows"][
        0
    ]["document_id"]

    response = client.post(
        f"/api/pdf-extraction/documents/{document_id}",
        json={"goal": "sample size"},
        headers=second_user(client),
    )

    assert response.status_code == 404


def test_extraction_is_rate_limited_by_source_address_not_just_by_account(
    client: TestClient, install: Callable[..., FetchTransport]
) -> None:
    """A second account from the same host must not reset the expensive-endpoint budget."""
    install(POINT)
    deps.llm_ip_limiter.limit = 2
    try:
        first = auth_header(client)
        upload(client, "trial_ziprasidone", headers=first)
        upload(client, "trial_ziprasidone", headers=first)
        response = upload(client, "trial_ziprasidone", headers=second_user(client))
    finally:
        deps.llm_ip_limiter.limit = deps._settings.llm_ip_rate_limit_per_minute

    assert response.status_code == 429
