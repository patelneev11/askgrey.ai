from __future__ import annotations

import pytest

from app.services.pubchem.client import PugRestClient
from app.services.pubchem.errors import CompoundNotFoundError, InvalidIdentifierError
from app.services.pubchem.models import IdentifierKind, MatchQuality
from app.services.pubchem.service import PubChemService
from app.services.rate_limit import RateLimiter
from tests.pubchem.conftest import (
    Handler,
    RecordingTransport,
    fault_response,
    fixture_response,
    json_response,
    sequence,
)

ASPIRIN_SMILES = "CC(=O)Oc1ccccc1C(=O)O"

NAME_CIDS = "compound/name/cids/JSON"
SMILES_CIDS = "compound/smiles/cids/JSON"
PROPERTIES = (
    "compound/cid/property/"
    "Title,MolecularFormula,MolecularWeight,SMILES,ConnectivitySMILES,IUPACName,XLogP/JSON"
)
SYNONYMS = "compound/cid/synonyms/JSON"

NOT_FOUND = fault_response("PUGREST.NotFound", 404)
BAD_REQUEST = fault_response("PUGREST.BadRequest", 400)


def build_service(transport: RecordingTransport, max_candidates: int = 10) -> PubChemService:
    return PubChemService(
        client=PugRestClient(transport=transport, rate_limiter=RateLimiter(1000.0)),
        max_candidates=max_candidates,
    )


def aspirin_records() -> dict[str, Handler]:
    return {
        PROPERTIES: fixture_response("properties_aspirin.json"),
        SYNONYMS: fixture_response("synonyms_aspirin.json"),
    }


def glucose_records() -> dict[str, Handler]:
    return {
        PROPERTIES: fixture_response("properties_glucose_candidates.json"),
        SYNONYMS: fixture_response("synonyms_glucose_candidates.json"),
    }


class TestSmilesLookup:
    @pytest.mark.asyncio
    async def test_resolves_structure_without_touching_the_name_endpoint(self) -> None:
        transport = RecordingTransport(
            {SMILES_CIDS: fixture_response("cids_smiles_aspirin.json"), **aspirin_records()}
        )

        result = await build_service(transport).lookup(ASPIRIN_SMILES)

        assert result.resolved_as is IdentifierKind.SMILES
        assert result.ambiguous is False
        assert result.match is not None
        assert result.match.cid == 2244
        assert result.match.molecular_formula == "C9H8O4"
        assert result.match.molecular_weight == pytest.approx(180.16)
        assert result.match.xlogp == pytest.approx(1.2)
        assert result.match.synonyms[0] == "aspirin"
        assert transport.bodies_for(SMILES_CIDS) == [{"smiles": [ASPIRIN_SMILES]}]
        assert transport.bodies_for(NAME_CIDS) == []

    @pytest.mark.asyncio
    async def test_explicit_kind_skips_sniffing(self) -> None:
        transport = RecordingTransport(
            {SMILES_CIDS: fixture_response("cids_smiles_aspirin.json"), **aspirin_records()}
        )

        result = await build_service(transport).lookup("water", kind=IdentifierKind.SMILES)

        assert result.resolved_as is IdentifierKind.SMILES
        assert transport.bodies_for(SMILES_CIDS) == [{"smiles": ["water"]}]
        assert transport.bodies_for(NAME_CIDS) == []


class TestNameLookup:
    @pytest.mark.asyncio
    async def test_exact_name_match(self) -> None:
        transport = RecordingTransport(
            {NAME_CIDS: fixture_response("cids_name_aspirin.json"), **aspirin_records()}
        )

        result = await build_service(transport).lookup("aspirin")

        assert result.resolved_as is IdentifierKind.NAME
        assert result.ambiguous is False
        assert result.total_matches == 1
        assert result.candidates[0].quality is MatchQuality.EXACT
        assert result.match is not None
        assert result.match.iupac_name == "2-acetyloxybenzoic acid"
        # The exact endpoint answered, so the looser word search is never attempted.
        assert transport.queries_for(NAME_CIDS) == [{}]

    @pytest.mark.asyncio
    async def test_synonym_lookup(self) -> None:
        transport = RecordingTransport(
            {NAME_CIDS: fixture_response("cids_name_aspirin.json"), **aspirin_records()}
        )

        result = await build_service(transport).lookup("acetylsalicylic acid")

        assert result.match is not None
        assert result.match.cid == 2244
        assert result.candidates[0].quality is MatchQuality.SYNONYM

    @pytest.mark.asyncio
    async def test_name_that_sniffs_as_a_structure_still_resolves(self) -> None:
        transport = RecordingTransport(
            {
                SMILES_CIDS: NOT_FOUND,
                NAME_CIDS: fixture_response("cids_name_aspirin.json"),
                **aspirin_records(),
            }
        )

        # No spaces and no long word, so the sniffer routes it to the structure endpoint first.
        result = await build_service(transport).lookup("C6H12O6")

        assert result.resolved_as is IdentifierKind.NAME
        assert result.match is not None
        assert result.match.cid == 2244


class TestAmbiguousNames:
    @pytest.mark.asyncio
    async def test_returns_ranked_candidates_instead_of_failing(self) -> None:
        transport = RecordingTransport(
            {
                NAME_CIDS: sequence(NOT_FOUND, fixture_response("cids_name_glucose_word.json")),
                **glucose_records(),
            }
        )

        result = await build_service(transport).lookup("glucose")

        assert result.ambiguous is True
        assert result.total_matches == 4
        assert [candidate.rank for candidate in result.candidates] == [1, 2, 3, 4]
        # PubChem lists a trisaccharide first, but only CID 5793 is literally named "glucose".
        assert result.match is not None
        assert result.match.cid == 5793
        assert result.candidates[0].quality is MatchQuality.SYNONYM
        assert result.candidates[1].quality is MatchQuality.WORD
        assert result.candidates[0].score > result.candidates[1].score
        assert any("word-search" in warning for warning in result.warnings)
        assert transport.queries_for(NAME_CIDS) == [{}, {"name_type": ["word"]}]

    @pytest.mark.asyncio
    async def test_candidate_list_is_capped_and_the_cap_is_reported(self) -> None:
        transport = RecordingTransport(
            {
                NAME_CIDS: sequence(NOT_FOUND, fixture_response("cids_name_glucose_word.json")),
                **glucose_records(),
            }
        )

        result = await build_service(transport, max_candidates=2).lookup("glucose")

        assert result.total_matches == 4
        assert len(result.candidates) == 2
        assert any("showing the top" in warning for warning in result.warnings)
        assert transport.bodies_for(PROPERTIES) == [{"cid": ["53477858,5793"]}]


class TestInvalidInput:
    @pytest.mark.asyncio
    async def test_empty_identifier(self) -> None:
        with pytest.raises(InvalidIdentifierError):
            await build_service(RecordingTransport({})).lookup("   ")

    @pytest.mark.asyncio
    async def test_overlong_identifier(self) -> None:
        with pytest.raises(InvalidIdentifierError):
            await build_service(RecordingTransport({})).lookup("C" * 4001)

    @pytest.mark.asyncio
    async def test_unstandardizable_structure_reports_no_match(self) -> None:
        transport = RecordingTransport({SMILES_CIDS: BAD_REQUEST, NAME_CIDS: NOT_FOUND})

        with pytest.raises(CompoundNotFoundError):
            await build_service(transport).lookup("not_a_smiles((")

    @pytest.mark.asyncio
    async def test_unknown_name(self) -> None:
        transport = RecordingTransport({NAME_CIDS: NOT_FOUND, SMILES_CIDS: NOT_FOUND})

        with pytest.raises(CompoundNotFoundError):
            await build_service(transport).lookup("notarealchemicalxyz")

    @pytest.mark.asyncio
    async def test_sentinel_cid_zero_is_not_a_match(self) -> None:
        # A structure PubChem can standardize but has no record for comes back as CID 0.
        transport = RecordingTransport(
            {
                SMILES_CIDS: lambda _body: json_response({"IdentifierList": {"CID": [0]}}),
                NAME_CIDS: NOT_FOUND,
            }
        )

        with pytest.raises(CompoundNotFoundError):
            await build_service(transport).lookup(ASPIRIN_SMILES)
