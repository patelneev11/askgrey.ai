from __future__ import annotations

import ipaddress
import socket
from collections.abc import Callable

import httpx

from app.core.dependency_health import MonitoredAsyncClient

from .errors import PdfFetchError

MAX_PDF_BYTES = 25 * 1024 * 1024
MAX_REDIRECTS = 5
PMC_ARTICLE_HOSTS = ("pmc.ncbi.nlm.nih.gov", "www.ncbi.nlm.nih.gov")

# The caller chooses the URL, so a blocked target must not be distinguishable from an
# unreachable one: any difference in wording turns this endpoint into an internal port scanner.
BLOCKED_MESSAGE = "that URL could not be fetched"

Resolver = Callable[[str], list[str]]


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


def system_resolver(host: str) -> list[str]:
    try:
        infos = socket.getaddrinfo(host, None, proto=socket.IPPROTO_TCP)
    except OSError as exc:
        raise PdfFetchError(BLOCKED_MESSAGE) from exc
    return [str(info[4][0]) for info in infos]


def is_ip_literal(host: str) -> bool:
    try:
        ipaddress.ip_address(host)
    except ValueError:
        return False
    return True


def is_public_address(address: str) -> bool:
    try:
        parsed = ipaddress.ip_address(address)
    except ValueError:
        return False
    if isinstance(parsed, ipaddress.IPv6Address) and parsed.ipv4_mapped is not None:
        parsed = parsed.ipv4_mapped
    return parsed.is_global


class PdfFetcher:
    """
    Downloads a PDF from a full-text link (PMC or publisher).

    The URL is caller-supplied, so every hop is treated as hostile: only http(s) is allowed,
    every hostname must resolve exclusively to public addresses, redirects are followed
    manually so each new target is checked the same way, and the body is size-capped while
    it streams rather than after it has been buffered.

    Known residual risk: the address check and the connection are separate DNS lookups, so a
    rebinding attacker with sub-second TTL control could still slip through. Pinning the
    connection to the validated address needs a custom transport and is tracked separately.
    """

    def __init__(
        self,
        *,
        timeout: float = 30.0,
        user_agent: str = "askgrey/0.1",
        max_bytes: int = MAX_PDF_BYTES,
        transport: httpx.AsyncBaseTransport | None = None,
        resolver: Resolver = system_resolver,
    ) -> None:
        self.max_bytes = max_bytes
        self.resolver = resolver
        self._client = MonitoredAsyncClient(
            "pdf_fetch",
            timeout=timeout,
            follow_redirects=False,
            headers={"User-Agent": user_agent, "Accept": "application/pdf"},
            transport=transport,
        )

    async def aclose(self) -> None:
        await self._client.aclose()

    def _validate(self, url: httpx.URL) -> None:
        if url.scheme not in {"http", "https"}:
            raise PdfFetchError("only http(s) URLs can be fetched")
        host = url.host
        if not host:
            raise PdfFetchError(BLOCKED_MESSAGE)
        addresses = [host] if is_ip_literal(host) else self.resolver(host)
        if not addresses or not all(is_public_address(address) for address in addresses):
            raise PdfFetchError(BLOCKED_MESSAGE)

    async def fetch(self, url: str) -> tuple[bytes, str]:
        """Return the PDF bytes and the URL they were actually served from."""
        target = httpx.URL(normalize_pmc_url(url))
        for _ in range(MAX_REDIRECTS + 1):
            self._validate(target)
            response, location = await self._get(target)
            if location is None:
                return response, str(target)
            target = target.join(location)
        raise PdfFetchError("too many redirects")

    async def _get(self, target: httpx.URL) -> tuple[bytes, str | None]:
        """Fetch one hop: either the body, or the redirect location to validate and follow."""
        try:
            async with self._client.stream("GET", target) as response:
                if response.is_redirect:
                    location = response.headers.get("location")
                    if not location:
                        raise PdfFetchError(BLOCKED_MESSAGE)
                    return b"", location
                if response.status_code >= 400:
                    raise PdfFetchError(f"the URL returned HTTP {response.status_code}")
                content = await self._read_capped(response)
        except httpx.HTTPError as exc:
            raise PdfFetchError(BLOCKED_MESSAGE) from exc
        if not content:
            raise PdfFetchError("the URL returned an empty body")
        return content, None

    async def _read_capped(self, response: httpx.Response) -> bytes:
        declared = response.headers.get("content-length")
        if declared and declared.isdigit() and int(declared) > self.max_bytes:
            raise PdfFetchError(f"PDF is larger than {self.max_bytes} bytes")
        chunks: list[bytes] = []
        total = 0
        async for chunk in response.aiter_bytes():
            total += len(chunk)
            if total > self.max_bytes:
                raise PdfFetchError(f"PDF is larger than {self.max_bytes} bytes")
            chunks.append(chunk)
        return b"".join(chunks)
