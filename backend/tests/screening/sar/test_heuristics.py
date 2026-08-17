from __future__ import annotations

from app.services.screening import parse_structure
from app.services.screening.sar import (
    SUGGESTION_CAVEAT,
    SuggestionSource,
    profile_structure,
    suggest_from_rules,
)
from app.services.screening.sar.heuristics import MAX_SUGGESTIONS


def fired_keys(smiles: str) -> set[str]:
    """The titles of the heuristics that fire for `smiles`, keyed for readable assertions."""
    structure = parse_structure(smiles)
    profile = profile_structure(smiles)
    result = suggest_from_rules(structure.mol, profile)
    return {suggestion.title for suggestion in result.suggestions}


def test_aryl_methyl_triggers_the_halogen_swap() -> None:
    # Toluene: the only liability present is the benzylic methyl.
    titles = fired_keys("Cc1ccccc1")

    assert "Swap the aryl methyl for fluorine or chlorine" in titles


def test_alkyl_ester_triggers_the_bioisostere_suggestion() -> None:
    # Ethyl benzoate.
    assert "Replace the ester with an amide or other stable bioisostere" in fired_keys(
        "CCOC(=O)c1ccccc1"
    )


def test_carboxylic_acid_is_not_treated_as_an_ester() -> None:
    assert "Replace the ester with an amide or other stable bioisostere" not in fired_keys(
        "OC(=O)c1ccccc1"
    )


def test_primary_aniline_triggers_capping_and_a_capped_aniline_does_not() -> None:
    assert "Cap the primary aromatic amine" in fired_keys("Nc1ccccc1")
    # Acetanilide: the nitrogen is already acylated.
    assert "Cap the primary aromatic amine" not in fired_keys("CC(=O)Nc1ccccc1")


def test_nitro_group_triggers_replacement() -> None:
    assert "Replace the nitro group" in fired_keys("[O-][N+](=O)c1ccccc1")


def test_phenol_triggers_masking_but_an_aryl_ether_does_not() -> None:
    assert "Mask or bioisosterically replace the phenol" in fired_keys("Oc1ccccc1")
    assert "Mask or bioisosterically replace the phenol" not in fired_keys("COc1ccccc1")


def test_lipophilicity_heuristic_needs_both_a_phenyl_and_a_high_clogp() -> None:
    # Ibuprofen: unsubstituted phenyl absent (para-disubstituted) and cLogP ~3.1.
    assert "Lower lipophilicity by swapping a phenyl for an azine" not in fired_keys(
        "CC(C)Cc1ccc(C(C)C(=O)O)cc1"
    )
    # Biphenyl-bearing lipophile: monosubstituted phenyl present and cLogP > 4.
    assert "Lower lipophilicity by swapping a phenyl for an azine" in fired_keys(
        "c1ccc(-c2ccc(CCCCCC)cc2)cc1"
    )


def test_descriptor_only_heuristics_fire_on_thresholds() -> None:
    # A long flexible diamide: 12 rotatable bonds and MW > 500.
    flexible = "c1ccccc1C(=O)NCCCCCCCCCCCCNC(=O)c1ccccc1"
    profile = profile_structure(flexible)
    titles = fired_keys(flexible)

    assert profile.value_of("rotatable_bonds") is not None
    assert profile.value_of("rotatable_bonds") > 10
    assert "Restrict the flexible linker" in titles
    assert ("Trim molecular weight before elaborating further" in titles) is (
        profile.value_of("molecular_weight") > 500
    )


def test_a_clean_fragment_gets_an_explicit_no_suggestion_entry() -> None:
    structure = parse_structure("c1ccccc1")
    result = suggest_from_rules(structure.mol, profile_structure("c1ccccc1"))

    assert len(result.suggestions) == 1
    only = result.suggestions[0]
    assert only.title == "No heuristic fired for this structure"
    assert "not a statement that the structure is optimal" in only.rationale
    assert "carries no information" in only.risk


def test_every_set_is_labelled_unvalidated_and_names_its_generator() -> None:
    structure = parse_structure("Cc1ccccc1")
    result = suggest_from_rules(structure.mol, profile_structure("Cc1ccccc1"))

    assert result.source is SuggestionSource.RULES
    assert result.generator == "rule-based medicinal-chemistry heuristics (deterministic)"
    assert result.validated is False
    assert result.caveat == SUGGESTION_CAVEAT
    assert "chemist review" in result.caveat
    assert result.model == ""


def test_suggestions_are_bounded_and_carry_a_risk_for_every_entry() -> None:
    # Deliberately liability-rich: nitro, phenol, aniline, ester and an aryl methyl.
    busy = "CCOC(=O)c1cc(C)c(O)c([N+](=O)[O-])c1Nc1ccccc1N"
    structure = parse_structure(busy)
    result = suggest_from_rules(structure.mol, profile_structure(busy))

    assert 1 <= len(result.suggestions) <= MAX_SUGGESTIONS
    assert all(suggestion.risk for suggestion in result.suggestions)
    assert all(suggestion.transformation for suggestion in result.suggestions)


def test_no_suggestion_claims_a_numeric_prediction() -> None:
    from app.services.screening.sar.heuristics import HEURISTICS

    for heuristic in HEURISTICS:
        text = " ".join(
            [
                heuristic.suggestion.expected_effect,
                heuristic.suggestion.rationale,
            ]
        ).lower()
        for banned in ("ic50", "pki", "kd =", "nm potency", "% bioavailab"):
            assert banned not in text, heuristic.key
