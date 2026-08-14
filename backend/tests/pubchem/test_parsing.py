from __future__ import annotations

import pytest

from app.services.pubchem.models import CompoundRecord
from app.services.pubchem.parsing import looks_like_smiles, parse_property_row
from app.services.records import RecordSource


class TestLooksLikeSmiles:
    @pytest.mark.parametrize(
        "value",
        [
            "CC(=O)Oc1ccccc1C(=O)O",
            "CCO",
            "C[C@H](N)C(=O)O",
            "[Na+].[Cl-]",
            "c1ccccc1",
        ],
    )
    def test_structures(self, value: str) -> None:
        assert looks_like_smiles(value) is True

    @pytest.mark.parametrize(
        "value",
        [
            "aspirin",
            "acetylsalicylic acid",
            "2-acetyloxybenzoic acid",
            "semaglutide",
            "",
            "   ",
        ],
    )
    def test_names(self, value: str) -> None:
        assert looks_like_smiles(value) is False


class TestParsePropertyRow:
    def test_normalizes_current_keys(self) -> None:
        record = parse_property_row(
            {
                "CID": 2244,
                "Title": "Aspirin",
                "MolecularFormula": "C9H8O4",
                "MolecularWeight": "180.16",
                "SMILES": "CC(=O)OC1=CC=CC=C1C(=O)O",
                "ConnectivitySMILES": "CC(=O)OC1=CC=CC=C1C(=O)O",
                "IUPACName": "2-acetyloxybenzoic acid",
                "XLogP": 1.2,
            },
            ["aspirin", "50-78-2"],
        )

        assert record.cid == 2244
        assert record.molecular_weight == pytest.approx(180.16)
        assert record.xlogp == pytest.approx(1.2)
        assert record.isomeric_smiles == "CC(=O)OC1=CC=CC=C1C(=O)O"
        assert record.synonyms == ["aspirin", "50-78-2"]
        assert record.pubchem_url == "https://pubchem.ncbi.nlm.nih.gov/compound/2244"

    def test_accepts_pre_2025_smiles_keys(self) -> None:
        record = parse_property_row(
            {
                "CID": 2244,
                "CanonicalSMILES": "CC(=O)OC1=CC=CC=C1C(=O)O",
                "IsomericSMILES": "CC(=O)OC1=CC=CC=C1C(=O)O",
            }
        )

        assert record.canonical_smiles == "CC(=O)OC1=CC=CC=C1C(=O)O"
        assert record.isomeric_smiles == "CC(=O)OC1=CC=CC=C1C(=O)O"

    def test_missing_and_unparseable_values_are_none(self) -> None:
        record = parse_property_row({"CID": 2244, "MolecularWeight": "n/a"})

        assert record.molecular_weight is None
        assert record.xlogp is None
        assert record.molecular_formula == ""


class TestSourceRecordProjection:
    def test_projects_into_shared_review_row(self) -> None:
        record = CompoundRecord(
            cid=2244,
            title="Aspirin",
            iupac_name="2-acetyloxybenzoic acid",
            molecular_formula="C9H8O4",
            molecular_weight=180.16,
            isomeric_smiles="CC(=O)OC1=CC=CC=C1C(=O)O",
            xlogp=1.2,
        )

        row = record.to_source_record()

        assert row.source is RecordSource.PUBCHEM
        assert row.record_id == "2244"
        assert row.title == "Aspirin"
        assert row.subtitle == "C9H8O4"
        assert row.url == "https://pubchem.ncbi.nlm.nih.gov/compound/2244"
        assert row.fields["MW"] == "180.16"
        assert row.fields["XLogP"] == "1.2"

    def test_display_name_falls_back_through_iupac_and_synonyms(self) -> None:
        assert CompoundRecord(cid=1, iupac_name="ethanol").display_name == "ethanol"
        assert CompoundRecord(cid=1, synonyms=["EtOH"]).display_name == "EtOH"
        assert CompoundRecord(cid=1).display_name == ""
