from __future__ import annotations

import pytest

from app.services.grants.errors import InvalidQueryError
from app.services.grants.matching import normalize_focus, render_candidates, tokenize
from tests.grants.conftest import opportunity


def test_normalize_focus_collapses_whitespace_and_caps_length() -> None:
    assert normalize_focus("  mRNA   vaccines\n for  oncology ") == "mRNA vaccines for oncology"
    with pytest.raises(InvalidQueryError):
        normalize_focus("x" * 2001)


def test_render_candidates_numbers_from_zero_and_includes_topics() -> None:
    on_topic = opportunity(
        "Pancreatic organoid models",
        topic_description="Patient-derived organoids for immunotherapy response.",
    )
    off_topic = opportunity("Rural broadband deployment", opportunity_id="2")

    rendered = render_candidates([on_topic, off_topic])

    assert rendered.startswith("[0] Pancreatic organoid models")
    assert "[1] Rural broadband" in rendered
    assert "Deadline: 2026-12-01" in rendered


def test_tokenize_drops_stopwords_and_keeps_hyphenated_compounds() -> None:
    assert tokenize("We are developing our patient-derived organoid platform") == [
        "patient-derived",
        "organoid",
    ]
