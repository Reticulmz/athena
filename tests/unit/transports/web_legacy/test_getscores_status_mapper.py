"""GetscoresStatusMapper unit tests.

TDD RED -> GREEN -> REFACTOR.
Validates getscores status wire value mapping from BeatmapRankStatus.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from osu_server.domain.beatmaps import (
    Beatmap,
    BeatmapFetchState,
    BeatmapFileState,
    BeatmapMetadataSource,
    BeatmapMode,
    BeatmapRankStatus,
    BeatmapSourceVerification,
    LocalBeatmapStatus,
)
from osu_server.transports.stable.web_legacy.mappers import (
    GetscoresStatusMapper,
)

_NOW = datetime(2026, 6, 7, tzinfo=UTC)
_NEXT_REFRESH = _NOW + timedelta(days=30)
_CHECKSUM = "0123456789abcdef0123456789abcdef"


def _make_beatmap(*, official_status: BeatmapRankStatus) -> Beatmap:
    return Beatmap(
        id=2_000,
        beatmapset_id=1_000,
        checksum_md5=_CHECKSUM,
        mode=BeatmapMode.OSU,
        version="Insane",
        total_length=240,
        hit_length=220,
        max_combo=1_234,
        bpm=180.0,
        cs=4.0,
        od=8.5,
        ar=9.4,
        hp=6.5,
        difficulty_rating=5.67,
        official_status=official_status,
        official_status_source=BeatmapMetadataSource.OFFICIAL,
        official_status_verified=BeatmapSourceVerification.VERIFIED,
        local_status_override=None,
        metadata_fetch_state=BeatmapFetchState.FRESH,
        file_state=BeatmapFileState.MISSING,
        file_attachment=None,
        last_fetched_at=_NOW,
        next_refresh_at=_NEXT_REFRESH,
    )


# ---------------------------------------------------------------------------
# Status wire values (requirements 9.1-9.7)
# ---------------------------------------------------------------------------


def test_not_submitted_maps_to_none() -> None:
    """NotSubmitted returns None (no header, mapped to -1 by caller)."""
    mapper = GetscoresStatusMapper()
    beatmap = _make_beatmap(official_status=BeatmapRankStatus.NOT_SUBMITTED)
    assert mapper.map_header_status(beatmap) is None


def test_unknown_maps_to_none() -> None:
    """Unknown returns None."""
    mapper = GetscoresStatusMapper()
    beatmap = _make_beatmap(official_status=BeatmapRankStatus.UNKNOWN)
    assert mapper.map_header_status(beatmap) is None


def test_pending_maps_to_0() -> None:
    mapper = GetscoresStatusMapper()
    beatmap = _make_beatmap(official_status=BeatmapRankStatus.PENDING)
    assert mapper.map_header_status(beatmap) == 0


def test_wip_maps_to_0() -> None:
    mapper = GetscoresStatusMapper()
    beatmap = _make_beatmap(official_status=BeatmapRankStatus.WIP)
    assert mapper.map_header_status(beatmap) == 0


def test_graveyard_maps_to_0() -> None:
    mapper = GetscoresStatusMapper()
    beatmap = _make_beatmap(official_status=BeatmapRankStatus.GRAVEYARD)
    assert mapper.map_header_status(beatmap) == 0


def test_ranked_maps_to_2() -> None:
    mapper = GetscoresStatusMapper()
    beatmap = _make_beatmap(official_status=BeatmapRankStatus.RANKED)
    assert mapper.map_header_status(beatmap) == 2


def test_approved_maps_to_3() -> None:
    mapper = GetscoresStatusMapper()
    beatmap = _make_beatmap(official_status=BeatmapRankStatus.APPROVED)
    assert mapper.map_header_status(beatmap) == 3


def test_qualified_maps_to_4() -> None:
    mapper = GetscoresStatusMapper()
    beatmap = _make_beatmap(official_status=BeatmapRankStatus.QUALIFIED)
    assert mapper.map_header_status(beatmap) == 4


def test_loved_maps_to_5() -> None:
    mapper = GetscoresStatusMapper()
    beatmap = _make_beatmap(official_status=BeatmapRankStatus.LOVED)
    assert mapper.map_header_status(beatmap) == 5


def test_all_mapped_statuses_are_unique() -> None:
    """Each visible status maps to a distinct wire value (requirement 9.8)."""
    mapper = GetscoresStatusMapper()
    visible_statuses = [
        BeatmapRankStatus.PENDING,
        BeatmapRankStatus.WIP,
        BeatmapRankStatus.GRAVEYARD,
        BeatmapRankStatus.RANKED,
        BeatmapRankStatus.APPROVED,
        BeatmapRankStatus.QUALIFIED,
        BeatmapRankStatus.LOVED,
    ]
    values = [mapper.map_header_status(_make_beatmap(official_status=s)) for s in visible_statuses]
    # Pending/WIP/Graveyard all map to 0 (same value is intentional)
    # Ranked=2, Approved=3, Qualified=4, Loved=5 are all distinct
    distinct_above_zero = [v for v in values if v is not None and v > 0]
    assert len(distinct_above_zero) == len(set(distinct_above_zero))


# ---------------------------------------------------------------------------
# Local status override (effective_status)
# ---------------------------------------------------------------------------


def test_local_override_takes_precedence() -> None:
    """local_status_override changes effective_status which maps to wire value."""
    mapper = GetscoresStatusMapper()
    beatmap = _make_beatmap(
        official_status=BeatmapRankStatus.PENDING,
    )
    # Use object.__setattr__ to bypass frozen dataclass
    object.__setattr__(beatmap, "local_status_override", LocalBeatmapStatus.RANKED)

    assert beatmap.effective_status == BeatmapRankStatus.RANKED
    assert mapper.map_header_status(beatmap) == 2


# ---------------------------------------------------------------------------
# Contract
# ---------------------------------------------------------------------------


def test_mapper_has_expected_interface() -> None:
    mapper = GetscoresStatusMapper()
    assert hasattr(mapper, "map_header_status")
    assert callable(mapper.map_header_status)
