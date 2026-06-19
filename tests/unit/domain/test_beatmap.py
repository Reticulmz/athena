from __future__ import annotations

from dataclasses import fields
from datetime import UTC, datetime, timedelta
from enum import Enum

import pytest

from osu_server.domain.beatmaps import (
    Beatmap,
    BeatmapFetchQueuePayload,
    BeatmapFetchState,
    BeatmapFetchTarget,
    BeatmapFetchTargetKind,
    BeatmapFileAttachment,
    BeatmapFileState,
    BeatmapMetadataLookupKind,
    BeatmapMetadataSource,
    BeatmapRankStatus,
    BeatmapSet,
    BeatmapSourceVerification,
    LocalBeatmapStatus,
)

_NOW = datetime(2026, 6, 4, tzinfo=UTC)
_NEXT_REFRESH = _NOW + timedelta(days=30)
_CHECKSUM = "0123456789abcdef0123456789abcdef"


def _make_beatmap(
    *,
    official_status: BeatmapRankStatus = BeatmapRankStatus.RANKED,
    local_status_override: LocalBeatmapStatus | None = None,
    source: BeatmapMetadataSource = BeatmapMetadataSource.OFFICIAL,
    source_verification: BeatmapSourceVerification = BeatmapSourceVerification.VERIFIED,
    file_attachment: BeatmapFileAttachment | None = None,
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
        official_status=official_status,
        official_status_source=source,
        official_status_verified=source_verification,
        local_status_override=local_status_override,
        metadata_fetch_state=BeatmapFetchState.FRESH,
        file_state=(
            BeatmapFileState.AVAILABLE if file_attachment is not None else BeatmapFileState.MISSING
        ),
        file_attachment=file_attachment,
        last_fetched_at=_NOW,
        next_refresh_at=_NEXT_REFRESH,
    )


def _make_attachment() -> BeatmapFileAttachment:
    return BeatmapFileAttachment(
        beatmap_id=2_000,
        blob_id=55,
        checksum_md5=_CHECKSUM,
        source="official",
        original_filename="2000.osu",
        fetched_at=_NOW,
        verified_at=_NOW,
    )


def test_rank_status_enum_preserves_approved_as_official_status() -> None:
    assert issubclass(BeatmapRankStatus, Enum)
    assert BeatmapRankStatus.APPROVED.value == "approved"
    assert BeatmapRankStatus.RANKED.value == "ranked"
    assert BeatmapRankStatus.LOVED.value == "loved"
    assert BeatmapRankStatus.UNKNOWN.value == "unknown"


def test_local_status_enum_excludes_approved() -> None:
    assert "approved" not in {status.value for status in LocalBeatmapStatus}
    assert LocalBeatmapStatus.RANKED.value == "ranked"


def test_fetch_target_exposes_typed_metadata_lookup() -> None:
    target = BeatmapFetchTarget.metadata_by_beatmapset_id(1234)

    lookup = target.metadata_lookup_target()

    assert target.kind is BeatmapFetchTargetKind.METADATA_BY_BEATMAPSET_ID
    assert lookup.kind is BeatmapMetadataLookupKind.BEATMAPSET_ID
    assert lookup.int_value() == 1234
    assert target.queue_payload() == BeatmapFetchQueuePayload(
        target_type="metadata:beatmapset",
        target_key="1234",
    )


def test_fetch_target_restores_worker_queue_payload() -> None:
    target = BeatmapFetchTarget.from_queue_payload(
        target_type="file:beatmap",
        target_key="2000",
    )

    assert target.kind is BeatmapFetchTargetKind.FILE_BY_BEATMAP_ID
    assert target.is_file_fetch
    assert target.file_beatmap_id() == 2000


def test_metadata_lookup_rejects_file_fetch_target() -> None:
    target = BeatmapFetchTarget.file_by_beatmap_id(2000)

    with pytest.raises(ValueError, match="file fetch target"):
        _ = target.metadata_lookup_target()


def test_beatmap_dataclass_contains_identity_status_source_and_file_fields() -> None:
    expected = {
        "id",
        "beatmapset_id",
        "checksum_md5",
        "mode",
        "version",
        "total_length",
        "hit_length",
        "max_combo",
        "bpm",
        "cs",
        "od",
        "ar",
        "hp",
        "difficulty_rating",
        "official_status",
        "official_status_source",
        "official_status_verified",
        "local_status_override",
        "metadata_fetch_state",
        "file_state",
        "file_attachment",
        "last_fetched_at",
        "next_refresh_at",
    }

    assert hasattr(Beatmap, "__slots__")
    assert {field.name for field in fields(Beatmap)} == expected


def test_effective_status_uses_official_status_without_local_override() -> None:
    beatmap = _make_beatmap(official_status=BeatmapRankStatus.APPROVED)

    assert beatmap.official_status is BeatmapRankStatus.APPROVED
    assert beatmap.local_status_override is None
    assert beatmap.effective_status is BeatmapRankStatus.APPROVED


def test_effective_status_uses_local_override_when_present() -> None:
    beatmap = _make_beatmap(
        official_status=BeatmapRankStatus.PENDING,
        local_status_override=LocalBeatmapStatus.RANKED,
    )

    assert beatmap.official_status is BeatmapRankStatus.PENDING
    assert beatmap.local_status_override is LocalBeatmapStatus.RANKED
    assert beatmap.effective_status is BeatmapRankStatus.RANKED


def test_beatmap_rejects_approved_as_runtime_local_override() -> None:
    with pytest.raises(ValueError, match="Approved cannot be used as a local override"):
        _ = _make_beatmap(
            local_status_override=BeatmapRankStatus.APPROVED,  # pyright: ignore[reportArgumentType]
        )


def test_beatmap_distinguishes_source_and_verification() -> None:
    beatmap = _make_beatmap(
        source=BeatmapMetadataSource.MIRROR,
        source_verification=BeatmapSourceVerification.UNVERIFIED,
    )

    assert beatmap.official_status_source is BeatmapMetadataSource.MIRROR
    assert beatmap.official_status_verified is BeatmapSourceVerification.UNVERIFIED


def test_file_attachment_metadata_references_blob_without_body_bytes() -> None:
    attachment = _make_attachment()
    beatmap = _make_beatmap(file_attachment=attachment)

    assert attachment.id is None
    assert attachment.blob_id == 55
    assert attachment.checksum_md5 == _CHECKSUM
    assert attachment.original_filename == "2000.osu"
    assert not hasattr(attachment, "body")
    assert not hasattr(attachment, "content")
    assert beatmap.file_state is BeatmapFileState.AVAILABLE
    assert beatmap.file_attachment == attachment


def test_file_attachment_preserves_persistent_identity_when_available() -> None:
    attachment = BeatmapFileAttachment(
        beatmap_id=2_000,
        blob_id=55,
        checksum_md5=_CHECKSUM,
        source="official",
        original_filename="2000.osu",
        fetched_at=_NOW,
        verified_at=_NOW,
        id=7,
    )

    assert attachment.id == 7
    assert attachment.blob_id == 55


def test_file_attachment_rejects_non_positive_persistent_identity() -> None:
    with pytest.raises(ValueError, match="id must be positive"):
        _ = BeatmapFileAttachment(
            beatmap_id=2_000,
            blob_id=55,
            checksum_md5=_CHECKSUM,
            source="official",
            original_filename="2000.osu",
            fetched_at=_NOW,
            verified_at=_NOW,
            id=0,
        )


def test_beatmapset_groups_known_beatmaps_and_status_metadata() -> None:
    beatmap = _make_beatmap()
    beatmapset = BeatmapSet(
        id=1_000,
        artist="Camellia",
        title="Exit This Earth's Atomosphere",
        creator="Realazy",
        artist_unicode=None,
        title_unicode=None,
        official_status=BeatmapRankStatus.RANKED,
        official_status_source=BeatmapMetadataSource.OFFICIAL,
        official_status_verified=BeatmapSourceVerification.VERIFIED,
        beatmaps=(beatmap,),
        last_fetched_at=_NOW,
        next_refresh_at=_NEXT_REFRESH,
    )

    assert hasattr(BeatmapSet, "__slots__")
    assert beatmapset.id == 1_000
    assert beatmapset.beatmaps == (beatmap,)
    assert beatmapset.official_status is BeatmapRankStatus.RANKED
    assert beatmapset.official_status_source is BeatmapMetadataSource.OFFICIAL
