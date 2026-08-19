"""
The snapshot's age, and what the product says about it.

The reference data is read from the source documents by hand, so its only honest claim is when a
human last read them. These tests pin that claim: the age is computed rather than asserted, the
thresholds are the documented maintenance policy, and the shipped files are held to it so an aging
snapshot fails here instead of quietly presenting old expectations as current ones.
"""

from __future__ import annotations

import warnings
from datetime import date, timedelta

import pytest

from app.services.regulatory.guidelines import (
    SNAPSHOT_REVIEW_INTERVAL_DAYS,
    SNAPSHOT_STALE_AFTER_DAYS,
    GuidelineChecker,
    Jurisdiction,
    SnapshotFreshness,
    SnapshotStatus,
    assess_freshness,
    load_reference_library,
    oldest,
)

RETRIEVED = date(2026, 1, 1)


def at(days: int) -> SnapshotFreshness:
    return assess_freshness("2026-01-fda-1", RETRIEVED, RETRIEVED + timedelta(days=days))


def test_fresh_snapshot_reports_its_age_and_next_review() -> None:
    snapshot = at(10)

    assert snapshot.status is SnapshotStatus.CURRENT
    assert snapshot.age_days == 10
    assert snapshot.review_due_on == date(2026, 4, 1)
    assert snapshot.stale_on == date(2026, 6, 30)
    assert "10 days ago" in snapshot.message
    # The wording must not let "current" be read as "complete" or "legally in force".
    assert "not a statement that the data is complete or legally current" in snapshot.message


@pytest.mark.parametrize(
    ("days", "status"),
    [
        (SNAPSHOT_REVIEW_INTERVAL_DAYS - 1, SnapshotStatus.CURRENT),
        (SNAPSHOT_REVIEW_INTERVAL_DAYS, SnapshotStatus.REVIEW_DUE),
        (SNAPSHOT_STALE_AFTER_DAYS - 1, SnapshotStatus.REVIEW_DUE),
        (SNAPSHOT_STALE_AFTER_DAYS, SnapshotStatus.STALE),
        (SNAPSHOT_STALE_AFTER_DAYS + 400, SnapshotStatus.STALE),
    ],
)
def test_thresholds_are_the_documented_policy(days: int, status: SnapshotStatus) -> None:
    assert at(days).status is status


def test_stale_snapshot_says_findings_may_be_superseded_and_where_to_refresh() -> None:
    snapshot = at(SNAPSHOT_STALE_AFTER_DAYS + 5)

    assert "may reflect superseded guidance" in snapshot.message
    assert "README.md" in snapshot.update_procedure
    assert "Nothing is fetched at runtime" in snapshot.update_procedure


def test_a_future_retrieved_date_is_not_treated_as_fresh() -> None:
    snapshot = at(-30)

    assert snapshot.status is SnapshotStatus.REVIEW_DUE
    assert snapshot.age_days == 0
    assert "in the future" in snapshot.message


def test_oldest_picks_the_worst_aged_snapshot() -> None:
    assert oldest([at(5), at(200), at(90)]).age_days == 200
    assert oldest([]) is None


def _checker() -> GuidelineChecker:
    return GuidelineChecker.from_reference_files()


def test_reference_listing_carries_per_jurisdiction_and_overall_freshness() -> None:
    library = _checker().reference(today=date(2030, 1, 1))

    assert {entry.freshness.status for entry in library.jurisdictions} == {SnapshotStatus.STALE}
    assert library.snapshot is not None
    assert library.snapshot.age_days == max(
        entry.freshness.age_days for entry in library.jurisdictions
    )


def test_check_report_states_how_old_the_data_behind_it_is() -> None:
    checker = _checker()
    fresh = checker.check("3.2.S.4", "batch analyses " * 40, [Jurisdiction.FDA], today=None)
    dated = checker.check(
        "3.2.S.4",
        "batch analyses " * 40,
        [Jurisdiction.FDA, Jurisdiction.EMA],
        today=date(2030, 1, 1),
    )

    assert fresh.snapshot is not None
    assert dated.snapshot is not None
    assert dated.snapshot.status is SnapshotStatus.STALE
    assert dated.snapshot.age_days == max(entry.freshness.age_days for entry in dated.jurisdictions)
    for entry in dated.jurisdictions:
        assert entry.freshness.version == entry.version
        assert entry.freshness.retrieved == entry.retrieved


# The forcing function for the manual refresh: this fails when the shipped snapshot passes the
# documented staleness limit, so the data cannot age out of date without someone being told.
# Refresh per app/services/regulatory/guidelines/README.md, 'Refreshing the data'.
def test_shipped_snapshots_are_within_the_staleness_limit() -> None:
    today = date.today()
    stale = []
    for jurisdiction, dataset in load_reference_library().items():
        snapshot = assess_freshness(dataset.version, dataset.retrieved, today)
        if snapshot.status is SnapshotStatus.STALE:
            stale.append(f"{jurisdiction.value}: {snapshot.message}")
        elif snapshot.status is SnapshotStatus.REVIEW_DUE:
            warnings.warn(
                f"guideline snapshot review overdue - {jurisdiction.value}: {snapshot.message}",
                stacklevel=1,
            )
    assert not stale, "guideline reference data is past its staleness limit: " + "; ".join(stale)
