from __future__ import annotations

import pytest

from app.services.screening import InvalidStructureError
from app.services.screening.sar import profile_structure
from tests.screening.sar.reference import REFERENCE_COMPOUNDS, ReferenceCompound

# PubChem publishes molecular weight to two decimals and TPSA to three significant figures,
# so the tolerances are the reference's precision rather than a margin for error.
MW_TOLERANCE = 0.05
TPSA_TOLERANCE = 1.0
# Wildman-Crippen (what RDKit computes) and XLogP3 (what PubChem publishes) are different
# estimators of the same physical quantity, and neither is a measured log P. This bound says
# they agree to about one and a half log units across the reference set; it is not a claim that
# either value is correct.
CLOGP_VS_XLOGP3_BOUND = 1.5


def ids(compounds: tuple[ReferenceCompound, ...]) -> list[str]:
    return [compound.name for compound in compounds]


@pytest.mark.parametrize("compound", REFERENCE_COMPOUNDS, ids=ids(REFERENCE_COMPOUNDS))
def test_identity_and_reference_descriptors(compound: ReferenceCompound) -> None:
    profile = profile_structure(compound.smiles)

    assert profile.molecular_formula == compound.formula
    assert profile.value_of("molecular_weight") == pytest.approx(
        compound.pubchem_mw, abs=MW_TOLERANCE
    )
    assert profile.value_of("hbd") == compound.pubchem_hbd
    assert profile.value_of("aromatic_rings") == compound.aromatic_rings

    expected_tpsa = (
        compound.rdkit_tpsa if compound.rdkit_tpsa is not None else compound.pubchem_tpsa
    )
    assert profile.value_of("tpsa") == pytest.approx(expected_tpsa, abs=TPSA_TOLERANCE)


@pytest.mark.parametrize("compound", REFERENCE_COMPOUNDS, ids=ids(REFERENCE_COMPOUNDS))
def test_acceptor_and_rotatable_bond_definitions(compound: ReferenceCompound) -> None:
    """
    Where RDKit's Lipinski definitions differ from PubChem's, the difference is asserted.

    The compounds carrying an `rdkit_*` override are locked to RDKit's value with the reason
    recorded in `reference.py`; everything else must agree with PubChem exactly.
    """
    profile = profile_structure(compound.smiles)

    expected_hba = compound.rdkit_hba if compound.rdkit_hba is not None else compound.pubchem_hba
    expected_rotatable = (
        compound.rdkit_rotatable_bonds
        if compound.rdkit_rotatable_bonds is not None
        else compound.pubchem_rotatable_bonds
    )
    assert profile.value_of("hba") == expected_hba
    assert profile.value_of("rotatable_bonds") == expected_rotatable

    if compound.rdkit_hba is not None or compound.rdkit_rotatable_bonds is not None:
        assert compound.divergence, "a definitional divergence must record why it exists"


@pytest.mark.parametrize("compound", REFERENCE_COMPOUNDS, ids=ids(REFERENCE_COMPOUNDS))
def test_clogp_tracks_published_xlogp3_within_a_stated_band(
    compound: ReferenceCompound,
) -> None:
    profile = profile_structure(compound.smiles)
    clogp = profile.value_of("logp")

    assert clogp is not None
    assert abs(clogp - compound.pubchem_xlogp3) <= CLOGP_VS_XLOGP3_BOUND


def test_clogp_ranks_the_reference_set_the_same_way_xlogp3_does() -> None:
    """
    Agreement that matters for screening is ordering, not absolute value.

    Pairs whose published log P differ by less than half a unit are excluded: the two estimators
    are not precise enough for their relative order to mean anything there.
    """
    computed = {
        compound.name: profile_structure(compound.smiles).value_of("logp")
        for compound in REFERENCE_COMPOUNDS
    }

    comparable = 0
    concordant = 0
    for first in REFERENCE_COMPOUNDS:
        for second in REFERENCE_COMPOUNDS:
            if first.name >= second.name:
                continue
            published_gap = first.pubchem_xlogp3 - second.pubchem_xlogp3
            if abs(published_gap) < 0.5:
                continue
            comparable += 1
            first_value = computed[first.name]
            second_value = computed[second.name]
            assert first_value is not None and second_value is not None
            if (first_value - second_value) * published_gap > 0:
                concordant += 1

    assert comparable >= 30
    assert concordant / comparable >= 0.9


def test_descriptors_carry_the_function_that_produced_them() -> None:
    profile = profile_structure("CC(=O)Oc1ccccc1C(=O)O")

    for descriptor in profile.descriptors:
        assert descriptor.method.startswith("RDKit ")
    assert "RDKit" in profile.basis
    assert "not measured" in profile.caveat


def test_rule_sets_flag_lipinski_and_veber_violations() -> None:
    atorvastatin = next(
        compound for compound in REFERENCE_COMPOUNDS if compound.name == "atorvastatin"
    )
    profile = profile_structure(atorvastatin.smiles)
    rule_sets = {rule_set.key: rule_set for rule_set in profile.rule_sets}

    lipinski = rule_sets["lipinski"]
    assert not lipinski.compliant
    failed = {check.key for check in lipinski.checks if not check.passed}
    # MW 558.6 and Wildman-Crippen LogP 6.3 both breach the Rule of Five.
    assert failed == {"molecular_weight", "logp"}
    assert lipinski.violations == 2
    assert "Lipinski" in lipinski.citation

    veber = rule_sets["veber"]
    assert not veber.compliant
    assert {check.key for check in veber.checks if not check.passed} == {"rotatable_bonds"}


def test_small_orals_pass_both_rule_sets() -> None:
    for name in ("aspirin", "ibuprofen", "acetaminophen", "caffeine", "diazepam"):
        compound = next(item for item in REFERENCE_COMPOUNDS if item.name == name)
        profile = profile_structure(compound.smiles)

        assert all(rule_set.compliant for rule_set in profile.rule_sets), name


def test_binding_affinity_is_reported_unavailable_rather_than_estimated() -> None:
    profile = profile_structure("CC(=O)Oc1ccccc1C(=O)O")

    keys = {descriptor.key for descriptor in profile.descriptors}
    assert not keys & {"binding_affinity", "affinity", "pki", "kd", "ic50"}

    affinity = next(item for item in profile.unavailable if item.key == "binding_affinity")
    assert affinity.available is False
    assert "docking" in affinity.reason
    assert "target structure" in affinity.requires


def test_canonicalization_makes_equivalent_inputs_identical() -> None:
    kekulized = profile_structure("C1=CC=CC=C1C(=O)O")
    aromatic = profile_structure("OC(=O)c1ccccc1")

    assert kekulized.canonical_smiles == aromatic.canonical_smiles
    assert kekulized.value_of("molecular_weight") == aromatic.value_of("molecular_weight")


def test_malformed_structures_raise_instead_of_producing_numbers() -> None:
    for value in ("", "   ", "not a molecule", "c1ccccc", "C(C)(C)(C)(C)C", "[Xx]"):
        with pytest.raises(InvalidStructureError):
            profile_structure(value)
