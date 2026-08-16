from __future__ import annotations

from decimal import Decimal

from app.services.protocols.calculator import (
    MasterMixResult,
    RecalculationRequest,
    recalculate,
)

DILUTION_ENTRY: dict[str, object] = {
    "id": "primer-dilution",
    "step_id": "step-2",
    "dilution": {
        "stock_concentration": {"value": "100", "unit": "uM"},
        "final_concentration": {"value": "10", "unit": "uM"},
        "final_volume": {"value": "1", "unit": "mL"},
    },
}

MIX_ENTRY: dict[str, object] = {
    "id": "qpcr-mix",
    "step_id": "step-3",
    "master_mix": {
        "components": [
            {"name": "2x mix", "per_reaction_volume": {"value": "10", "unit": "uL"}},
            {"name": "Water", "per_reaction_volume": {"value": "8", "unit": "uL"}},
        ],
        "reactions": 24,
        "overage_percent": "0",
    },
}


def batch(**kwargs: object) -> RecalculationRequest:
    return RecalculationRequest.model_validate(kwargs)


def test_batch_scale_rescales_every_master_mix_but_not_dilutions() -> None:
    response = recalculate(batch(entries=[DILUTION_ENTRY, MIX_ENTRY], batch_scale=96))

    dilution, mix = response.outcomes
    assert dilution.result is not None
    assert dilution.result.stock_volume.value == Decimal("0.1")

    assert isinstance(mix.result, MasterMixResult)
    assert mix.result.reactions == 96
    assert mix.result.effective_reactions == Decimal("96")
    assert mix.result.total_volume.value == Decimal("1728")
    assert response.batch_scale == 96


def test_overage_override_applies_without_a_batch_scale() -> None:
    response = recalculate(batch(entries=[MIX_ENTRY], overage_percent="10"))

    mix = response.outcomes[0]
    assert isinstance(mix.result, MasterMixResult)
    assert mix.result.reactions == 24
    assert mix.result.overage_percent == Decimal("10")
    assert mix.result.total_volume.value == Decimal("475.2")


def test_entries_keep_their_own_scale_when_no_override_is_sent() -> None:
    response = recalculate(batch(entries=[MIX_ENTRY]))

    mix = response.outcomes[0]
    assert isinstance(mix.result, MasterMixResult)
    assert mix.result.reactions == 24
    assert mix.result.total_volume.value == Decimal("432")
    assert response.batch_scale is None


def test_one_bad_entry_does_not_lose_the_rest_of_the_protocol() -> None:
    """A half-edited field on one step must not blank out every other calculated value."""
    broken: dict[str, object] = {
        "id": "broken",
        "dilution": {
            "stock_concentration": {"value": "1", "unit": "mM"},
            "final_concentration": {"value": "10", "unit": "ug/mL"},
            "final_volume": {"value": "1", "unit": "mL"},
        },
    }
    response = recalculate(batch(entries=[broken, DILUTION_ENTRY]))

    failed, ok = response.outcomes
    assert failed.id == "broken"
    assert failed.result is None
    assert failed.error is not None
    assert "different kinds of concentration" in failed.error
    assert ok.result is not None


def test_entry_with_no_calculation_reports_an_error_for_that_entry_only() -> None:
    response = recalculate(batch(entries=[{"id": "empty"}, DILUTION_ENTRY]))

    assert response.outcomes[0].error is not None
    assert "exactly one calculation" in response.outcomes[0].error
    assert response.outcomes[1].error is None


def test_step_ids_are_echoed_so_the_frontend_can_place_results() -> None:
    response = recalculate(batch(entries=[DILUTION_ENTRY, MIX_ENTRY], batch_scale=12))

    assert [outcome.step_id for outcome in response.outcomes] == ["step-2", "step-3"]
    assert [outcome.id for outcome in response.outcomes] == ["primer-dilution", "qpcr-mix"]
