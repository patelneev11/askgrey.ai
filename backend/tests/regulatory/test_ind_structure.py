from __future__ import annotations

from app.services.regulatory.ind import EvidenceKind, load_structure


def test_the_transcribed_tree_carries_its_version_and_its_sources() -> None:
    structure = load_structure()

    assert structure.version
    assert structure.retrieved
    ids = {source["id"] for source in structure.sources}
    assert {"M4Q(R1)", "M4S(R2)", "21 CFR 312.23"} <= ids
    assert all(source["url"].startswith("https://") for source in structure.sources)
    assert all(source["document_date"] for source in structure.sources)


def test_section_ids_are_unique_and_every_id_matches_its_module() -> None:
    structure = load_structure()

    ids = [section.id for section in structure.sections]
    assert len(ids) == len(set(ids))
    assert all(section.id.startswith(f"{section.module}.") for section in structure.sections)


def test_headings_transcribed_from_m4q_are_present_verbatim() -> None:
    structure = load_structure()

    substance = structure.get("3.2.S.4.4")
    assert substance is not None
    assert substance.title == "Batch Analyses (name, manufacturer)"
    assert structure.get("3.2.P.8.1") is not None
    assert structure.get("3.2.R") is not None


def test_headings_transcribed_from_m4s_are_present_verbatim() -> None:
    structure = load_structure()

    repeat_dose = structure.get("4.2.3.2")
    assert repeat_dose is not None
    assert repeat_dose.title.startswith("Repeat-Dose Toxicity (in order by species, by route,")
    assert structure.get("4.2.3.7.7") is not None


def test_a_section_with_no_evidence_mapping_is_not_offered_for_drafting() -> None:
    structure = load_structure()

    container = structure.get("3.2")
    literature = structure.get("3.3")
    assert container is not None and literature is not None
    assert container.draftable is False
    assert literature.draftable is False


def test_a_drafted_section_names_the_kinds_it_is_drafted_from() -> None:
    structure = load_structure()

    batches = structure.get("3.2.S.4.4")
    assert batches is not None
    assert batches.draftable is True
    assert set(batches.requires) == {EvidenceKind.BATCH, EvidenceKind.ASSAY_RESULT}


def test_facts_only_a_person_can_supply_are_inherited_down_module_four() -> None:
    structure = load_structure()

    section = structure.get("4.2.3.2")
    assert section is not None
    supplied = section.author_supplied()
    assert supplied
    assert any("312.23(a)(8)" in item for item in supplied)


def test_a_section_outside_the_author_supplied_map_inherits_nothing() -> None:
    structure = load_structure()

    section = structure.get("3.2.S.4.4")
    assert section is not None
    assert section.author_supplied() == ()


def test_every_section_traces_back_to_the_document_it_came_from() -> None:
    structure = load_structure()

    for section in structure.sections:
        reference = structure.source_reference(section)
        assert reference.startswith("M4Q(R1)" if section.module == "3" else "M4S(R2)")
        assert "https://" in reference


def test_an_unknown_section_id_is_not_invented() -> None:
    structure = load_structure()

    assert structure.get("3.2.S.9.9") is None
    assert structure.get("  3.2.S.4.4  ") is not None
