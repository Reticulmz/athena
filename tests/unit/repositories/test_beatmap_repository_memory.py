from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime, timedelta

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
    LocalBeatmapStatus,
)
from osu_server.repositories.interfaces.beatmap_repository import (
    BeatmapFetchTarget,
    BeatmapRepository,
    DuplicateBeatmapChecksumError,
)
from osu_server.repositories.memory.beatmap_repository import InMemoryBeatmapRepository

_NOW = datetime(2026, 6, 4, tzinfo=UTC)
_NEXT_REFRESH = _NOW + timedelta(days=30)
_CHECKSUM = "0123456789abcdef0123456789abcdef"
_OTHER_CHECKSUM = "fedcba9876543210fedcba9876543210"


def _make_beatmap(
    *,
    beatmap_id: int = 2_000,
    beatmapset_id: int = 1_000,
    checksum_md5: str = _CHECKSUM,
    official_status: BeatmapRankStatus = BeatmapRankStatus.RANKED,
    local_status_override: LocalBeatmapStatus | None = None,
    file_attachment: BeatmapFileAttachment | None = None,
) -> Beatmap:
    return Beatmap(
        id=beatmap_id,
        beatmapset_id=beatmapset_id,
        checksum_md5=checksum_md5,
        mode="osu",
        version=f"Difficulty {beatmap_id}",
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
        local_status_override=local_status_override,
        metadata_fetch_state=BeatmapFetchState.FRESH,
        file_state=(
            BeatmapFileState.AVAILABLE if file_attachment is not None else BeatmapFileState.MISSING
        ),
        file_attachment=file_attachment,
        last_fetched_at=_NOW,
        next_refresh_at=_NEXT_REFRESH,
    )


def _make_beatmapset(
    *beatmaps: Beatmap,
    status: BeatmapRankStatus = BeatmapRankStatus.RANKED,
) -> BeatmapSet:
    return BeatmapSet(
        id=1_000,
        artist="Camellia",
        title="Exit This Earth's Atomosphere",
        creator="Realazy",
        artist_unicode=None,
        title_unicode=None,
        official_status=status,
        official_status_source=BeatmapMetadataSource.OFFICIAL,
        official_status_verified=BeatmapSourceVerification.VERIFIED,
        beatmaps=beatmaps,
        last_fetched_at=_NOW,
        next_refresh_at=_NEXT_REFRESH,
    )


def _make_attachment(
    *,
    beatmap_id: int = 2_000,
    checksum_md5: str = _CHECKSUM,
    blob_id: int = 55,
) -> BeatmapFileAttachment:
    return BeatmapFileAttachment(
        beatmap_id=beatmap_id,
        blob_id=blob_id,
        checksum_md5=checksum_md5,
        source="official",
        original_filename=f"{beatmap_id}.osu",
        fetched_at=_NOW,
        verified_at=_NOW,
    )


def test_in_memory_beatmap_repository_satisfies_contract() -> None:
    repo = InMemoryBeatmapRepository()

    assert isinstance(repo, BeatmapRepository)


async def test_saves_and_resolves_beatmaps_by_id_set_id_and_checksum() -> None:
    repo = InMemoryBeatmapRepository()
    beatmap = _make_beatmap()

    await repo.save_beatmapset_snapshot(_make_beatmapset(beatmap))

    assert await repo.get_beatmap(2_000) == beatmap
    assert await repo.get_beatmap_by_checksum(_CHECKSUM) == beatmap
    beatmapset = await repo.get_beatmapset(1_000)
    assert beatmapset is not None
    assert beatmapset.beatmaps == (beatmap,)


async def test_save_rejects_checksum_reuse_for_different_beatmap() -> None:
    repo = InMemoryBeatmapRepository()
    await repo.save_beatmapset_snapshot(_make_beatmapset(_make_beatmap()))

    with pytest.raises(DuplicateBeatmapChecksumError) as exc_info:
        await repo.save_beatmapset_snapshot(
            _make_beatmapset(_make_beatmap(beatmap_id=2_001, checksum_md5=_CHECKSUM))
        )

    assert exc_info.value.checksum_md5 == _CHECKSUM
    assert exc_info.value.existing_beatmap_id == 2_000


async def test_save_rejects_duplicate_checksum_inside_same_snapshot() -> None:
    repo = InMemoryBeatmapRepository()

    with pytest.raises(DuplicateBeatmapChecksumError) as exc_info:
        await repo.save_beatmapset_snapshot(
            _make_beatmapset(
                _make_beatmap(beatmap_id=2_000, checksum_md5=_CHECKSUM),
                _make_beatmap(beatmap_id=2_001, checksum_md5=_CHECKSUM),
            )
        )

    assert exc_info.value.checksum_md5 == _CHECKSUM
    assert exc_info.value.existing_beatmap_id == 2_000
    assert await repo.get_beatmap(2_000) is None
    assert await repo.get_beatmap(2_001) is None


async def test_official_refresh_preserves_existing_local_override() -> None:
    repo = InMemoryBeatmapRepository()
    await repo.save_beatmapset_snapshot(
        _make_beatmapset(
            _make_beatmap(
                official_status=BeatmapRankStatus.PENDING,
                local_status_override=LocalBeatmapStatus.RANKED,
            )
        )
    )

    await repo.save_beatmapset_snapshot(
        _make_beatmapset(
            _make_beatmap(official_status=BeatmapRankStatus.LOVED),
            status=BeatmapRankStatus.LOVED,
        )
    )

    refreshed = await repo.get_beatmap(2_000)
    assert refreshed is not None
    assert refreshed.official_status is BeatmapRankStatus.LOVED
    assert refreshed.local_status_override is LocalBeatmapStatus.RANKED
    assert refreshed.effective_status is BeatmapRankStatus.RANKED


async def test_can_set_local_override_without_changing_official_status() -> None:
    repo = InMemoryBeatmapRepository()
    await repo.save_beatmapset_snapshot(
        _make_beatmapset(_make_beatmap(official_status=BeatmapRankStatus.PENDING))
    )

    updated = await repo.set_local_status_override(2_000, LocalBeatmapStatus.RANKED)

    assert updated.official_status is BeatmapRankStatus.PENDING
    assert updated.local_status_override is LocalBeatmapStatus.RANKED
    assert updated.effective_status is BeatmapRankStatus.RANKED


async def test_attachments_are_idempotent_and_update_current_file_state() -> None:
    repo = InMemoryBeatmapRepository()
    await repo.save_beatmapset_snapshot(_make_beatmapset(_make_beatmap()))
    attachment = _make_attachment()

    first = await repo.attach_osu_file(attachment)
    duplicate = await repo.attach_osu_file(replace(attachment, blob_id=99))

    assert first == attachment
    assert duplicate == attachment
    assert await repo.get_current_file_attachment(2_000) == attachment
    beatmap = await repo.get_beatmap(2_000)
    assert beatmap is not None
    assert beatmap.file_state is BeatmapFileState.AVAILABLE
    assert beatmap.file_attachment == attachment


async def test_official_refresh_preserves_existing_file_attachment() -> None:
    repo = InMemoryBeatmapRepository()
    attachment = _make_attachment()
    await repo.save_beatmapset_snapshot(
        _make_beatmapset(_make_beatmap(file_attachment=attachment))
    )

    await repo.save_beatmapset_snapshot(
        _make_beatmapset(_make_beatmap(official_status=BeatmapRankStatus.LOVED))
    )

    refreshed = await repo.get_beatmap(2_000)
    assert refreshed is not None
    assert refreshed.file_state is BeatmapFileState.AVAILABLE
    assert refreshed.file_attachment == attachment


async def test_fetch_pending_marker_is_idempotent_until_completed() -> None:
    repo = InMemoryBeatmapRepository()
    target = BeatmapFetchTarget.metadata_by_beatmap_id(2_000)

    first = await repo.try_mark_fetch_pending(target, now=_NOW)
    duplicate = await repo.try_mark_fetch_pending(target, now=_NOW + timedelta(seconds=1))
    state = await repo.get_fetch_state(target)

    assert first is True
    assert duplicate is False
    assert state is not None
    assert state.status is BeatmapFetchState.PENDING_FETCH
    assert state.attempt_count == 1
    assert state.pending_since == _NOW

    await repo.mark_fetch_succeeded(target, now=_NOW + timedelta(seconds=2))
    second_pending = await repo.try_mark_fetch_pending(target, now=_NOW + timedelta(seconds=3))

    assert second_pending is True
    refreshed_state = await repo.get_fetch_state(target)
    assert refreshed_state is not None
    assert refreshed_state.status is BeatmapFetchState.PENDING_FETCH
    assert refreshed_state.attempt_count == 2


async def test_failed_fetch_state_is_observable() -> None:
    repo = InMemoryBeatmapRepository()
    target = BeatmapFetchTarget.file_by_beatmap_id(2_000)

    _ = await repo.try_mark_fetch_pending(target, now=_NOW)
    await repo.mark_fetch_failed(target, reason="timeout", now=_NOW + timedelta(seconds=5))

    state = await repo.get_fetch_state(target)
    assert state is not None
    assert state.status is BeatmapFetchState.FAILED
    assert state.last_error == "timeout"
    assert state.last_attempted_at == _NOW + timedelta(seconds=5)


# ---------------------------------------------------------------------------
# Filename-within-beatmapset lookup (task 1.2)
# ---------------------------------------------------------------------------


async def test_resolves_beatmap_by_exact_filename_in_beatmapset() -> None:
    """Exact original_filename within a beatmapset returns the matching beatmap."""
    repo = InMemoryBeatmapRepository()
    attachment = replace(_make_attachment(beatmap_id=2_000), original_filename="my_map.osu")
    beatmap = _make_beatmap(file_attachment=attachment)
    await repo.save_beatmapset_snapshot(_make_beatmapset(beatmap))

    result = await repo.get_beatmap_by_filename_in_beatmapset(1_000, "my_map.osu")

    assert result is not None
    assert result.id == 2_000


async def test_filename_lookup_returns_none_when_no_match_in_set() -> None:
    """Returns None when no beatmap in the set has the matching filename."""
    repo = InMemoryBeatmapRepository()
    attachment = replace(_make_attachment(beatmap_id=2_000), original_filename="real.osu")
    beatmap = _make_beatmap(file_attachment=attachment)
    await repo.save_beatmapset_snapshot(_make_beatmapset(beatmap))

    result = await repo.get_beatmap_by_filename_in_beatmapset(1_000, "other.osu")

    assert result is None


async def test_filename_lookup_returns_none_when_set_does_not_exist() -> None:
    """Returns None when the requested beatmapset does not exist."""
    repo = InMemoryBeatmapRepository()

    result = await repo.get_beatmap_by_filename_in_beatmapset(999, "anything.osu")

    assert result is None


async def test_filename_lookup_returns_none_for_partial_filename_match() -> None:
    """Exact match only; partial filename fragments must not resolve (requirement 4.6)."""
    repo = InMemoryBeatmapRepository()
    attachment = replace(_make_attachment(beatmap_id=2_000), original_filename="my_map.osu")
    beatmap = _make_beatmap(file_attachment=attachment)
    await repo.save_beatmapset_snapshot(_make_beatmapset(beatmap))

    assert await repo.get_beatmap_by_filename_in_beatmapset(1_000, "my_map") is None
    assert await repo.get_beatmap_by_filename_in_beatmapset(1_000, ".osu") is None
    assert await repo.get_beatmap_by_filename_in_beatmapset(1_000, "map.osu") is None


async def test_filename_lookup_scoped_to_beatmapset() -> None:
    """Filename is resolved only within its matching beatmapset (requirement 4.3, 4.4)."""
    repo = InMemoryBeatmapRepository()

    # Beatmapset 1000: beatmap 2000 with "shared.osu"
    attachment_a = replace(_make_attachment(beatmap_id=2_000), original_filename="shared.osu")
    beatmap_a = _make_beatmap(beatmap_id=2_000, beatmapset_id=1_000, file_attachment=attachment_a)
    await repo.save_beatmapset_snapshot(_make_beatmapset(beatmap_a))

    # Beatmapset 2000: beatmap 3000 with "other.osu" (no "shared.osu" here)
    attachment_b = replace(_make_attachment(beatmap_id=3_000), original_filename="other.osu")
    beatmap_b = _make_beatmap(
        beatmap_id=3_000,
        beatmapset_id=2_000,
        checksum_md5=_OTHER_CHECKSUM,
        file_attachment=attachment_b,
    )
    await repo.save_beatmapset_snapshot(replace(_make_beatmapset(beatmap_b), id=2_000))

    # "shared.osu" exists in set 1000 but NOT in set 2000
    assert await repo.get_beatmap_by_filename_in_beatmapset(1_000, "shared.osu") is not None
    assert await repo.get_beatmap_by_filename_in_beatmapset(2_000, "shared.osu") is None


async def test_filename_lookup_beatmap_without_attachment_returns_none() -> None:
    """Beatmap without a file attachment cannot be resolved by filename."""
    repo = InMemoryBeatmapRepository()
    beatmap = _make_beatmap()  # no file_attachment
    await repo.save_beatmapset_snapshot(_make_beatmapset(beatmap))

    result = await repo.get_beatmap_by_filename_in_beatmapset(1_000, "2000.osu")

    assert result is None
