from __future__ import annotations

import pytest

from app.services.screening import (
    MAX_HEAVY_ATOMS,
    MAX_SMILES_LENGTH,
    InvalidStructureError,
    normalize_smiles,
    parse_structure,
)


class TestNormalizeSmiles:
    def test_trims_surrounding_whitespace(self) -> None:
        assert normalize_smiles("  CCO\n") == "CCO"

    @pytest.mark.parametrize("value", ["", "   ", "\n\t"])
    def test_rejects_empty_input(self, value: str) -> None:
        with pytest.raises(InvalidStructureError, match="must not be empty"):
            normalize_smiles(value)

    def test_rejects_non_string(self) -> None:
        with pytest.raises(InvalidStructureError, match="must be a string"):
            normalize_smiles(None)

    def test_rejects_input_over_the_length_bound(self) -> None:
        with pytest.raises(InvalidStructureError, match="at most 600 characters"):
            normalize_smiles("C" * (MAX_SMILES_LENGTH + 1))

    @pytest.mark.parametrize(
        "value",
        [
            "CCO CCO",  # two structures pasted together
            "CCO\nCCC",  # a newline-separated list
            "aspirin (acetylsalicylic acid)",  # a name, not a structure
            "CCO&q=1",  # query-string injection aimed at a downstream API
            "CCO<script>",
        ],
    )
    def test_rejects_characters_smiles_cannot_contain(self, value: str) -> None:
        with pytest.raises(InvalidStructureError, match="not valid in SMILES"):
            normalize_smiles(value)


class TestParseStructure:
    def test_returns_canonical_identity_for_a_valid_structure(self) -> None:
        structure = parse_structure("  CC(=O)OC1=CC=CC=C1C(=O)O  ")

        assert structure.input_smiles == "CC(=O)OC1=CC=CC=C1C(=O)O"
        assert structure.canonical_smiles == "CC(=O)Oc1ccccc1C(=O)O"
        assert structure.molecular_formula == "C9H8O4"
        assert structure.heavy_atom_count == 13
        assert structure.scaffold_hint == "C9H8O4 (CC(=O)Oc1ccccc1C(=O)O)"
        # InChI is a build-time option in RDKit, so only its shape is asserted.
        assert structure.inchikey == "" or len(structure.inchikey) == 27

    @pytest.mark.parametrize(
        "value",
        [
            "c1ccccc",  # unclosed aromatic ring
            "C(C)(C)(C)(C)C",  # pentavalent carbon
            "[Xx]",  # not an element
            "C1CC",  # unclosed ring bond
        ],
    )
    def test_rejects_structures_rdkit_cannot_sanitize(self, value: str) -> None:
        with pytest.raises(InvalidStructureError):
            parse_structure(value)

    def test_rejects_a_structure_with_no_heavy_atoms(self) -> None:
        with pytest.raises(InvalidStructureError, match="no heavy atoms"):
            parse_structure("[H][H]")

    def test_rejects_structures_past_the_heavy_atom_bound(self) -> None:
        polymer = "C" * (MAX_HEAVY_ATOMS + 1)

        with pytest.raises(InvalidStructureError, match="limited to 200-atom"):
            parse_structure(polymer)

    def test_accepts_a_structure_at_the_heavy_atom_bound(self) -> None:
        assert parse_structure("C" * MAX_HEAVY_ATOMS).heavy_atom_count == MAX_HEAVY_ATOMS
