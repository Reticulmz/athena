"""Tests for beatmap metadata provider contracts and status mapping.

TDD: RED phase first, then GREEN.
"""

from __future__ import annotations

import inspect
from dataclasses import FrozenInstanceError
from datetime import UTC, datetime, timedelta

import pytest

from osu_server.domain.beatmaps import (
    BeatmapMetadataProvider,
    BeatmapMetadataSource,
    BeatmapRankStatus,
    BeatmapsetSnapshot,
    BeatmapSnapshot,
    BeatmapSourceError,
    BeatmapSourceErrorCategory,
    BeatmapSourceVerification,
    LocalBeatmapStatus,
    map_external_status,
)
from osu_server.infrastructure.beatmaps.mappers import (
    beatmap_json_to_snapshot,
    beatmap_v1_json_to_snapshot,
)
from osu_server.infrastructure.beatmaps.metadata_sources import (
    CompositeBeatmapMetadataProvider,
)
from tests.factories.beatmap import (
    FakeBeatmapMetadataProvider,
    FakeProviderResultKind,
    make_metadata_provider_response,
)

# ---------------------------------------------------------------------------
# Status mapping tests (exhaustive)
# ---------------------------------------------------------------------------


class TestMapExternalStatus:
    """External status string to BeatmapRankStatus mapping."""

    def test_ranked(self) -> None:
        assert map_external_status("ranked") is BeatmapRankStatus.RANKED

    def test_approved(self) -> None:
        assert map_external_status("approved") is BeatmapRankStatus.APPROVED

    def test_loved(self) -> None:
        assert map_external_status("loved") is BeatmapRankStatus.LOVED

    def test_qualified(self) -> None:
        assert map_external_status("qualified") is BeatmapRankStatus.QUALIFIED

    def test_pending(self) -> None:
        assert map_external_status("pending") is BeatmapRankStatus.PENDING

    def test_wip(self) -> None:
        assert map_external_status("wip") is BeatmapRankStatus.WIP

    def test_graveyard(self) -> None:
        assert map_external_status("graveyard") is BeatmapRankStatus.GRAVEYARD

    def test_unknown_string_returns_unknown(self) -> None:
        assert map_external_status("unknown") is BeatmapRankStatus.UNKNOWN

    def test_nonexistent_status_returns_unknown(self) -> None:
        assert map_external_status("some_future_category") is BeatmapRankStatus.UNKNOWN

    def test_empty_string_returns_unknown(self) -> None:
        assert map_external_status("") is BeatmapRankStatus.UNKNOWN

    def test_case_insensitive(self) -> None:
        """External status strings from osu! API are case-insensitive."""
        assert map_external_status("RANKED") is BeatmapRankStatus.RANKED
        assert map_external_status("Ranked") is BeatmapRankStatus.RANKED
        assert map_external_status("GRAVEYARD") is BeatmapRankStatus.GRAVEYARD
        assert map_external_status("Loved") is BeatmapRankStatus.LOVED

    def test_whitespace_handling(self) -> None:
        """Leading/trailing whitespace is stripped."""
        assert map_external_status("  ranked  ") is BeatmapRankStatus.RANKED
        assert map_external_status("\tpending\n") is BeatmapRankStatus.PENDING

    def test_all_known_statuses_are_mapped(self) -> None:
        """Every known external status string maps to a non-UNKNOWN rank status."""
        known = {"ranked", "approved", "loved", "qualified", "pending", "wip", "graveyard"}
        for status_str in known:
            result = map_external_status(status_str)
            assert result is not BeatmapRankStatus.UNKNOWN, (
                f"Expected {status_str} to map to a known status, got UNKNOWN"
            )


# ---------------------------------------------------------------------------
# BeatmapSnapshot tests
# ---------------------------------------------------------------------------


class TestBeatmapSnapshot:
    """BeatmapSnapshot dataclass creation and immutability."""

    def test_creation_with_required_fields(self) -> None:
        now = datetime.now(UTC)
        snap = BeatmapSnapshot(
            beatmap_id=2000,
            beatmapset_id=1000,
            checksum_md5="a1b2c3d4e5f6a7b8c9d0e1f2a3b4c5d6",
            mode="osu",
            version="Another",
            official_status=BeatmapRankStatus.RANKED,
            official_status_source=BeatmapMetadataSource.OFFICIAL,
            official_status_verified=BeatmapSourceVerification.VERIFIED,
            last_fetched_at=now,
            next_refresh_at=now + timedelta(days=30),
        )
        assert snap.beatmap_id == 2000
        assert snap.beatmapset_id == 1000
        assert snap.mode == "osu"
        assert snap.version == "Another"
        assert snap.official_status is BeatmapRankStatus.RANKED

    def test_default_values(self) -> None:
        """Optional fields default to None."""
        snap = BeatmapSnapshot(
            beatmap_id=2000,
            beatmapset_id=1000,
            checksum_md5="a1b2c3d4e5f6a7b8c9d0e1f2a3b4c5d6",
            mode="osu",
            version="Normal",
            official_status=BeatmapRankStatus.UNKNOWN,
            official_status_source=BeatmapMetadataSource.OFFICIAL,
            official_status_verified=BeatmapSourceVerification.UNVERIFIED,
        )
        assert snap.local_status_override is None
        assert snap.total_length is None
        assert snap.hit_length is None
        assert snap.max_combo is None
        assert snap.bpm is None
        assert snap.cs is None
        assert snap.od is None
        assert snap.ar is None
        assert snap.hp is None
        assert snap.difficulty_rating is None
        assert snap.last_fetched_at is None
        assert snap.next_refresh_at is None
        assert snap.official_last_updated_at is None

    def test_frozen_immutable(self) -> None:
        snap = BeatmapSnapshot(
            beatmap_id=2000,
            beatmapset_id=1000,
            checksum_md5="a1b2c3d4e5f6a7b8c9d0e1f2a3b4c5d6",
            mode="osu",
            version="Normal",
            official_status=BeatmapRankStatus.UNKNOWN,
            official_status_source=BeatmapMetadataSource.OFFICIAL,
            official_status_verified=BeatmapSourceVerification.UNVERIFIED,
        )
        with pytest.raises(FrozenInstanceError):
            snap.beatmap_id = 9999  # pyright: ignore[reportAttributeAccessIssue]

    def test_gameplay_stats_accept_none(self) -> None:
        """Gameplay stats can be None (e.g. mirror doesn't provide them)."""
        snap = BeatmapSnapshot(
            beatmap_id=2000,
            beatmapset_id=1000,
            checksum_md5="a1b2c3d4e5f6a7b8c9d0e1f2a3b4c5d6",
            mode="osu",
            version="Expert",
            official_status=BeatmapRankStatus.RANKED,
            official_status_source=BeatmapMetadataSource.OFFICIAL,
            official_status_verified=BeatmapSourceVerification.VERIFIED,
            cs=4.5,
            od=8.0,
            ar=9.2,
        )
        assert snap.cs == 4.5
        assert snap.od == 8.0
        assert snap.ar == 9.2
        assert snap.hp is None
        assert snap.bpm is None

    def test_local_status_override_preserved(self) -> None:
        """Local status override survives snapshot creation."""
        snap = BeatmapSnapshot(
            beatmap_id=2000,
            beatmapset_id=1000,
            checksum_md5="a1b2c3d4e5f6a7b8c9d0e1f2a3b4c5d6",
            mode="osu",
            version="Insane",
            official_status=BeatmapRankStatus.GRAVEYARD,
            official_status_source=BeatmapMetadataSource.OFFICIAL,
            official_status_verified=BeatmapSourceVerification.VERIFIED,
            local_status_override=LocalBeatmapStatus.LOVED,
        )
        assert snap.local_status_override is LocalBeatmapStatus.LOVED

    def test_invalid_checksum_raises(self) -> None:
        with pytest.raises(ValueError, match="checksum_md5"):
            _ = BeatmapSnapshot(
                beatmap_id=2000,
                beatmapset_id=1000,
                checksum_md5="not-a-valid-md5",
                mode="osu",
                version="Normal",
                official_status=BeatmapRankStatus.UNKNOWN,
                official_status_source=BeatmapMetadataSource.OFFICIAL,
                official_status_verified=BeatmapSourceVerification.UNVERIFIED,
            )

    def test_equals_by_value(self) -> None:
        """Two snapshots with identical fields should be equal."""
        a = BeatmapSnapshot(
            beatmap_id=2000,
            beatmapset_id=1000,
            checksum_md5="a1b2c3d4e5f6a7b8c9d0e1f2a3b4c5d6",
            mode="osu",
            version="Normal",
            official_status=BeatmapRankStatus.RANKED,
            official_status_source=BeatmapMetadataSource.OFFICIAL,
            official_status_verified=BeatmapSourceVerification.VERIFIED,
        )
        b = BeatmapSnapshot(
            beatmap_id=2000,
            beatmapset_id=1000,
            checksum_md5="a1b2c3d4e5f6a7b8c9d0e1f2a3b4c5d6",
            mode="osu",
            version="Normal",
            official_status=BeatmapRankStatus.RANKED,
            official_status_source=BeatmapMetadataSource.OFFICIAL,
            official_status_verified=BeatmapSourceVerification.VERIFIED,
        )
        assert a == b


class TestBeatmapMetadataMapper:
    """External beatmap metadata date fields."""

    def test_v1_last_update_maps_to_official_last_updated_at(self) -> None:
        snapshot = beatmap_v1_json_to_snapshot(
            [
                {
                    "beatmap_id": "2000",
                    "beatmapset_id": "1000",
                    "file_md5": "a1b2c3d4e5f6a7b8c9d0e1f2a3b4c5d6",
                    "mode": "0",
                    "version": "Insane",
                    "approved": "1",
                    "artist": "Camellia",
                    "title": "Exit This Earth's Atomosphere",
                    "creator": "Realazy",
                    "last_update": "2026-06-29 12:34:56",
                }
            ],
            now=datetime(2026, 6, 30, tzinfo=UTC),
        )

        assert snapshot is not None
        assert snapshot.beatmaps[0].official_last_updated_at == datetime(
            2026, 6, 29, 12, 34, 56, tzinfo=UTC
        )

    def test_v2_last_updated_maps_to_official_last_updated_at(self) -> None:
        snapshot = beatmap_json_to_snapshot(
            {
                "id": 1000,
                "artist": "Camellia",
                "title": "Exit This Earth's Atomosphere",
                "creator": "Realazy",
                "status": "ranked",
                "last_updated": "2026-06-28T00:00:00Z",
                "beatmaps": [
                    {
                        "id": 2000,
                        "beatmapset_id": 1000,
                        "checksum": "a1b2c3d4e5f6a7b8c9d0e1f2a3b4c5d6",
                        "mode": "osu",
                        "version": "Insane",
                        "status": "ranked",
                        "last_updated": "2026-06-29T12:34:56Z",
                    },
                    {
                        "id": 2001,
                        "beatmapset_id": 1000,
                        "checksum": "ffffffffffffffffffffffffffffffff",
                        "mode": "osu",
                        "version": "Another",
                        "status": "ranked",
                    },
                ],
            },
            now=datetime(2026, 6, 30, tzinfo=UTC),
        )

        assert snapshot.beatmaps[0].official_last_updated_at == datetime(
            2026, 6, 29, 12, 34, 56, tzinfo=UTC
        )
        assert snapshot.beatmaps[1].official_last_updated_at == datetime(2026, 6, 28, tzinfo=UTC)


# ---------------------------------------------------------------------------
# BeatmapsetSnapshot tests
# ---------------------------------------------------------------------------


class TestBeatmapsetSnapshot:
    """BeatmapsetSnapshot dataclass creation and immutability."""

    def test_creation_with_required_fields(self) -> None:
        now = datetime.now(UTC)
        child = BeatmapSnapshot(
            beatmap_id=2000,
            beatmapset_id=1000,
            checksum_md5="a1b2c3d4e5f6a7b8c9d0e1f2a3b4c5d6",
            mode="osu",
            version="Another",
            official_status=BeatmapRankStatus.RANKED,
            official_status_source=BeatmapMetadataSource.OFFICIAL,
            official_status_verified=BeatmapSourceVerification.VERIFIED,
        )
        snap = BeatmapsetSnapshot(
            beatmapset_id=1000,
            artist="Camellia",
            title="Exit This Earth's Atomosphere",
            creator="Realazy",
            source=BeatmapMetadataSource.OFFICIAL,
            verified=BeatmapSourceVerification.VERIFIED,
            official_status=BeatmapRankStatus.RANKED,
            official_status_source=BeatmapMetadataSource.OFFICIAL,
            official_status_verified=BeatmapSourceVerification.VERIFIED,
            beatmaps=(child,),
            last_fetched_at=now,
            next_refresh_at=now + timedelta(days=30),
        )
        assert snap.beatmapset_id == 1000
        assert snap.artist == "Camellia"
        assert snap.title == "Exit This Earth's Atomosphere"
        assert snap.creator == "Realazy"
        assert snap.source is BeatmapMetadataSource.OFFICIAL
        assert snap.verified is BeatmapSourceVerification.VERIFIED
        assert len(snap.beatmaps) == 1

    def test_source_mirror_unverified(self) -> None:
        """Mirror-sourced snapshots carry UNVERIFIED verification."""
        child = BeatmapSnapshot(
            beatmap_id=9999,
            beatmapset_id=8888,
            checksum_md5="ffffffffffffffffffffffffffffffff",
            mode="osu",
            version="Normal",
            official_status=BeatmapRankStatus.RANKED,
            official_status_source=BeatmapMetadataSource.MIRROR,
            official_status_verified=BeatmapSourceVerification.UNVERIFIED,
        )
        snap = BeatmapsetSnapshot(
            beatmapset_id=8888,
            artist="Unknown Artist",
            title="Unknown Title",
            creator="Unknown Creator",
            source=BeatmapMetadataSource.MIRROR,
            verified=BeatmapSourceVerification.UNVERIFIED,
            official_status=BeatmapRankStatus.RANKED,
            official_status_source=BeatmapMetadataSource.MIRROR,
            official_status_verified=BeatmapSourceVerification.UNVERIFIED,
            beatmaps=(child,),
        )
        assert snap.source is BeatmapMetadataSource.MIRROR
        assert snap.verified is BeatmapSourceVerification.UNVERIFIED
        assert snap.official_status_source is BeatmapMetadataSource.MIRROR

    def test_official_source_verified(self) -> None:
        """Official-sourced snapshots carry VERIFIED verification."""
        child = BeatmapSnapshot(
            beatmap_id=2000,
            beatmapset_id=1000,
            checksum_md5="a1b2c3d4e5f6a7b8c9d0e1f2a3b4c5d6",
            mode="osu",
            version="Another",
            official_status=BeatmapRankStatus.RANKED,
            official_status_source=BeatmapMetadataSource.OFFICIAL,
            official_status_verified=BeatmapSourceVerification.VERIFIED,
        )
        snap = BeatmapsetSnapshot(
            beatmapset_id=1000,
            artist="Camellia",
            title="Exit This Earth's Atomosphere",
            creator="Realazy",
            source=BeatmapMetadataSource.OFFICIAL,
            verified=BeatmapSourceVerification.VERIFIED,
            official_status=BeatmapRankStatus.RANKED,
            official_status_source=BeatmapMetadataSource.OFFICIAL,
            official_status_verified=BeatmapSourceVerification.VERIFIED,
            beatmaps=(child,),
        )
        assert snap.source is BeatmapMetadataSource.OFFICIAL
        assert snap.verified is BeatmapSourceVerification.VERIFIED

    def test_frozen_immutable(self) -> None:
        child = BeatmapSnapshot(
            beatmap_id=2000,
            beatmapset_id=1000,
            checksum_md5="a1b2c3d4e5f6a7b8c9d0e1f2a3b4c5d6",
            mode="osu",
            version="Normal",
            official_status=BeatmapRankStatus.UNKNOWN,
            official_status_source=BeatmapMetadataSource.OFFICIAL,
            official_status_verified=BeatmapSourceVerification.UNVERIFIED,
        )
        snap = BeatmapsetSnapshot(
            beatmapset_id=1000,
            artist="Test",
            title="Test",
            creator="Test",
            source=BeatmapMetadataSource.OFFICIAL,
            verified=BeatmapSourceVerification.VERIFIED,
            official_status=BeatmapRankStatus.UNKNOWN,
            official_status_source=BeatmapMetadataSource.OFFICIAL,
            official_status_verified=BeatmapSourceVerification.UNVERIFIED,
            beatmaps=(child,),
        )
        with pytest.raises(FrozenInstanceError):
            snap.artist = "Changed"  # pyright: ignore[reportAttributeAccessIssue]

    def test_multiple_beatmaps(self) -> None:
        """A beatmapset snapshot can contain multiple difficulty beatmaps."""
        b1 = BeatmapSnapshot(
            beatmap_id=2000,
            beatmapset_id=1000,
            checksum_md5="a1b2c3d4e5f6a7b8c9d0e1f2a3b4c5d6",
            mode="osu",
            version="Easy",
            official_status=BeatmapRankStatus.RANKED,
            official_status_source=BeatmapMetadataSource.OFFICIAL,
            official_status_verified=BeatmapSourceVerification.VERIFIED,
        )
        b2 = BeatmapSnapshot(
            beatmap_id=2001,
            beatmapset_id=1000,
            checksum_md5="b2c3d4e5f6a7b8c9d0e1f2a3b4c5d6a1",
            mode="osu",
            version="Hard",
            official_status=BeatmapRankStatus.RANKED,
            official_status_source=BeatmapMetadataSource.OFFICIAL,
            official_status_verified=BeatmapSourceVerification.VERIFIED,
        )
        snap = BeatmapsetSnapshot(
            beatmapset_id=1000,
            artist="Camellia",
            title="Test",
            creator="Mapper",
            source=BeatmapMetadataSource.OFFICIAL,
            verified=BeatmapSourceVerification.VERIFIED,
            official_status=BeatmapRankStatus.RANKED,
            official_status_source=BeatmapMetadataSource.OFFICIAL,
            official_status_verified=BeatmapSourceVerification.VERIFIED,
            beatmaps=(b1, b2),
        )
        assert len(snap.beatmaps) == 2
        assert snap.beatmaps[0].beatmap_id == 2000
        assert snap.beatmaps[1].beatmap_id == 2001

    def test_unicode_fields_default_none(self) -> None:
        """artist_unicode and title_unicode default to None."""
        child = BeatmapSnapshot(
            beatmap_id=2000,
            beatmapset_id=1000,
            checksum_md5="a1b2c3d4e5f6a7b8c9d0e1f2a3b4c5d6",
            mode="osu",
            version="Normal",
            official_status=BeatmapRankStatus.UNKNOWN,
            official_status_source=BeatmapMetadataSource.OFFICIAL,
            official_status_verified=BeatmapSourceVerification.UNVERIFIED,
        )
        snap = BeatmapsetSnapshot(
            beatmapset_id=1000,
            artist="Artist",
            title="Title",
            creator="Creator",
            source=BeatmapMetadataSource.OFFICIAL,
            verified=BeatmapSourceVerification.VERIFIED,
            official_status=BeatmapRankStatus.UNKNOWN,
            official_status_source=BeatmapMetadataSource.OFFICIAL,
            official_status_verified=BeatmapSourceVerification.UNVERIFIED,
            beatmaps=(child,),
        )
        assert snap.artist_unicode is None
        assert snap.title_unicode is None

    def test_equals_by_value(self) -> None:
        child = BeatmapSnapshot(
            beatmap_id=2000,
            beatmapset_id=1000,
            checksum_md5="a1b2c3d4e5f6a7b8c9d0e1f2a3b4c5d6",
            mode="osu",
            version="Normal",
            official_status=BeatmapRankStatus.RANKED,
            official_status_source=BeatmapMetadataSource.OFFICIAL,
            official_status_verified=BeatmapSourceVerification.VERIFIED,
        )
        a = BeatmapsetSnapshot(
            beatmapset_id=1000,
            artist="A",
            title="T",
            creator="C",
            source=BeatmapMetadataSource.OFFICIAL,
            verified=BeatmapSourceVerification.VERIFIED,
            official_status=BeatmapRankStatus.RANKED,
            official_status_source=BeatmapMetadataSource.OFFICIAL,
            official_status_verified=BeatmapSourceVerification.VERIFIED,
            beatmaps=(child,),
        )
        child2 = BeatmapSnapshot(
            beatmap_id=2000,
            beatmapset_id=1000,
            checksum_md5="a1b2c3d4e5f6a7b8c9d0e1f2a3b4c5d6",
            mode="osu",
            version="Normal",
            official_status=BeatmapRankStatus.RANKED,
            official_status_source=BeatmapMetadataSource.OFFICIAL,
            official_status_verified=BeatmapSourceVerification.VERIFIED,
        )
        b = BeatmapsetSnapshot(
            beatmapset_id=1000,
            artist="A",
            title="T",
            creator="C",
            source=BeatmapMetadataSource.OFFICIAL,
            verified=BeatmapSourceVerification.VERIFIED,
            official_status=BeatmapRankStatus.RANKED,
            official_status_source=BeatmapMetadataSource.OFFICIAL,
            official_status_verified=BeatmapSourceVerification.VERIFIED,
            beatmaps=(child2,),
        )
        assert a == b


# ---------------------------------------------------------------------------
# BeatmapMetadataProvider Protocol tests
# ---------------------------------------------------------------------------


class TestBeatmapMetadataProviderProtocol:
    """BeatmapMetadataProvider Protocol structural checks."""

    def test_protocol_is_runtime_checkable(self) -> None:
        """BeatmapMetadataProvider must be runtime_checkable."""
        assert hasattr(BeatmapMetadataProvider, "_is_runtime_protocol")

    def test_protocol_has_expected_methods(self) -> None:
        """Protocol must define the three lookup methods."""
        assert hasattr(BeatmapMetadataProvider, "lookup_by_beatmap_id")
        assert hasattr(BeatmapMetadataProvider, "lookup_by_beatmapset_id")
        assert hasattr(BeatmapMetadataProvider, "lookup_by_checksum")

    def test_fake_provider_satisfies_domain_protocol(self) -> None:
        """Domain fake provider satisfies the domain Protocol."""
        assert isinstance(FakeBeatmapMetadataProvider(), BeatmapMetadataProvider)

    def test_composite_satisfies_provider_protocol(self) -> None:
        """CompositeBeatmapMetadataProvider satisfies the infrastructure Protocol."""
        provider = CompositeBeatmapMetadataProvider(
            official=_make_null_provider(),
            mirror=_make_null_provider(),
        )
        assert isinstance(provider, BeatmapMetadataProvider)


# ---------------------------------------------------------------------------
# CompositeBeatmapMetadataProvider chain tests
# ---------------------------------------------------------------------------


class TestCompositeBeatmapMetadataProvider:
    """CompositeBeatmapMetadataProvider chains official -> mirror."""

    async def test_official_success_does_not_try_mirror(self) -> None:
        """When official returns a snapshot, mirror is not called."""
        official = _CountingProvider("official", _make_provider_test_snapshot(beatmapset_id=1000))
        mirror = _CountingProvider("mirror", None)

        composite = CompositeBeatmapMetadataProvider(official=official, mirror=mirror)
        result = await composite.lookup_by_beatmap_id(2000)

        assert result is not None
        assert result.beatmapset_id == 1000
        assert official.lookup_by_beatmap_id_calls == 1
        assert mirror.lookup_by_beatmap_id_calls == 0

    async def test_official_none_falls_back_to_mirror(self) -> None:
        """When official returns None, mirror is tried."""
        official = _CountingProvider("official", None)
        mirror = _CountingProvider("mirror", _make_provider_test_snapshot(beatmapset_id=8888))

        composite = CompositeBeatmapMetadataProvider(official=official, mirror=mirror)
        result = await composite.lookup_by_beatmap_id(9999)

        assert result is not None
        assert result.beatmapset_id == 8888
        assert official.lookup_by_beatmap_id_calls == 1
        assert mirror.lookup_by_beatmap_id_calls == 1

    async def test_both_return_none(self) -> None:
        """When both providers return None, composite returns None."""
        official = _CountingProvider("official", None)
        mirror = _CountingProvider("mirror", None)

        composite = CompositeBeatmapMetadataProvider(official=official, mirror=mirror)
        result = await composite.lookup_by_beatmapset_id(5000)

        assert result is None
        assert official.lookup_by_beatmapset_id_calls == 1
        assert mirror.lookup_by_beatmapset_id_calls == 1

    async def test_official_exception_falls_back_to_mirror(self) -> None:
        """When official raises, mirror is still tried."""
        official = _RaisingProvider(
            "official",
            BeatmapSourceError(
                category=BeatmapSourceErrorCategory.TIMEOUT,
                source="official",
                lookup_key="2000",
                message="timeout",
            ),
        )
        mirror = _CountingProvider("mirror", _make_provider_test_snapshot(beatmapset_id=7777))

        composite = CompositeBeatmapMetadataProvider(official=official, mirror=mirror)
        result = await composite.lookup_by_beatmap_id(2000)

        assert result is not None
        assert result.beatmapset_id == 7777

    async def test_both_raise_returns_none(self) -> None:
        """When both providers raise, composite returns None."""
        official = _RaisingProvider(
            "official",
            BeatmapSourceError(
                category=BeatmapSourceErrorCategory.TIMEOUT,
                source="official",
                lookup_key="2000",
                message="timeout",
            ),
        )
        mirror = _RaisingProvider(
            "mirror",
            BeatmapSourceError(
                category=BeatmapSourceErrorCategory.NOT_FOUND,
                source="mirror",
                lookup_key="2000",
                message="not found",
            ),
        )

        composite = CompositeBeatmapMetadataProvider(official=official, mirror=mirror)
        result = await composite.lookup_by_checksum("a1b2c3d4e5f6a7b8c9d0e1f2a3b4c5d6")

        assert result is None

    async def test_lookup_by_beatmap_id_delegates(self) -> None:
        """lookup_by_beatmap_id delegates to the correct method on sub-providers."""
        official = _CountingProvider("official", _make_provider_test_snapshot(beatmapset_id=1000))
        mirror = _CountingProvider("mirror", None)

        composite = CompositeBeatmapMetadataProvider(official=official, mirror=mirror)
        _ = await composite.lookup_by_beatmap_id(2000)

        assert official.last_called_method == "lookup_by_beatmap_id"

    async def test_lookup_by_beatmapset_id_delegates(self) -> None:
        """lookup_by_beatmapset_id delegates to the correct method."""
        official = _CountingProvider("official", None)
        mirror = _CountingProvider("mirror", _make_provider_test_snapshot(beatmapset_id=1000))

        composite = CompositeBeatmapMetadataProvider(official=official, mirror=mirror)
        _ = await composite.lookup_by_beatmapset_id(1000)

        assert official.last_called_method == "lookup_by_beatmapset_id"
        assert mirror.last_called_method == "lookup_by_beatmapset_id"

    async def test_lookup_by_checksum_delegates(self) -> None:
        """lookup_by_checksum delegates to the correct method."""
        official = _CountingProvider("official", None)
        mirror = _CountingProvider("mirror", None)

        composite = CompositeBeatmapMetadataProvider(official=official, mirror=mirror)
        _ = await composite.lookup_by_checksum("a1b2c3d4e5f6a7b8c9d0e1f2a3b4c5d6")

        assert official.last_called_method == "lookup_by_checksum"
        assert mirror.last_called_method == "lookup_by_checksum"


# ---------------------------------------------------------------------------
# BeatmapSourceError tests
# ---------------------------------------------------------------------------


class TestBeatmapSourceError:
    """BeatmapSourceError source failure categories."""

    def test_configuration_category(self) -> None:
        err = BeatmapSourceError(
            category=BeatmapSourceErrorCategory.CONFIGURATION,
            source="official",
            lookup_key="N/A",
            message="missing API key",
        )
        assert err.category is BeatmapSourceErrorCategory.CONFIGURATION
        assert "missing API key" in str(err)

    def test_unauthorized_category(self) -> None:
        err = BeatmapSourceError(
            category=BeatmapSourceErrorCategory.UNAUTHORIZED,
            source="official",
            lookup_key="2000",
            message="invalid credentials",
        )
        assert err.category is BeatmapSourceErrorCategory.UNAUTHORIZED

    def test_rate_limited_category(self) -> None:
        err = BeatmapSourceError(
            category=BeatmapSourceErrorCategory.RATE_LIMITED,
            source="official",
            lookup_key="2000",
            message="rate limit exceeded",
        )
        assert err.category is BeatmapSourceErrorCategory.RATE_LIMITED

    def test_timeout_category(self) -> None:
        err = BeatmapSourceError(
            category=BeatmapSourceErrorCategory.TIMEOUT,
            source="official",
            lookup_key="2000",
            message="request timed out",
        )
        assert err.category is BeatmapSourceErrorCategory.TIMEOUT

    def test_temporary_unavailable_category(self) -> None:
        err = BeatmapSourceError(
            category=BeatmapSourceErrorCategory.TEMPORARY_UNAVAILABLE,
            source="official",
            lookup_key="2000",
            message="503 Service Unavailable",
        )
        assert err.category is BeatmapSourceErrorCategory.TEMPORARY_UNAVAILABLE

    def test_not_found_category(self) -> None:
        err = BeatmapSourceError(
            category=BeatmapSourceErrorCategory.NOT_FOUND,
            source="official",
            lookup_key="2000",
            message="404 Not Found",
        )
        assert err.category is BeatmapSourceErrorCategory.NOT_FOUND

    def test_invalid_response_category(self) -> None:
        err = BeatmapSourceError(
            category=BeatmapSourceErrorCategory.INVALID_RESPONSE,
            source="official",
            lookup_key="2000",
            message="unexpected JSON structure",
        )
        assert err.category is BeatmapSourceErrorCategory.INVALID_RESPONSE

    def test_carries_source_and_lookup_key(self) -> None:
        err = BeatmapSourceError(
            category=BeatmapSourceErrorCategory.TIMEOUT,
            source="mirror",
            lookup_key="abc123",
            message="timed out",
        )
        assert err.source == "mirror"
        assert err.lookup_key == "abc123"

    def test_carries_original_exception(self) -> None:
        original = ValueError("some underlying error")
        err = BeatmapSourceError(
            category=BeatmapSourceErrorCategory.INVALID_RESPONSE,
            source="official",
            lookup_key="2000",
            message="parse failure",
            original_error=original,
        )
        assert err.original_error is original

    def test_original_error_defaults_to_none(self) -> None:
        err = BeatmapSourceError(
            category=BeatmapSourceErrorCategory.NOT_FOUND,
            source="official",
            lookup_key="2000",
            message="not found",
        )
        assert err.original_error is None


# ---------------------------------------------------------------------------
# FakeBeatmapMetadataProvider Protocol compatibility
# ---------------------------------------------------------------------------


class TestFakeBeatmapMetadataProviderProtocol:
    """Verify FakeBeatmapMetadataProvider from factories is structurally compatible."""

    def test_has_expected_method_names(self) -> None:

        fake = FakeBeatmapMetadataProvider()
        assert hasattr(fake, "lookup_by_beatmap_id")
        assert hasattr(fake, "lookup_by_beatmapset_id")
        assert hasattr(fake, "lookup_by_checksum")

    def test_methods_are_async(self) -> None:

        fake = FakeBeatmapMetadataProvider()
        assert inspect.iscoroutinefunction(fake.lookup_by_beatmap_id)
        assert inspect.iscoroutinefunction(fake.lookup_by_beatmapset_id)
        assert inspect.iscoroutinefunction(fake.lookup_by_checksum)

    def test_methods_accept_correct_parameters(self) -> None:

        fake = FakeBeatmapMetadataProvider()
        sig_bid = inspect.signature(fake.lookup_by_beatmap_id)
        sig_bsid = inspect.signature(fake.lookup_by_beatmapset_id)
        sig_ck = inspect.signature(fake.lookup_by_checksum)

        assert "beatmap_id" in sig_bid.parameters
        assert "beatmapset_id" in sig_bsid.parameters
        assert "checksum_md5" in sig_ck.parameters

    def test_returns_response_with_snapshot_for_success(self) -> None:
        """Fake provider response contains a snapshot via FakeMetadataProviderResponse."""
        snap = make_metadata_provider_response(kind=FakeProviderResultKind.SUCCESS)
        fake = FakeBeatmapMetadataProvider(by_beatmap_id={2000: snap})
        assert 2000 in fake.by_beatmap_id
        assert fake.by_beatmap_id[2000].kind is FakeProviderResultKind.SUCCESS

    def test_default_response_is_not_found(self) -> None:
        """Default response for unmapped keys is NOT_FOUND."""

        fake = FakeBeatmapMetadataProvider()
        assert fake.default_response.kind.value == "not_found"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_provider_test_snapshot(beatmapset_id: int = 1000) -> BeatmapsetSnapshot:
    """Create a minimal provider-side snapshot for infrastructure provider tests."""
    now = datetime.now(UTC)
    child = BeatmapSnapshot(
        beatmap_id=beatmapset_id * 2,
        beatmapset_id=beatmapset_id,
        checksum_md5="a1b2c3d4e5f6a7b8c9d0e1f2a3b4c5d6",
        mode="osu",
        version="Normal",
        official_status=BeatmapRankStatus.RANKED,
        official_status_source=BeatmapMetadataSource.OFFICIAL,
        official_status_verified=BeatmapSourceVerification.VERIFIED,
        last_fetched_at=now,
    )
    return BeatmapsetSnapshot(
        beatmapset_id=beatmapset_id,
        artist="Test Artist",
        title="Test Title",
        creator="Test Creator",
        source=BeatmapMetadataSource.OFFICIAL,
        verified=BeatmapSourceVerification.VERIFIED,
        official_status=BeatmapRankStatus.RANKED,
        official_status_source=BeatmapMetadataSource.OFFICIAL,
        official_status_verified=BeatmapSourceVerification.VERIFIED,
        beatmaps=(child,),
        last_fetched_at=now,
        next_refresh_at=now + timedelta(days=30),
    )


class _CountingProvider:
    """Provider that returns a fixed snapshot and records call counts."""

    name: str
    response: BeatmapsetSnapshot | None
    lookup_by_beatmap_id_calls: int
    lookup_by_beatmapset_id_calls: int
    lookup_by_checksum_calls: int
    last_called_method: str | None

    def __init__(self, name: str, response: BeatmapsetSnapshot | None) -> None:
        self.name = name
        self.response = response
        self.lookup_by_beatmap_id_calls = 0
        self.lookup_by_beatmapset_id_calls = 0
        self.lookup_by_checksum_calls = 0
        self.last_called_method = None

    async def lookup_by_beatmap_id(
        self,
        beatmap_id: int,  # noqa: ARG002  # pyright: ignore[reportUnusedParameter]
    ) -> BeatmapsetSnapshot | None:
        self.lookup_by_beatmap_id_calls += 1
        self.last_called_method = "lookup_by_beatmap_id"
        return self.response

    async def lookup_by_beatmapset_id(
        self,
        beatmapset_id: int,  # noqa: ARG002  # pyright: ignore[reportUnusedParameter]
    ) -> BeatmapsetSnapshot | None:
        self.lookup_by_beatmapset_id_calls += 1
        self.last_called_method = "lookup_by_beatmapset_id"
        return self.response

    async def lookup_by_checksum(
        self,
        checksum_md5: str,  # noqa: ARG002  # pyright: ignore[reportUnusedParameter]
    ) -> BeatmapsetSnapshot | None:
        self.lookup_by_checksum_calls += 1
        self.last_called_method = "lookup_by_checksum"
        return self.response


class _RaisingProvider:
    """Provider that always raises the given exception."""

    name: str
    exception: Exception

    def __init__(self, name: str, exception: Exception) -> None:
        self.name = name
        self.exception = exception

    async def lookup_by_beatmap_id(
        self,
        beatmap_id: int,  # noqa: ARG002  # pyright: ignore[reportUnusedParameter]
    ) -> BeatmapsetSnapshot | None:
        raise self.exception

    async def lookup_by_beatmapset_id(
        self,
        beatmapset_id: int,  # noqa: ARG002  # pyright: ignore[reportUnusedParameter]
    ) -> BeatmapsetSnapshot | None:
        raise self.exception

    async def lookup_by_checksum(
        self,
        checksum_md5: str,  # noqa: ARG002  # pyright: ignore[reportUnusedParameter]
    ) -> BeatmapsetSnapshot | None:
        raise self.exception


def _make_null_provider() -> _CountingProvider:
    """Return a provider that always returns None."""
    return _CountingProvider("null", None)
