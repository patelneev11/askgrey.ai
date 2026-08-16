from __future__ import annotations

from app.core.config import Settings, get_settings
from app.services.rate_limit import RateLimiter

from .client import PugRestClient
from .errors import CompoundNotFoundError, InvalidIdentifierError, PubChemRequestError
from .models import (
    CompoundCandidate,
    CompoundLookup,
    CompoundRecord,
    IdentifierKind,
    MatchQuality,
)
from .parsing import looks_like_smiles, parse_property_row

MAX_IDENTIFIER_LENGTH = 4000
MAX_CANDIDATES = 25

NOT_FOUND_CODES = frozenset({"PUGREST.NotFound"})
BAD_INPUT_CODES = frozenset({"PUGREST.BadRequest"})

QUALITY_BASE_SCORE = {
    MatchQuality.EXACT: 1.0,
    MatchQuality.SYNONYM: 0.8,
    MatchQuality.WORD: 0.5,
}


class PubChemService:
    """
    The module's entry point: a SMILES, IUPAC name or synonym in, normalized compounds out.

    Each lookup is `resolve identifier -> CID(s) -> properties + synonyms -> rank`. An
    identifier that maps to several compounds is never an error: the result carries every
    candidate in rank order, with `match` set to the best one.
    """

    def __init__(self, *, client: PugRestClient, max_candidates: int = 10) -> None:
        self.client = client
        self.max_candidates = max(1, min(max_candidates, MAX_CANDIDATES))

    @classmethod
    def from_settings(cls, settings: Settings | None = None) -> PubChemService:
        settings = settings or get_settings()
        client = PugRestClient(
            timeout=settings.pubchem_timeout_seconds,
            base_url=settings.pubchem_base_url,
            rate_limiter=RateLimiter(settings.pubchem_rate_limit),
        )
        return cls(client=client, max_candidates=settings.pubchem_max_candidates)

    async def aclose(self) -> None:
        await self.client.aclose()

    async def lookup(
        self,
        identifier: str,
        *,
        kind: IdentifierKind | None = None,
        limit: int | None = None,
    ) -> CompoundLookup:
        """
        Resolve `identifier` and return the compound(s) it denotes.

        `kind` forces an interpretation; the default sniffs the string and falls back to the
        other endpoint if the first one draws a blank. Raises `CompoundNotFoundError` only when
        no interpretation matches anything.
        """
        query = identifier.strip()
        if not query:
            raise InvalidIdentifierError("identifier must not be empty")
        if len(query) > MAX_IDENTIFIER_LENGTH:
            raise InvalidIdentifierError(
                f"identifier must be at most {MAX_IDENTIFIER_LENGTH} characters"
            )

        warnings: list[str] = []
        resolved_as, quality, cids = await self._resolve(query, kind, warnings)
        if not cids:
            raise CompoundNotFoundError(f"no PubChem compound matches {query!r}")

        page_size = self.max_candidates if limit is None else max(1, min(limit, MAX_CANDIDATES))
        selected = cids[:page_size]
        if len(cids) > len(selected):
            warnings.append(
                f"{len(cids)} compounds matched; showing the top {len(selected)} by rank"
            )

        records = await self._records_for(selected)
        candidates = _rank(query, records, quality)

        return CompoundLookup(
            query=query,
            resolved_as=resolved_as,
            ambiguous=len(cids) > 1,
            total_matches=len(cids),
            match=candidates[0].compound if candidates else None,
            candidates=candidates,
            warnings=warnings,
        )

    async def records_for_cids(self, cids: list[int]) -> list[CompoundRecord]:
        """Normalized records for known CIDs, in the order PubChem returns them."""
        return await self._records_for(cids[:MAX_CANDIDATES])

    async def _resolve(
        self,
        query: str,
        kind: IdentifierKind | None,
        warnings: list[str],
    ) -> tuple[IdentifierKind, MatchQuality, list[int]]:
        if kind is IdentifierKind.CID:
            try:
                return IdentifierKind.CID, MatchQuality.EXACT, [int(query)]
            except ValueError as exc:
                raise InvalidIdentifierError(f"{query!r} is not a CID") from exc

        if kind is IdentifierKind.SMILES:
            return IdentifierKind.SMILES, MatchQuality.EXACT, await self._cids_for_smiles(query)

        if kind is IdentifierKind.NAME:
            return IdentifierKind.NAME, *await self._cids_for_name(query, warnings)

        # Auto: try the likelier endpoint first, then fall back to the other one. A name that
        # happens to look like a structure (and vice versa) costs one extra request, not a miss.
        if looks_like_smiles(query):
            cids = await self._cids_for_smiles(query)
            if cids:
                return IdentifierKind.SMILES, MatchQuality.EXACT, cids
            quality, name_cids = await self._cids_for_name(query, warnings)
            return IdentifierKind.NAME, quality, name_cids

        quality, cids = await self._cids_for_name(query, warnings)
        if cids:
            return IdentifierKind.NAME, quality, cids
        return IdentifierKind.SMILES, MatchQuality.EXACT, await self._cids_for_smiles(query)

    async def _cids_for_smiles(self, query: str) -> list[int]:
        try:
            return await self.client.cids_for_smiles(query)
        except PubChemRequestError as exc:
            if exc.code in NOT_FOUND_CODES:
                return []
            if exc.code in BAD_INPUT_CODES:
                # PubChem could not standardize the structure, so it is not valid SMILES.
                return []
            raise

    async def _cids_for_name(
        self, query: str, warnings: list[str]
    ) -> tuple[MatchQuality, list[int]]:
        try:
            cids = await self.client.cids_for_name(query)
        except PubChemRequestError as exc:
            if exc.code not in NOT_FOUND_CODES:
                raise
            cids = []
        if cids:
            # The name index matched a registered name or synonym; `_rank` promotes a candidate
            # to EXACT only when its own title or IUPAC name literally is the query.
            return MatchQuality.SYNONYM, cids

        # No indexed name matches, so widen to PubChem's word search. This is the main source
        # of ambiguity: a partial or trade name matches every compound mentioning the word.
        try:
            word_cids = await self.client.cids_for_name(query, word_search=True)
        except PubChemRequestError as exc:
            if exc.code in NOT_FOUND_CODES:
                return MatchQuality.WORD, []
            raise
        if word_cids:
            warnings.append(f"no exact name match for {query!r}; ranked word-search candidates")
        return MatchQuality.WORD, word_cids

    async def _records_for(self, cids: list[int]) -> list[CompoundRecord]:
        if not cids:
            return []
        rows = await self.client.properties(cids)
        synonyms = await self.client.synonyms(cids)
        records = [parse_property_row(row, synonyms.get(_row_cid(row), [])) for row in rows]
        # PUG-REST returns properties in ascending CID order, not the order they were requested.
        by_cid = {record.cid: record for record in records}
        ordered = [by_cid[cid] for cid in cids if cid in by_cid]
        return ordered or records


def _row_cid(row: dict[str, object]) -> int:
    value = row.get("CID")
    return int(value) if isinstance(value, int | float) else 0


def _rank(
    query: str, records: list[CompoundRecord], lookup_quality: MatchQuality
) -> list[CompoundCandidate]:
    """
    Order candidates by how directly they answer the identifier.

    PubChem's own ordering is the tie-breaker (it is roughly relevance), but a candidate whose
    title or registered synonym *is* the query outranks one that merely contains the word.
    """
    needle = query.casefold()
    scored: list[tuple[float, int, MatchQuality, CompoundRecord]] = []
    for position, record in enumerate(records):
        quality = lookup_quality
        if record.title.casefold() == needle or record.iupac_name.casefold() == needle:
            quality = MatchQuality.EXACT
        elif any(synonym.casefold() == needle for synonym in record.synonyms):
            quality = max(quality, MatchQuality.SYNONYM, key=_quality_rank)
        score = QUALITY_BASE_SCORE[quality] - position * 0.01
        scored.append((score, position, quality, record))

    scored.sort(key=lambda item: (-item[0], item[1]))
    return [
        CompoundCandidate(compound=record, rank=index + 1, quality=quality, score=round(score, 4))
        for index, (score, _position, quality, record) in enumerate(scored)
    ]


def _quality_rank(quality: MatchQuality) -> float:
    return QUALITY_BASE_SCORE[quality]
