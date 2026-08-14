from __future__ import annotations

from app.services.llm import strip_code_fence


def test_strips_a_code_fence_the_model_added_anyway() -> None:
    assert strip_code_fence('```json\n{"a": 1}\n```') == '{"a": 1}'
    assert strip_code_fence('  {"a": 1}  ') == '{"a": 1}'
