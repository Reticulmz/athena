"""GetscoresResolver unit tests.

TDD RED -> GREEN -> REFACTOR.
Validates checksum-first resolution, bounded-wait metadata resolution,
metadata-only options, and unavailable outcomes.
"""

from __future__ import annotations

import asyncio
from dataclasses import is_dataclass
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable

import pytest

from osu_server.domain.beatmap import (
    Beatmap,
    BeatmapFetchState,
    BeatmapFileAttachment,
    BeatmapFileState,
    BeatmapMetadataSource,
    BeatmapRankStatus,
    BeatmapSet,
    BeatmapSourceVerification,
)
from osu_server.repositories.memory.beatmap_repository import (
    InMemoryBeatmapRepository,
)
from osu_server.services.beatmap_mirror_service import BeatmapResolveResult
from osu_server.transports.web_legacy.getscores_query_parser import (
    GetscoresRequest,
)
from osu_server.transports.web_legacy.getscores_resolver import (
    GetscoresOutcomeKind,
    GetscoresResolveOutcome,
    GetscoresResolver,
    GetscoresResolveReason,
)
from osu_server.transports.web_legacy.getscores_status_mapper import (
    GetscoresStatusMapper,
)

_NOW = datetime(2026, 6, 7, tzinfo=UTC)
_NEXT_REFRESH = _NOW + timedelta(days=30)
_CHECKSUM = "0123456789abcdef0123456789abcdef"


def _make_beatmap(
    *,
    beatmap_id: int = 75,
    beatmapset_id: int = 1,
    checksum_md5: str = _CHECKSUM,
    official_status: BeatmapRankStatus = BeatmapRankStatus.RANKED,
) -> Beatmap:
    return Beatmap(
        id=beatmap_id,
        beatmapset_id=beatmapset_id,
        checksum_md5=checksum_md5,
        mode="osu",
        version="Insane",
        total_length=240,
        hit_length=220,
        max_combo=1234,
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


def _make_beatmapset(
    *,
    beatmapset_id: int = 1,
    artist: str = "Camellia",
    title: str = "Exit This Earth's Atomosphere",
) -> BeatmapSet:
    return BeatmapSet(
        id=beatmapset_id,
        artist=artist,
        title=title,
        creator="Realazy",
        artist_unicode=None,
        title_unicode=None,
        official_status=BeatmapRankStatus.RANKED,
        official_status_source=BeatmapMetadataSource.OFFICIAL,
        official_status_verified=BeatmapSourceVerification.VERIFIED,
        beatmaps=(),
        last_fetched_at=_NOW,
        next_refresh_at=_NEXT_REFRESH,
    )


def _seed_beatmap_in_repo(
    repo: InMemoryBeatmapRepository,
    beatmap: Beatmap,
    beatmapset: BeatmapSet,
) -> None:
    """Seed a beatmap and beatmapset into the in-memory repo for direct lookups."""
    repo._beatmapsets[beatmapset.id] = beatmapset  # noqa: SLF001  # pyright: ignore[reportPrivateUsage]
    repo._beatmaps[beatmap.id] = beatmap  # noqa: SLF001  # pyright: ignore[reportPrivateUsage]
    repo._beatmap_ids_by_checksum[beatmap.checksum_md5] = beatmap.id  # noqa: SLF001  # pyright: ignore[reportPrivateUsage]


# ---------------------------------------------------------------------------
# Checksum-first resolution (requirements 4.1, 4.2)
# ---------------------------------------------------------------------------


async def test_known_checksum_returns_header_immediately() -> None:
    """Known checksum returns HEADER without calling mirror service (req 4.1)."""
    repo = InMemoryBeatmapRepository()
    beatmap = _make_beatmap(checksum_md5=_CHECKSUM)
    beatmapset = _make_beatmapset()
    _seed_beatmap_in_repo(repo, beatmap, beatmapset)

    # Mirror should not be called — use a counter to verify
    call_count = 0

    async def _mirror_resolve(_checksum_md5: str, _options: object = None) -> BeatmapResolveResult:
        nonlocal call_count
        call_count += 1
        return _make_resolve_result(
            beatmap=None, beatmapset=None, metadata_status=BeatmapFetchState.PENDING_FETCH
        )

    resolver = _make_resolver(repo, mirror_resolve=_mirror_resolve)

    outcome = await resolver.resolve(
        GetscoresRequest(
            checksum_md5=_CHECKSUM,
            filename=None,
            beatmapset_id_hint=None,
            mode=None,
            mods=None,
            leaderboard_type=None,
            leaderboard_version=None,
            song_select=None,
            anti_cheat_signal=False,
        ),
        wait_timeout_seconds=0.5,
    )

    assert outcome.kind == GetscoresOutcomeKind.HEADER
    assert outcome.header is not None
    assert outcome.header.beatmap.id == beatmap.id
    assert outcome.header.beatmapset.id == beatmapset.id
    assert call_count == 0  # Mirror NOT called for known checksum


async def test_known_checksum_ignores_conflicting_filename_hint() -> None:
    """Checksum result preferred over filename+set hint (req 4.2)."""
    repo = InMemoryBeatmapRepository()
    beatmap = _make_beatmap(beatmap_id=75, beatmapset_id=1, checksum_md5=_CHECKSUM)
    beatmapset = _make_beatmapset(beatmapset_id=1)
    _seed_beatmap_in_repo(repo, beatmap, beatmapset)

    resolver = _make_resolver(repo)

    outcome = await resolver.resolve(
        GetscoresRequest(
            checksum_md5=_CHECKSUM,
            filename="different.osu",
            beatmapset_id_hint=999,
            mode=None,
            mods=None,
            leaderboard_type=None,
            leaderboard_version=None,
            song_select=None,
            anti_cheat_signal=False,
        ),
        wait_timeout_seconds=0.5,
    )

    assert outcome.kind == GetscoresOutcomeKind.HEADER
    assert outcome.header is not None
    assert outcome.header.beatmap.id == 75  # Checksum result beats filename hint


# ---------------------------------------------------------------------------
# Unknown checksum -> bounded wait metadata resolution (req 5.1-5.7)
# ---------------------------------------------------------------------------


async def test_unknown_checksum_resolves_to_submitted_beatmap_after_wait() -> None:
    """Unknown checksum -> mirror resolves to submitted beatmap -> HEADER (req 5.2, 5.4)."""
    repo = InMemoryBeatmapRepository()
    beatmap = _make_beatmap(checksum_md5=_CHECKSUM, official_status=BeatmapRankStatus.RANKED)
    beatmapset = _make_beatmapset()

    async def _mirror_resolve(_checksum_md5: str, _options: object = None) -> BeatmapResolveResult:
        await asyncio.sleep(0.01)
        # Mirror persists resolved metadata to the repo
        _seed_beatmap_in_repo(repo, beatmap, beatmapset)
        return _make_resolve_result(beatmap=beatmap, beatmapset=beatmapset)

    resolver = _make_resolver(repo, mirror_resolve=_mirror_resolve)

    outcome = await resolver.resolve(
        GetscoresRequest(
            checksum_md5=_CHECKSUM,
            filename=None,
            beatmapset_id_hint=None,
            mode=None,
            mods=None,
            leaderboard_type=None,
            leaderboard_version=None,
            song_select=None,
            anti_cheat_signal=False,
        ),
        wait_timeout_seconds=0.5,
    )

    assert outcome.kind == GetscoresOutcomeKind.HEADER
    assert outcome.header is not None
    assert outcome.header.beatmap.id == beatmap.id


async def test_unknown_checksum_resolves_to_not_submitted_returns_unavailable() -> None:
    """Mirror resolves NotSubmitted -> UNAVAILABLE (req 5.5)."""
    repo = InMemoryBeatmapRepository()
    beatmap = _make_beatmap(
        checksum_md5=_CHECKSUM,
        official_status=BeatmapRankStatus.NOT_SUBMITTED,
    )
    beatmapset = _make_beatmapset()

    async def _mirror_resolve(_checksum_md5: str, _options: object = None) -> BeatmapResolveResult:
        await asyncio.sleep(0.01)
        _seed_beatmap_in_repo(repo, beatmap, beatmapset)
        return _make_resolve_result(beatmap=beatmap, beatmapset=beatmapset)

    resolver = _make_resolver(repo, mirror_resolve=_mirror_resolve)

    outcome = await resolver.resolve(
        GetscoresRequest(
            checksum_md5=_CHECKSUM,
            filename=None,
            beatmapset_id_hint=None,
            mode=None,
            mods=None,
            leaderboard_type=None,
            leaderboard_version=None,
            song_select=None,
            anti_cheat_signal=False,
        ),
        wait_timeout_seconds=0.5,
    )

    assert outcome.kind == GetscoresOutcomeKind.UNAVAILABLE
    assert outcome.header is None
    assert outcome.reason == GetscoresResolveReason.NOT_SUBMITTED


async def test_unknown_checksum_pending_after_wait_returns_unavailable() -> None:
    """Mirror still pending after bounded wait -> UNAVAILABLE (req 5.6)."""
    repo = InMemoryBeatmapRepository()

    async def _mirror_resolve(_checksum_md5: str, _options: object = None) -> BeatmapResolveResult:
        await asyncio.sleep(0.3)  # Longer than wait_timeout
        return _make_resolve_result(
            beatmap=None, beatmapset=None, metadata_status=BeatmapFetchState.PENDING_FETCH
        )

    resolver = _make_resolver(repo, mirror_resolve=_mirror_resolve)

    outcome = await resolver.resolve(
        GetscoresRequest(
            checksum_md5=_CHECKSUM,
            filename=None,
            beatmapset_id_hint=None,
            mode=None,
            mods=None,
            leaderboard_type=None,
            leaderboard_version=None,
            song_select=None,
            anti_cheat_signal=False,
        ),
        wait_timeout_seconds=0.05,
    )

    assert outcome.kind == GetscoresOutcomeKind.UNAVAILABLE


async def test_unknown_checksum_metadata_failed_returns_unavailable() -> None:
    """Mirror resolution fails -> UNAVAILABLE (req 5.7)."""
    repo = InMemoryBeatmapRepository()

    async def _mirror_resolve(_checksum_md5: str, _options: object = None) -> BeatmapResolveResult:
        return _make_resolve_result(
            beatmap=None,
            beatmapset=None,
            metadata_status=BeatmapFetchState.FAILED,
            reason="fetch error",
        )

    resolver = _make_resolver(repo, mirror_resolve=_mirror_resolve)

    outcome = await resolver.resolve(
        GetscoresRequest(
            checksum_md5=_CHECKSUM,
            filename=None,
            beatmapset_id_hint=None,
            mode=None,
            mods=None,
            leaderboard_type=None,
            leaderboard_version=None,
            song_select=None,
            anti_cheat_signal=False,
        ),
        wait_timeout_seconds=0.5,
    )

    assert outcome.kind == GetscoresOutcomeKind.UNAVAILABLE


# ---------------------------------------------------------------------------
# Filename-in-set lookup (no checksum) (req 4.3, 4.4)
# ---------------------------------------------------------------------------


async def test_filename_in_set_finds_submitted_beatmap_returns_header() -> None:
    """Filename+set lookup finds submitted beatmap -> HEADER."""
    repo = InMemoryBeatmapRepository()
    beatmap = _make_beatmap(
        beatmap_id=75,
        beatmapset_id=1,
        checksum_md5=_CHECKSUM,
        official_status=BeatmapRankStatus.RANKED,
    )
    beatmapset = _make_beatmapset(beatmapset_id=1)

    # Attach file_attachment with the target filename
    attachment = BeatmapFileAttachment(
        beatmap_id=beatmap.id,
        blob_id=1,
        checksum_md5=_CHECKSUM,
        source="osu_api",
        original_filename="beatmap.osu",
        fetched_at=_NOW,
        verified_at=None,
    )
    beatmap_with_file = _beatmap_with_attachment(beatmap, attachment)
    # Update beatmapset beatmaps to include the beatmap with attachment
    patched_set = BeatmapSet(
        id=beatmapset.id,
        artist=beatmapset.artist,
        title=beatmapset.title,
        creator=beatmapset.creator,
        artist_unicode=beatmapset.artist_unicode,
        title_unicode=beatmapset.title_unicode,
        official_status=beatmapset.official_status,
        official_status_source=beatmapset.official_status_source,
        official_status_verified=beatmapset.official_status_verified,
        beatmaps=(beatmap_with_file,),
        last_fetched_at=beatmapset.last_fetched_at,
        next_refresh_at=beatmapset.next_refresh_at,
    )

    _seed_beatmap_in_repo(repo, beatmap_with_file, patched_set)

    resolver = _make_resolver(repo)

    outcome = await resolver.resolve(
        GetscoresRequest(
            checksum_md5=None,
            filename="beatmap.osu",
            beatmapset_id_hint=1,
            mode=None,
            mods=None,
            leaderboard_type=None,
            leaderboard_version=None,
            song_select=None,
            anti_cheat_signal=False,
        ),
        wait_timeout_seconds=0.5,
    )

    assert outcome.kind == GetscoresOutcomeKind.HEADER
    assert outcome.header is not None
    assert outcome.header.beatmap.id == 75


async def test_filename_in_set_not_found_returns_unavailable() -> None:
    """Filename+set lookup finds nothing -> UNAVAILABLE."""
    repo = InMemoryBeatmapRepository()

    resolver = _make_resolver(repo)

    outcome = await resolver.resolve(
        GetscoresRequest(
            checksum_md5=None,
            filename="beatmap.osu",
            beatmapset_id_hint=1,
            mode=None,
            mods=None,
            leaderboard_type=None,
            leaderboard_version=None,
            song_select=None,
            anti_cheat_signal=False,
        ),
        wait_timeout_seconds=0.5,
    )

    assert outcome.kind == GetscoresOutcomeKind.UNAVAILABLE


# ---------------------------------------------------------------------------
# Metadata-only resolution (no .osu file required) (req 5.8)
# ---------------------------------------------------------------------------


async def test_resolver_does_not_require_osu_file() -> None:
    """Header returned even when beatmap has no .osu file (req 5.8)."""
    repo = InMemoryBeatmapRepository()
    beatmap = _make_beatmap(checksum_md5=_CHECKSUM)
    beatmapset = _make_beatmapset()
    _seed_beatmap_in_repo(repo, beatmap, beatmapset)

    resolver = _make_resolver(repo)

    outcome = await resolver.resolve(
        GetscoresRequest(
            checksum_md5=_CHECKSUM,
            filename=None,
            beatmapset_id_hint=None,
            mode=None,
            mods=None,
            leaderboard_type=None,
            leaderboard_version=None,
            song_select=None,
            anti_cheat_signal=False,
        ),
        wait_timeout_seconds=0.5,
    )

    assert outcome.kind == GetscoresOutcomeKind.HEADER


# ---------------------------------------------------------------------------
# Known checksum with NotSubmitted status (req 7.1)
# ---------------------------------------------------------------------------


async def test_known_checksum_not_submitted_returns_unavailable() -> None:
    """Known checksum with NotSubmitted status -> UNAVAILABLE (req 7.1)."""
    repo = InMemoryBeatmapRepository()
    beatmap = _make_beatmap(
        checksum_md5=_CHECKSUM,
        official_status=BeatmapRankStatus.NOT_SUBMITTED,
    )
    beatmapset = _make_beatmapset()
    _seed_beatmap_in_repo(repo, beatmap, beatmapset)

    resolver = _make_resolver(repo)

    outcome = await resolver.resolve(
        GetscoresRequest(
            checksum_md5=_CHECKSUM,
            filename=None,
            beatmapset_id_hint=None,
            mode=None,
            mods=None,
            leaderboard_type=None,
            leaderboard_version=None,
            song_select=None,
            anti_cheat_signal=False,
        ),
        wait_timeout_seconds=0.5,
    )

    assert outcome.kind == GetscoresOutcomeKind.UNAVAILABLE
    assert outcome.reason == GetscoresResolveReason.NOT_SUBMITTED


# ---------------------------------------------------------------------------
# Outcome reason enum coverage
# ---------------------------------------------------------------------------


def test_outcome_kind_enum_has_expected_values() -> None:
    """GetscoresOutcomeKind covers HEADER, UNAVAILABLE, UPDATE_AVAILABLE."""
    assert GetscoresOutcomeKind.HEADER.value == "header"
    assert GetscoresOutcomeKind.UNAVAILABLE.value == "unavailable"
    assert GetscoresOutcomeKind.UPDATE_AVAILABLE.value == "update_available"


def test_resolve_reason_enum_covers_resolution_paths() -> None:
    """GetscoresResolveReason covers known paths."""
    reasons = list(GetscoresResolveReason)
    assert GetscoresResolveReason.KNOWN_CHECKSUM in reasons
    assert GetscoresResolveReason.NOT_SUBMITTED in reasons
    assert GetscoresResolveReason.PENDING_FETCH in reasons
    assert GetscoresResolveReason.FAILED_METADATA in reasons
    assert GetscoresResolveReason.NOT_FOUND in reasons


# ---------------------------------------------------------------------------
# Resolve outcome frozen dataclass
# ---------------------------------------------------------------------------


def test_resolve_outcome_is_frozen_dataclass() -> None:
    """GetscoresResolveOutcome is a frozen dataclass."""
    assert is_dataclass(GetscoresResolveOutcome)

    outcome = GetscoresResolveOutcome(
        kind=GetscoresOutcomeKind.UNAVAILABLE,
        header=None,
        reason=GetscoresResolveReason.NOT_FOUND,
    )

    with pytest.raises(AttributeError):
        outcome.kind = GetscoresOutcomeKind.HEADER  # type: ignore[misc]  # pyright: ignore[reportAttributeAccessIssue]


# ---------------------------------------------------------------------------
# Contract
# ---------------------------------------------------------------------------


def test_resolver_has_expected_interface() -> None:
    resolver = _make_resolver(InMemoryBeatmapRepository())
    assert hasattr(resolver, "resolve")
    assert callable(resolver.resolve)


# ---------------------------------------------------------------------------
# Test helpers
# ---------------------------------------------------------------------------


def _make_resolve_result(
    *,
    beatmap: Beatmap | None = None,
    beatmapset: BeatmapSet | None = None,
    metadata_status: BeatmapFetchState = BeatmapFetchState.FRESH,
    reason: str | None = None,
) -> BeatmapResolveResult:
    """Build a BeatmapResolveResult."""
    return BeatmapResolveResult(
        beatmap=beatmap,
        beatmapset=beatmapset,
        eligibility=None,
        metadata_status=metadata_status,
        file_status=BeatmapFileState.MISSING,
        source=BeatmapMetadataSource.OFFICIAL if beatmap else None,
        verified=beatmap is not None,
        last_fetched_at=_NOW if beatmap else None,
        next_refresh_at=_NEXT_REFRESH if beatmap else None,
        reason=reason,
    )


def _make_resolver(
    repo: InMemoryBeatmapRepository,
    mirror_resolve: Callable[..., Awaitable[object]] | None = None,
) -> GetscoresResolver:
    """Build a GetscoresResolver, optionally with a custom mirror resolve."""
    if mirror_resolve is not None:
        resolver = GetscoresResolver(
            repository=repo,
            status_mapper=GetscoresStatusMapper(),
            _mirror_resolve=mirror_resolve,
        )
    else:
        resolver = GetscoresResolver(
            repository=repo,
            status_mapper=GetscoresStatusMapper(),
            _mirror_resolve=_noop_mirror_resolve,
        )
    return resolver


async def _noop_mirror_resolve(_checksum_md5: str, _options: object = None) -> object:
    return _make_resolve_result()


def _beatmap_with_attachment(beatmap: Beatmap, attachment: BeatmapFileAttachment) -> Beatmap:
    return Beatmap(
        id=beatmap.id,
        beatmapset_id=beatmap.beatmapset_id,
        checksum_md5=beatmap.checksum_md5,
        mode=beatmap.mode,
        version=beatmap.version,
        total_length=beatmap.total_length,
        hit_length=beatmap.hit_length,
        max_combo=beatmap.max_combo,
        bpm=beatmap.bpm,
        cs=beatmap.cs,
        od=beatmap.od,
        ar=beatmap.ar,
        hp=beatmap.hp,
        difficulty_rating=beatmap.difficulty_rating,
        official_status=beatmap.official_status,
        official_status_source=beatmap.official_status_source,
        official_status_verified=beatmap.official_status_verified,
        local_status_override=beatmap.local_status_override,
        metadata_fetch_state=beatmap.metadata_fetch_state,
        file_state=beatmap.file_state,
        file_attachment=attachment,
        last_fetched_at=beatmap.last_fetched_at,
        next_refresh_at=beatmap.next_refresh_at,
    )
