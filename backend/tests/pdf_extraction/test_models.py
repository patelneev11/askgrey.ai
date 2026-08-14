from __future__ import annotations

import pytest

from app.services.pdf_extraction import BoundingBox, ExtractionField, fields_from_goal


def test_goal_splits_into_stable_columns() -> None:
    fields = fields_from_goal("sample size, dosing regimen, primary efficacy endpoint")

    assert fields == [
        ExtractionField(key="sample_size", label="sample size"),
        ExtractionField(key="dosing_regimen", label="dosing regimen"),
        ExtractionField(key="primary_efficacy_endpoint", label="primary efficacy endpoint"),
    ]


@pytest.mark.parametrize(
    ("goal", "keys"),
    [
        (
            "sample sizes; dosage model\nprimary endpoint",
            ["sample_sizes", "dosage_model", "primary_endpoint"],
        ),
        ("Sample size,, sample size", ["sample_size"]),
        ("dose and duration", ["dose", "duration"]),
        ("   ", []),
        (",,,", []),
    ],
)
def test_goal_splitting_is_deterministic(goal: str, keys: list[str]) -> None:
    assert [field.key for field in fields_from_goal(goal)] == keys


def test_bounding_box_geometry() -> None:
    first = BoundingBox(x0=10, top=20, x1=30, bottom=40)
    second = BoundingBox(x0=5, top=25, x1=25, bottom=55)

    assert first.width == 20
    assert first.height == 20
    assert first.union(second) == BoundingBox(x0=5, top=20, x1=30, bottom=55)
