"""What the model is shown when a tool result is too big for one turn.

The property under test is not "the payload is small" but "the payload still contains real records
and says how many it dropped". A model told only that a result was too large answers from memory,
and an invented NCT id passes every format and link check a reviewer would run.
"""

from __future__ import annotations

import json

from app.services.chat.agent import MAX_DETAIL_CHARS, _bounded, _tool_result_block
from app.services.chat.models import ToolStep


def trial(index: int) -> dict[str, object]:
    return {
        "nct_id": f"NCT{10_000_000 + index}",
        "title": "A study of something " + "x" * 400,
        "status": "COMPLETED",
        "sponsor": "Sponsor " + "y" * 200,
    }


def test_a_payload_within_the_ceiling_is_untouched() -> None:
    detail = {"trials": [trial(1)], "total_count": 1}
    assert _bounded(detail) == detail


def test_an_oversized_search_keeps_records_and_its_metadata() -> None:
    trials = [trial(index) for index in range(60)]
    bounded = _bounded({"trials": trials, "total_count": 900, "query": "ziprasidone"})

    assert isinstance(bounded, dict)
    kept = bounded["trials"]
    assert isinstance(kept, list)
    assert kept, "records must survive: a stub payload is what invites invented identifiers"
    assert kept == trials[: len(kept)]
    # The metadata the answer needs is not what gets dropped.
    assert bounded["total_count"] == 900
    assert bounded["query"] == "ziprasidone"
    notice = bounded["truncated"]
    assert isinstance(notice, dict)
    assert notice["records_sent_to_you"] == len(kept)
    assert notice["records_the_tool_returned"] == 60
    assert notice["cut_field"] == "trials"
    # The note has to say the missing records were not delivered: terse counts alone were read as a
    # display detail, and the answer then claimed all 60 had arrived.
    assert "you do not have them" in str(notice["note"])
    assert f"{len(kept)} of 60" in str(notice["note"])
    assert len(json.dumps(bounded, separators=(",", ":"))) <= MAX_DETAIL_CHARS


def test_an_oversized_list_becomes_records_with_a_count() -> None:
    bounded = _bounded([trial(index) for index in range(60)])

    assert isinstance(bounded, dict)
    records = bounded["records"]
    assert isinstance(records, list)
    assert records
    notice = bounded["truncated"]
    assert isinstance(notice, dict)
    assert notice["records_sent_to_you"] == len(records)
    assert notice["records_the_tool_returned"] == 60
    assert len(json.dumps(bounded, separators=(",", ":"))) <= MAX_DETAIL_CHARS


def test_a_payload_with_no_records_to_drop_is_cut_and_says_so() -> None:
    bounded = _bounded({"text": "z" * (MAX_DETAIL_CHARS * 2)})

    assert isinstance(bounded, dict)
    assert "partial_json" in bounded
    notice = bounded["truncated"]
    assert isinstance(notice, dict)
    assert "not sent to you" in str(notice["note"])
    assert len(json.dumps(bounded, separators=(",", ":"))) <= MAX_DETAIL_CHARS


def test_the_block_sent_back_to_the_model_carries_the_bounded_detail() -> None:
    detail = _bounded({"trials": [trial(index) for index in range(60)], "total_count": 60})
    step = ToolStep(
        id="toolu_1",
        tool="search_clinical_trials",
        title="Trial search",
        summary="60 trial(s) returned of 60 matched",
        detail=detail,
    )
    block = _tool_result_block(step)
    content = block["content"]

    assert isinstance(content, str)
    assert "NCT10000000" in content, "the first real identifier has to reach the model"
    assert '"truncated"' in content
