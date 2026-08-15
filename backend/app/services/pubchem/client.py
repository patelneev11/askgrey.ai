from __future__ import annotations

from typing import Any

import httpx

from app.core.dependency_health import MonitoredAsyncClient
from app.services.rate_limit import RateLimiter, retry_with_backoff

from .errors import PubChemRequestError, PubChemResponseError

PUG_REST_BASE_URL = "https://pubchem.ncbi.nlm.nih.gov/rest/pug"
RETRYABLE_STATUS_CODES = frozenset({429, 500, 502, 503, 504})

# PubChem renamed these in 2025: `SMILES` is what used to be `IsomericSMILES`, and
# `ConnectivitySMILES` is what used to be `CanonicalSMILES`. Both spellings are read back so a
# mirror still serving the old keys keeps working.
PROPERTY_NAMES = (
    "Title",
    "MolecularFormula",
    "MolecularWeight",
    "SMILES",
    "ConnectivitySMILES",
    "IUPACName",
    "XLogP",
)


class PugRestClient:
    """
    Thin async wrapper over the PUG-REST endpoints this product uses.

    Every request passes through a shared `RateLimiter` (PubChem allows 5 requests/second) and
    is retried with exponential backoff on 429/5xx and transport failures. Identifiers are sent
    as form bodies rather than path segments, because names and SMILES routinely contain `/`,
    `#` and `+`, which PUG-REST cannot disambiguate from its own path syntax.
    """

    def __init__(
        self,
        *,
        timeout: float = 20.0,
        rate_limiter: RateLimiter | None = None,
        transport: httpx.AsyncBaseTransport | None = None,
        base_url: str = PUG_REST_BASE_URL,
        max_attempts: int = 4,
        base_delay: float = 0.5,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.max_attempts = max_attempts
        self.base_delay = base_delay
        self.rate_limiter = rate_limiter or RateLimiter(5.0)
        self._client = MonitoredAsyncClient("pubchem", timeout=timeout, transport=transport)

    async def aclose(self) -> None:
        await self._client.aclose()

    async def __aenter__(self) -> PugRestClient:
        return self

    async def __aexit__(self, *exc_info: object) -> None:
        await self.aclose()

    async def _request(
        self,
        path: str,
        *,
        data: dict[str, str] | None = None,
        params: dict[str, str] | None = None,
    ) -> dict[str, Any]:
        url = f"{self.base_url}/{path.lstrip('/')}"

        async def attempt() -> httpx.Response:
            await self.rate_limiter.acquire()
            try:
                if data is None:
                    response = await self._client.get(url, params=params)
                else:
                    response = await self._client.post(url, data=data, params=params)
            except httpx.HTTPError as exc:
                raise PubChemRequestError(f"{path} request failed: {exc}") from exc
            if response.status_code >= 400:
                raise _fault_error(path, response)
            return response

        def should_retry(exc: BaseException) -> bool:
            if not isinstance(exc, PubChemRequestError):
                return False
            # A transport failure has no status code and is worth another attempt.
            return exc.status_code is None or exc.status_code in RETRYABLE_STATUS_CODES

        response = await retry_with_backoff(
            attempt,
            should_retry=should_retry,
            max_attempts=self.max_attempts,
            base_delay=self.base_delay,
        )
        try:
            payload = response.json()
        except ValueError as exc:
            raise PubChemResponseError(f"{path} returned a non-JSON body") from exc
        if not isinstance(payload, dict):
            raise PubChemResponseError(f"{path} returned a non-object body")
        return payload

    async def cids_for_name(self, name: str, *, word_search: bool = False) -> list[int]:
        """CIDs whose name index matches `name`. `word_search` widens to PubChem's word search."""
        params = {"name_type": "word"} if word_search else None
        payload = await self._request("compound/name/cids/JSON", data={"name": name}, params=params)
        return _identifier_list(payload)

    async def cids_for_smiles(self, smiles: str) -> list[int]:
        """CIDs for a structure, after PubChem standardizes the SMILES."""
        payload = await self._request("compound/smiles/cids/JSON", data={"smiles": smiles})
        return _identifier_list(payload)

    async def properties(self, cids: list[int]) -> list[dict[str, Any]]:
        """Property rows for `cids`, in PubChem's response order."""
        if not cids:
            return []
        joined = ",".join(str(cid) for cid in cids)
        payload = await self._request(
            f"compound/cid/property/{','.join(PROPERTY_NAMES)}/JSON", data={"cid": joined}
        )
        table = payload.get("PropertyTable")
        if not isinstance(table, dict):
            raise PubChemResponseError("property response is missing PropertyTable")
        rows = table.get("Properties")
        if not isinstance(rows, list):
            raise PubChemResponseError("property response is missing Properties")
        return [row for row in rows if isinstance(row, dict)]

    async def synonyms(self, cids: list[int]) -> dict[int, list[str]]:
        """Registered synonyms per CID. Absent CIDs simply have no entry."""
        if not cids:
            return {}
        joined = ",".join(str(cid) for cid in cids)
        payload = await self._request("compound/cid/synonyms/JSON", data={"cid": joined})
        information = payload.get("InformationList")
        if not isinstance(information, dict):
            raise PubChemResponseError("synonym response is missing InformationList")
        entries = information.get("Information")
        if not isinstance(entries, list):
            raise PubChemResponseError("synonym response is missing Information")

        result: dict[int, list[str]] = {}
        for entry in entries:
            if not isinstance(entry, dict):
                continue
            cid = entry.get("CID")
            names = entry.get("Synonym")
            if isinstance(cid, int) and isinstance(names, list):
                result[cid] = [str(name) for name in names]
        return result


def _identifier_list(payload: dict[str, Any]) -> list[int]:
    identifiers = payload.get("IdentifierList")
    if not isinstance(identifiers, dict):
        raise PubChemResponseError("response is missing IdentifierList")
    cids = identifiers.get("CID")
    if not isinstance(cids, list):
        raise PubChemResponseError("response is missing CID list")
    # A structure PubChem knows of but has no record for comes back as the sentinel CID 0.
    return [cid for cid in cids if isinstance(cid, int) and cid > 0]


def _fault_error(path: str, response: httpx.Response) -> PubChemRequestError:
    """Turn a PUG-REST error body into an exception carrying its `PUGREST.*` fault code."""
    code = ""
    message = ""
    try:
        body = response.json()
    except ValueError:
        body = None
    if isinstance(body, dict):
        fault = body.get("Fault")
        if isinstance(fault, dict):
            code = str(fault.get("Code", ""))
            message = str(fault.get("Message", ""))
    detail = f"{code}: {message}" if code else f"HTTP {response.status_code}"
    return PubChemRequestError(
        f"{path} failed ({detail})", status_code=response.status_code, code=code
    )
