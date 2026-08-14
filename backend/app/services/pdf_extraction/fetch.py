from __future__ import annotations

import httpx

from .errors import PdfFetchError

MAX_PDF_BYTES = 25 * 1024 * 1024
PMC_ARTICLE_HOSTS = ("pmc.ncbi.nlm.nih.gov", "www.ncbi.nlm.nih.gov")


def normalize_pmc_url(url: str) -> str:
    """
    Point a PMC article URL at its PDF.

    `https://pmc.ncbi.nlm.nih.gov/articles/PMC1234567/` serves HTML; the same path with a
    trailing `pdf/` serves the file. Any other URL is returned unchanged.
    """
    stripped = url.strip()
    parsed = httpx.URL(stripped)
    if parsed.host in PMC_ARTICLE_HOSTS and "/articles/" in parsed.path:
        path = parsed.path.rstrip("/")
        if not path.endswith("/pdf") and not path.endswith(".pdf"):
            return str(parsed.copy_with(path=f"{path}/pdf/"))
    return stripped


class PdfFetcher:
    """Downloads a PDF from a full-text link (PMC or publisher)."""

    def __init__(
        self,
        *,
        timeout: float = 30.0,
        user_agent: str = "askgrey/0.1",
        max_bytes: int = MAX_PDF_BYTES,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self.max_bytes = max_bytes
        self._client = httpx.AsyncClient(
            timeout=timeout,
            follow_redirects=True,
            headers={"User-Agent": user_agent, "Accept": "application/pdf"},
            transport=transport,
        )

    async def aclose(self) -> None:
        await self._client.aclose()

    async def fetch(self, url: str) -> tuple[bytes, str]:
        """Return the PDF bytes and the URL they were actually served from."""
        target = normalize_pmc_url(url)
        if httpx.URL(target).scheme not in {"http", "https"}:
            raise PdfFetchError("only http(s) URLs can be fetched")
        try:
            response = await self._client.get(target)
        except httpx.HTTPError as exc:
            raise PdfFetchError(f"could not fetch {target}: {exc}") from exc
        if response.status_code >= 400:
            raise PdfFetchError(f"{target} returned HTTP {response.status_code}")
        content = response.content
        if len(content) > self.max_bytes:
            raise PdfFetchError(f"PDF is larger than {self.max_bytes} bytes")
        if not content:
            raise PdfFetchError(f"{target} returned an empty body")
        return content, str(response.url)
