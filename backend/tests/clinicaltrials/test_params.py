from __future__ import annotations

from app.services.clinicaltrials.models import TrialPhase, TrialSearch, TrialStatus
from app.services.clinicaltrials.service import build_params


def test_single_filters_map_onto_their_api_facets() -> None:
    assert build_params(TrialSearch(sponsor="Pfizer"), page_size=5)["query.spons"] == "Pfizer"
    assert build_params(TrialSearch(condition="melanoma"), page_size=5)["query.cond"] == "melanoma"
    assert (
        build_params(TrialSearch(intervention="pembrolizumab"), page_size=5)["query.intr"]
        == "pembrolizumab"
    )
    assert (
        build_params(TrialSearch(phases=[TrialPhase.PHASE3]), page_size=5)["filter.advanced"]
        == "AREA[Phase]PHASE3"
    )
    assert (
        build_params(TrialSearch(statuses=[TrialStatus.RECRUITING]), page_size=5)[
            "filter.overallStatus"
        ]
        == "RECRUITING"
    )


def test_multiple_phases_and_statuses_are_or_ed() -> None:
    params = build_params(
        TrialSearch(
            phases=[TrialPhase.PHASE2, TrialPhase.PHASE3],
            statuses=[TrialStatus.RECRUITING, TrialStatus.COMPLETED],
        ),
        page_size=5,
    )

    assert params["filter.advanced"] == "AREA[Phase](PHASE2 OR PHASE3)"
    assert params["filter.overallStatus"] == "RECRUITING,COMPLETED"
