from __future__ import annotations

from dataclasses import FrozenInstanceError
from datetime import UTC, datetime, timedelta

import pytest

from osu_server.domain.beatmap import (
    Beatmap,
    BeatmapFetchState,
    BeatmapFileState,
    BeatmapMetadataSource,
    BeatmapRankStatus,
    BeatmapSet,
    BeatmapSourceVerification,
)
from osu_server.repositories.interfaces.beatmap_repository import (
    BeatmapFetchTarget,
)
from osu_server.repositories.memory.beatmap_repository import InMemoryBeatmapRepository
from osu_server.services.beatmap_eligibility import BeatmapEligibilityService
from osu_server.services.beatmap_freshness import BeatmapFreshnessPolicy
from osu_server.services.beatmap_mirror_service import (
    BeatmapMirrorService,
    BeatmapResolveOptions,
    BeatmapResolveResult,
    BeatmapSetResolveResult,
)

_NOW = datetime(2026, 6, 4, tzinfo=UTC)
_ONE_HOUR = timedelta(hours=1)
_THIRTY_DAYS = timedelta(days=30)

_DEFAULT_CHECKSUM = "0123456789abcdef0123456789abcdef"
_ALT_CHECKSUM = "abcdef0123456789abcdef0123456789"
_BEATMAP_ID = 2_000
_BEATMAPSET_ID = 1_000


# ---------------------------------------------------------------------------
# Test helpers -- domain object factories
# ---------------------------------------------------------------------------


def _make_beatmap(
    *,
    beatmap_id: int = _BEATMAP_ID,
    beatmapset_id: int = _BEATMAPSET_ID,
    checksum_md5: str = _DEFAULT_CHECKSUM,
    mode: str = "osu",
    version: str = "Another",
    official_status: BeatmapRankStatus = BeatmapRankStatus.RANKED,
    official_status_source: BeatmapMetadataSource = BeatmapMetadataSource.OFFICIAL,
    official_status_verified: BeatmapSourceVerification = BeatmapSourceVerification.VERIFIED,
    metadata_fetch_state: BeatmapFetchState = BeatmapFetchState.FRESH,
    file_state: BeatmapFileState = BeatmapFileState.MISSING,
    last_fetched_at: datetime | None = None,
    next_refresh_at: datetime | None = None,
) -> Beatmap:
    return Beatmap(
        id=beatmap_id,
        beatmapset_id=beatmapset_id,
        checksum_md5=checksum_md5,
        mode=mode,
        version=version,
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
        official_status_source=official_status_source,
        official_status_verified=official_status_verified,
        local_status_override=None,
        metadata_fetch_state=metadata_fetch_state,
        file_state=file_state,
        file_attachment=None,
        last_fetched_at=last_fetched_at,
        next_refresh_at=next_refresh_at,
    )


def _make_beatmapset(
    *,
    beatmapset_id: int = _BEATMAPSET_ID,
    artist: str = "Camellia",
    title: str = "Exit This Earth's Atomosphere",
    creator: str = "Realazy",
    official_status: BeatmapRankStatus = BeatmapRankStatus.RANKED,
    official_status_source: BeatmapMetadataSource = BeatmapMetadataSource.OFFICIAL,
    official_status_verified: BeatmapSourceVerification = BeatmapSourceVerification.VERIFIED,
    beatmaps: tuple[Beatmap, ...] | None = None,
    last_fetched_at: datetime | None = None,
    next_refresh_at: datetime | None = None,
) -> BeatmapSet:
    return BeatmapSet(
        id=beatmapset_id,
        artist=artist,
        title=title,
        creator=creator,
        artist_unicode=None,
        title_unicode=None,
        official_status=official_status,
        official_status_source=official_status_source,
        official_status_verified=official_status_verified,
        beatmaps=beatmaps or (),
        last_fetched_at=last_fetched_at,
        next_refresh_at=next_refresh_at,
    )


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def freshness_policy() -> BeatmapFreshnessPolicy:
    return BeatmapFreshnessPolicy(
        ranked_refresh_interval=_THIRTY_DAYS,
        pending_refresh_interval=_ONE_HOUR,
        graveyard_refresh_interval=_THIRTY_DAYS,
        mirror_refresh_interval=_ONE_HOUR,
    )


@pytest.fixture
def repo() -> InMemoryBeatmapRepository:
    return InMemoryBeatmapRepository()


@pytest.fixture
def service(
    repo: InMemoryBeatmapRepository,
    freshness_policy: BeatmapFreshnessPolicy,
) -> BeatmapMirrorService:
    return BeatmapMirrorService(
        repository=repo,
        eligibility_service=BeatmapEligibilityService(),
        freshness_policy=freshness_policy,
    )


# ---------------------------------------------------------------------------
# Tests: resolve_by_beatmap_id
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_resolve_by_beatmap_id_returns_cached_beatmap(
    service: BeatmapMirrorService,
    repo: InMemoryBeatmapRepository,
) -> None:
    beatmap = _make_beatmap(
        last_fetched_at=_NOW,
        next_refresh_at=_NOW + _THIRTY_DAYS,
    )
    beatmapset = _make_beatmapset(beatmaps=(beatmap,), last_fetched_at=_NOW)
    await repo.save_beatmapset_snapshot(beatmapset)

    result = await service.resolve_by_beatmap_id(_BEATMAP_ID)

    assert result.beatmap is not None
    assert result.beatmap.id == _BEATMAP_ID
    assert result.beatmapset is not None
    assert result.beatmapset.id == _BEATMAPSET_ID
    assert result.metadata_status is BeatmapFetchState.FRESH
    assert result.file_status is BeatmapFileState.MISSING
    assert result.source is BeatmapMetadataSource.OFFICIAL
    assert result.verified is True
    assert result.eligibility is not None
    assert result.eligibility.accepts_scores is True
    assert result.reason is None


@pytest.mark.asyncio
async def test_resolve_by_beatmap_id_unknown_returns_pending(
    service: BeatmapMirrorService,
) -> None:
    result = await service.resolve_by_beatmap_id(999)

    assert result.beatmap is None
    assert result.beatmapset is None
    assert result.eligibility is None
    assert result.metadata_status is BeatmapFetchState.PENDING_FETCH
    assert result.file_status is BeatmapFileState.MISSING
    assert result.source is None
    assert result.verified is False
    assert result.reason == "unsolicited"


@pytest.mark.asyncio
async def test_resolve_by_beatmap_id_returns_failed_when_fetch_failed(
    service: BeatmapMirrorService,
    repo: InMemoryBeatmapRepository,
) -> None:
    target = BeatmapFetchTarget(target_type="metadata:beatmap", target_key="999")
    now = _NOW
    await repo.mark_fetch_failed(target, "provider_timeout", now)

    result = await service.resolve_by_beatmap_id(999)

    assert result.beatmap is None
    assert result.metadata_status is BeatmapFetchState.FAILED
    assert result.reason == "provider_timeout"


@pytest.mark.asyncio
async def test_resolve_by_beatmap_id_returns_pending_for_pending_fetch(
    service: BeatmapMirrorService,
    repo: InMemoryBeatmapRepository,
) -> None:
    target = BeatmapFetchTarget(target_type="metadata:beatmap", target_key="999")
    now = _NOW
    _ = await repo.try_mark_fetch_pending(target, now)

    result = await service.resolve_by_beatmap_id(999)

    assert result.beatmap is None
    assert result.metadata_status is BeatmapFetchState.PENDING_FETCH
    assert result.reason == "pending_fetch"


@pytest.mark.asyncio
async def test_resolve_by_beatmap_id_returns_stale_when_past_next_refresh(
    service: BeatmapMirrorService,
    repo: InMemoryBeatmapRepository,
) -> None:
    """A beatmap whose next_refresh_at is in the past should report STALE."""
    beatmap = _make_beatmap(
        last_fetched_at=_NOW - _THIRTY_DAYS - _ONE_HOUR,
        next_refresh_at=_NOW - _ONE_HOUR,  # already past
        file_state=BeatmapFileState.AVAILABLE,
    )
    beatmapset = _make_beatmapset(beatmaps=(beatmap,))
    await repo.save_beatmapset_snapshot(beatmapset)

    result = await service.resolve_by_beatmap_id(_BEATMAP_ID)

    assert result.beatmap is not None
    assert result.metadata_status is BeatmapFetchState.STALE
    assert result.reason == "stale"


@pytest.mark.asyncio
async def test_resolve_by_beatmap_id_force_refresh_overrides_freshness(
    service: BeatmapMirrorService,
    repo: InMemoryBeatmapRepository,
) -> None:
    beatmap = _make_beatmap(
        last_fetched_at=_NOW,
        next_refresh_at=_NOW + _THIRTY_DAYS,  # still fresh
    )
    beatmapset = _make_beatmapset(beatmaps=(beatmap,))
    await repo.save_beatmapset_snapshot(beatmapset)

    result = await service.resolve_by_beatmap_id(
        _BEATMAP_ID,
        options=BeatmapResolveOptions(force_refresh=True),
    )

    assert result.beatmap is not None
    assert result.metadata_status is BeatmapFetchState.STALE
    assert result.reason == "force_refresh"


@pytest.mark.asyncio
async def test_resolve_by_beatmap_id_require_osu_file_when_file_missing(
    service: BeatmapMirrorService,
    repo: InMemoryBeatmapRepository,
) -> None:
    beatmap = _make_beatmap(
        last_fetched_at=_NOW,
        next_refresh_at=_NOW + _THIRTY_DAYS,
        file_state=BeatmapFileState.MISSING,
    )
    beatmapset = _make_beatmapset(beatmaps=(beatmap,))
    await repo.save_beatmapset_snapshot(beatmapset)

    result = await service.resolve_by_beatmap_id(
        _BEATMAP_ID,
        options=BeatmapResolveOptions(require_osu_file=True),
    )

    assert result.beatmap is not None
    assert result.file_status is BeatmapFileState.MISSING
    assert result.reason == "osu_file_required_but_unavailable"


@pytest.mark.asyncio
async def test_resolve_by_beatmap_id_file_available_ok(
    service: BeatmapMirrorService,
    repo: InMemoryBeatmapRepository,
) -> None:
    beatmap = _make_beatmap(
        last_fetched_at=_NOW,
        next_refresh_at=_NOW + _THIRTY_DAYS,
        file_state=BeatmapFileState.AVAILABLE,
    )
    beatmapset = _make_beatmapset(beatmaps=(beatmap,))
    await repo.save_beatmapset_snapshot(beatmapset)

    result = await service.resolve_by_beatmap_id(
        _BEATMAP_ID,
        options=BeatmapResolveOptions(require_osu_file=True),
    )

    assert result.file_status is BeatmapFileState.AVAILABLE
    assert result.reason is None


@pytest.mark.asyncio
async def test_resolve_by_beatmap_id_projects_eligibility(
    service: BeatmapMirrorService,
    repo: InMemoryBeatmapRepository,
) -> None:
    beatmap = _make_beatmap(
        official_status=BeatmapRankStatus.QUALIFIED,
        last_fetched_at=_NOW,
        next_refresh_at=_NOW + _THIRTY_DAYS,
    )
    beatmapset = _make_beatmapset(
        beatmaps=(beatmap,),
        official_status=BeatmapRankStatus.QUALIFIED,
    )
    await repo.save_beatmapset_snapshot(beatmapset)

    result = await service.resolve_by_beatmap_id(_BEATMAP_ID)

    assert result.eligibility is not None
    assert result.eligibility.accepts_scores is True
    assert result.eligibility.awards_ranked_pp is False
    assert result.eligibility.awards_loved_pp is False


@pytest.mark.asyncio
async def test_resolve_by_beatmap_id_untrusted_mirror_denies_eligibility(
    service: BeatmapMirrorService,
    repo: InMemoryBeatmapRepository,
) -> None:
    beatmap = _make_beatmap(
        official_status=BeatmapRankStatus.RANKED,
        official_status_source=BeatmapMetadataSource.MIRROR,
        official_status_verified=BeatmapSourceVerification.UNVERIFIED,
        last_fetched_at=_NOW,
        next_refresh_at=_NOW + _THIRTY_DAYS,
    )
    beatmapset = _make_beatmapset(
        beatmaps=(beatmap,),
        official_status_source=BeatmapMetadataSource.MIRROR,
        official_status_verified=BeatmapSourceVerification.UNVERIFIED,
    )
    await repo.save_beatmapset_snapshot(beatmapset)

    result = await service.resolve_by_beatmap_id(_BEATMAP_ID)

    assert result.eligibility is not None
    assert result.eligibility.accepts_scores is False
    assert result.eligibility.denial_reason == "untrusted_mirror_status"


@pytest.mark.asyncio
async def test_resolve_by_beatmap_id_unknown_with_file_fetch_failed(
    service: BeatmapMirrorService,
    repo: InMemoryBeatmapRepository,
) -> None:
    metadata_target = BeatmapFetchTarget(target_type="metadata:beatmap", target_key="999")
    file_target = BeatmapFetchTarget(target_type="file:beatmap", target_key="999")
    now = _NOW
    await repo.mark_fetch_failed(metadata_target, "provider_error", now)
    await repo.mark_fetch_failed(file_target, "file_download_failed", now)

    result = await service.resolve_by_beatmap_id(999)

    assert result.beatmap is None
    assert result.metadata_status is BeatmapFetchState.FAILED
    assert result.file_status is BeatmapFileState.FAILED
    assert result.reason == "provider_error"


# ---------------------------------------------------------------------------
# Tests: resolve_by_beatmapset_id
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_resolve_by_beatmapset_id_returns_cached_set(
    service: BeatmapMirrorService,
    repo: InMemoryBeatmapRepository,
) -> None:
    beatmap = _make_beatmap(last_fetched_at=_NOW, next_refresh_at=_NOW + _THIRTY_DAYS)
    beatmapset = _make_beatmapset(
        beatmaps=(beatmap,),
        last_fetched_at=_NOW,
        next_refresh_at=_NOW + _THIRTY_DAYS,
    )
    await repo.save_beatmapset_snapshot(beatmapset)

    result = await service.resolve_by_beatmapset_id(_BEATMAPSET_ID)

    assert result.beatmapset is not None
    assert result.beatmapset.id == _BEATMAPSET_ID
    assert result.metadata_status is BeatmapFetchState.FRESH
    assert result.source is BeatmapMetadataSource.OFFICIAL
    assert result.verified is True
    assert result.reason is None


@pytest.mark.asyncio
async def test_resolve_by_beatmapset_id_unknown_returns_pending(
    service: BeatmapMirrorService,
) -> None:
    result = await service.resolve_by_beatmapset_id(999)

    assert result.beatmapset is None
    assert result.metadata_status is BeatmapFetchState.PENDING_FETCH
    assert result.source is None
    assert result.verified is False
    assert result.reason == "unsolicited"


@pytest.mark.asyncio
async def test_resolve_by_beatmapset_id_failed_fetch_returns_failed(
    service: BeatmapMirrorService,
    repo: InMemoryBeatmapRepository,
) -> None:
    target = BeatmapFetchTarget(target_type="metadata:beatmapset", target_key="999")
    now = _NOW
    await repo.mark_fetch_failed(target, "api_unreachable", now)

    result = await service.resolve_by_beatmapset_id(999)

    assert result.beatmapset is None
    assert result.metadata_status is BeatmapFetchState.FAILED
    assert result.reason == "api_unreachable"


# ---------------------------------------------------------------------------
# Tests: resolve_by_checksum
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_resolve_by_checksum_returns_cached_beatmap(
    service: BeatmapMirrorService,
    repo: InMemoryBeatmapRepository,
) -> None:
    beatmap = _make_beatmap(
        checksum_md5=_DEFAULT_CHECKSUM,
        last_fetched_at=_NOW,
        next_refresh_at=_NOW + _THIRTY_DAYS,
    )
    beatmapset = _make_beatmapset(beatmaps=(beatmap,))
    await repo.save_beatmapset_snapshot(beatmapset)

    result = await service.resolve_by_checksum(_DEFAULT_CHECKSUM)

    assert result.beatmap is not None
    assert result.beatmap.checksum_md5 == _DEFAULT_CHECKSUM
    assert result.metadata_status is BeatmapFetchState.FRESH
    assert result.source is BeatmapMetadataSource.OFFICIAL
    assert result.verified is True


@pytest.mark.asyncio
async def test_resolve_by_checksum_unknown_returns_pending(
    service: BeatmapMirrorService,
) -> None:
    result = await service.resolve_by_checksum(_ALT_CHECKSUM)

    assert result.beatmap is None
    assert result.metadata_status is BeatmapFetchState.PENDING_FETCH
    assert result.source is None
    assert result.verified is False
    assert result.reason == "unsolicited"


@pytest.mark.asyncio
async def test_resolve_by_checksum_failed_fetch_returns_failed(
    service: BeatmapMirrorService,
    repo: InMemoryBeatmapRepository,
) -> None:
    target = BeatmapFetchTarget(target_type="metadata:checksum", target_key=_ALT_CHECKSUM)
    now = _NOW
    await repo.mark_fetch_failed(target, "checksum_not_found", now)

    result = await service.resolve_by_checksum(_ALT_CHECKSUM)

    assert result.beatmap is None
    assert result.metadata_status is BeatmapFetchState.FAILED
    assert result.reason == "checksum_not_found"


# ---------------------------------------------------------------------------
# Tests: BeatmapResolveResult structure
# ---------------------------------------------------------------------------


def test_resolve_result_is_frozen() -> None:
    result = BeatmapResolveResult(
        beatmap=None,
        beatmapset=None,
        eligibility=None,
        metadata_status=BeatmapFetchState.PENDING_FETCH,
        file_status=BeatmapFileState.MISSING,
        source=None,
        verified=False,
        last_fetched_at=None,
        next_refresh_at=None,
        reason="unsolicited",
    )
    with pytest.raises(FrozenInstanceError):
        result.reason = "changed"  # pyright: ignore[reportAttributeAccessIssue]


def test_set_resolve_result_is_frozen() -> None:
    result = BeatmapSetResolveResult(
        beatmapset=None,
        metadata_status=BeatmapFetchState.PENDING_FETCH,
        source=None,
        verified=False,
        last_fetched_at=None,
        next_refresh_at=None,
        reason="unsolicited",
    )
    with pytest.raises(FrozenInstanceError):
        result.reason = "changed"  # pyright: ignore[reportAttributeAccessIssue]


def test_resolve_options_defaults() -> None:
    opts = BeatmapResolveOptions()
    assert opts.require_osu_file is False
    assert opts.wait_timeout_seconds == 0.0
    assert opts.force_refresh is False
