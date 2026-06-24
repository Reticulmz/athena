from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from osu_server.domain.beatmaps import (
    Beatmap,
    BeatmapFetchState,
    BeatmapFileState,
    BeatmapFreshnessPolicy,
    BeatmapMetadataSource,
    BeatmapRankStatus,
    BeatmapSourceVerification,
)

_NOW = datetime(2026, 6, 4, 12, tzinfo=UTC)
_LAST_FETCHED = _NOW - timedelta(hours=1)
_NEXT_REFRESH = _NOW + timedelta(days=1)
_CHECKSUM = "0123456789abcdef0123456789abcdef"


def _make_policy() -> BeatmapFreshnessPolicy:
    return BeatmapFreshnessPolicy(
        ranked_refresh_interval=timedelta(days=30),
        pending_refresh_interval=timedelta(days=1),
        graveyard_refresh_interval=timedelta(days=7),
        mirror_refresh_interval=timedelta(hours=6),
    )


def _make_beatmap(
    status: BeatmapRankStatus,
    *,
    source: BeatmapMetadataSource = BeatmapMetadataSource.OFFICIAL,
    last_fetched_at: datetime | None = _LAST_FETCHED,
    next_refresh_at: datetime | None = _NEXT_REFRESH,
    metadata_fetch_state: BeatmapFetchState = BeatmapFetchState.FRESH,
) -> Beatmap:
    return Beatmap(
        id=2_000,
        beatmapset_id=1_000,
        checksum_md5=_CHECKSUM,
        mode="osu",
        version="Another",
        total_length=240,
        hit_length=220,
        max_combo=1_234,
        bpm=180.0,
        cs=4.0,
        od=8.5,
        ar=9.4,
        hp=6.5,
        difficulty_rating=5.67,
        official_status=status,
        official_status_source=source,
        official_status_verified=(
            BeatmapSourceVerification.UNVERIFIED
            if source is BeatmapMetadataSource.MIRROR
            else BeatmapSourceVerification.VERIFIED
        ),
        local_status_override=None,
        metadata_fetch_state=metadata_fetch_state,
        file_state=BeatmapFileState.MISSING,
        file_attachment=None,
        last_fetched_at=last_fetched_at,
        next_refresh_at=next_refresh_at,
    )


@pytest.mark.parametrize(
    "status",
    [BeatmapRankStatus.RANKED, BeatmapRankStatus.APPROVED, BeatmapRankStatus.LOVED],
)
def test_stable_statuses_keep_future_next_refresh(status: BeatmapRankStatus) -> None:
    beatmap = _make_beatmap(status, next_refresh_at=_NOW + timedelta(days=5))
    decision = _make_policy().evaluate(beatmap, now=_NOW)

    assert decision.is_stale is False
    assert decision.should_refresh is False
    assert decision.next_refresh_at == _NOW + timedelta(days=5)
    assert decision.reason is None


@pytest.mark.parametrize(
    "status",
    [BeatmapRankStatus.RANKED, BeatmapRankStatus.APPROVED, BeatmapRankStatus.LOVED],
)
def test_stable_statuses_refresh_when_policy_marks_stale(status: BeatmapRankStatus) -> None:
    beatmap = _make_beatmap(status, next_refresh_at=_NOW - timedelta(seconds=1))
    decision = _make_policy().evaluate(beatmap, now=_NOW)

    assert decision.is_stale is True
    assert decision.should_refresh is True
    assert decision.reason == "stale"


@pytest.mark.parametrize(
    "status",
    [BeatmapRankStatus.QUALIFIED, BeatmapRankStatus.PENDING, BeatmapRankStatus.WIP],
)
def test_pending_like_statuses_use_short_refresh_interval(status: BeatmapRankStatus) -> None:
    beatmap = _make_beatmap(status, next_refresh_at=None)
    decision = _make_policy().evaluate(beatmap, now=_NOW)

    assert decision.next_refresh_at == _NOW - timedelta(hours=1) + timedelta(days=1)
    assert decision.is_stale is False
    assert decision.should_refresh is False


def test_pending_like_status_refreshes_when_interval_has_elapsed() -> None:
    beatmap = _make_beatmap(
        BeatmapRankStatus.PENDING,
        last_fetched_at=_NOW - timedelta(days=2),
        next_refresh_at=None,
    )
    decision = _make_policy().evaluate(beatmap, now=_NOW)

    assert decision.next_refresh_at == _NOW - timedelta(days=1)
    assert decision.is_stale is True
    assert decision.should_refresh is True
    assert decision.reason == "stale"


def test_next_refresh_placeholder_uses_policy_deadline() -> None:
    fetched_at = _NOW - timedelta(seconds=1)
    beatmap = _make_beatmap(
        BeatmapRankStatus.RANKED,
        last_fetched_at=fetched_at,
        next_refresh_at=fetched_at,
    )

    decision = _make_policy().evaluate(beatmap, now=_NOW)

    assert decision.next_refresh_at == fetched_at + timedelta(days=30)
    assert decision.is_stale is False
    assert decision.should_refresh is False


def test_mirror_sourced_next_refresh_placeholder_uses_mirror_interval() -> None:
    fetched_at = _NOW - timedelta(seconds=1)
    beatmap = _make_beatmap(
        BeatmapRankStatus.RANKED,
        source=BeatmapMetadataSource.MIRROR,
        last_fetched_at=fetched_at,
        next_refresh_at=fetched_at,
    )

    decision = _make_policy().evaluate(beatmap, now=_NOW)

    assert decision.next_refresh_at == fetched_at + timedelta(hours=6)
    assert decision.is_stale is False
    assert decision.should_refresh is False


def test_graveyard_status_uses_longer_refresh_interval_than_pending_like_statuses() -> None:
    policy = _make_policy()
    pending = policy.evaluate(
        _make_beatmap(BeatmapRankStatus.PENDING, next_refresh_at=None),
        now=_NOW,
    )
    graveyard = policy.evaluate(
        _make_beatmap(BeatmapRankStatus.GRAVEYARD, next_refresh_at=None),
        now=_NOW,
    )

    assert pending.next_refresh_at is not None
    assert graveyard.next_refresh_at is not None
    assert graveyard.next_refresh_at > pending.next_refresh_at
    assert graveyard.next_refresh_at == _NOW - timedelta(hours=1) + timedelta(days=7)


def test_mirror_sourced_records_request_official_refresh_on_later_access() -> None:
    beatmap = _make_beatmap(
        BeatmapRankStatus.RANKED,
        source=BeatmapMetadataSource.MIRROR,
        last_fetched_at=_NOW - timedelta(hours=1),
        next_refresh_at=_NOW + timedelta(days=5),
    )
    decision = _make_policy().evaluate(beatmap, now=_NOW, official_sources_available=True)

    assert decision.is_stale is True
    assert decision.should_refresh is True
    assert decision.requests_official_refresh is True
    assert decision.reason == "mirror_official_refresh_due"


def test_force_refresh_requests_refresh_even_when_record_is_fresh() -> None:
    beatmap = _make_beatmap(BeatmapRankStatus.RANKED, next_refresh_at=_NOW + timedelta(days=5))
    decision = _make_policy().evaluate(beatmap, now=_NOW, force_refresh=True)

    assert decision.is_stale is False
    assert decision.should_refresh is True
    assert decision.reason == "force_refresh"


def test_pending_and_failed_fetch_states_are_not_overwritten_by_freshness_policy() -> None:
    policy = _make_policy()
    pending = policy.evaluate(
        _make_beatmap(
            BeatmapRankStatus.PENDING,
            metadata_fetch_state=BeatmapFetchState.PENDING_FETCH,
        ),
        now=_NOW,
    )
    failed = policy.evaluate(
        _make_beatmap(BeatmapRankStatus.PENDING, metadata_fetch_state=BeatmapFetchState.FAILED),
        now=_NOW,
    )

    assert pending.should_refresh is False
    assert pending.reason == "pending_fetch"
    assert failed.should_refresh is True
    assert failed.reason == "failed_fetch"
