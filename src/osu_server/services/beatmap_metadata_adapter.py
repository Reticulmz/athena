"""Adapt infrastructure beatmap metadata provider DTOs to domain snapshots."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

import structlog

from osu_server.domain.beatmap import (
    BeatmapMetadataSource,
    BeatmapsetSnapshot,
    BeatmapSnapshot,
    BeatmapSourceVerification,
    map_external_status,
)
from osu_server.infrastructure.beatmaps.contracts import (
    BeatmapMetadataSourceName,
    ProviderBeatmapMetadataProvider,
    ProviderBeatmapsetSnapshot,
)

if TYPE_CHECKING:
    from osu_server.domain.beatmap import BeatmapMetadataProvider

logger: structlog.stdlib.BoundLogger = structlog.get_logger(__name__)  # pyright: ignore[reportAny]


@dataclass(slots=True)
class DomainBeatmapMetadataProviderAdapter:
    """Expose infrastructure metadata providers through the domain provider Protocol."""

    provider: ProviderBeatmapMetadataProvider

    async def lookup_by_beatmap_id(self, beatmap_id: int) -> BeatmapsetSnapshot | None:
        snapshot = await self.provider.lookup_by_beatmap_id(beatmap_id)
        return None if snapshot is None else provider_snapshot_to_domain(snapshot)

    async def lookup_by_beatmapset_id(self, beatmapset_id: int) -> BeatmapsetSnapshot | None:
        snapshot = await self.provider.lookup_by_beatmapset_id(beatmapset_id)
        return None if snapshot is None else provider_snapshot_to_domain(snapshot)

    async def lookup_by_checksum(self, checksum_md5: str) -> BeatmapsetSnapshot | None:
        snapshot = await self.provider.lookup_by_checksum(checksum_md5)
        return None if snapshot is None else provider_snapshot_to_domain(snapshot)


@dataclass(slots=True)
class DomainCompositeBeatmapMetadataProvider:
    """Chain domain metadata providers without owning external I/O behavior."""

    official: BeatmapMetadataProvider
    mirror: BeatmapMetadataProvider

    async def lookup_by_beatmap_id(self, beatmap_id: int) -> BeatmapsetSnapshot | None:
        key = str(beatmap_id)
        try:
            result = await self.official.lookup_by_beatmap_id(beatmap_id)
            if result is not None:
                return result
        except Exception:
            logger.debug(
                "beatmap_metadata_lookup_failed",
                key_kind="beatmap_id",
                key=key,
                exc_info=True,
            )
        return await self._lookup_mirror_by_beatmap_id(beatmap_id, key)

    async def lookup_by_beatmapset_id(self, beatmapset_id: int) -> BeatmapsetSnapshot | None:
        key = str(beatmapset_id)
        try:
            result = await self.official.lookup_by_beatmapset_id(beatmapset_id)
            if result is not None:
                return result
        except Exception:
            logger.debug(
                "beatmap_metadata_lookup_failed",
                key_kind="beatmapset_id",
                key=key,
                exc_info=True,
            )
        return await self._lookup_mirror_by_beatmapset_id(beatmapset_id, key)

    async def lookup_by_checksum(self, checksum_md5: str) -> BeatmapsetSnapshot | None:
        try:
            result = await self.official.lookup_by_checksum(checksum_md5)
            if result is not None:
                return result
        except Exception:
            logger.debug(
                "beatmap_metadata_lookup_failed",
                key_kind="checksum_md5",
                key=checksum_md5,
                exc_info=True,
            )
        return await self._lookup_mirror_by_checksum(checksum_md5)

    async def _lookup_mirror_by_beatmap_id(
        self, beatmap_id: int, key: str
    ) -> BeatmapsetSnapshot | None:
        try:
            result = await self.mirror.lookup_by_beatmap_id(beatmap_id)
        except Exception:
            logger.debug(
                "beatmap_metadata_lookup_failed",
                key_kind="beatmap_id",
                key=key,
                exc_info=True,
            )
            return None
        _log_metadata_fallback(result, key_kind="beatmap_id", key=key)
        return result

    async def _lookup_mirror_by_beatmapset_id(
        self, beatmapset_id: int, key: str
    ) -> BeatmapsetSnapshot | None:
        try:
            result = await self.mirror.lookup_by_beatmapset_id(beatmapset_id)
        except Exception:
            logger.debug(
                "beatmap_metadata_lookup_failed",
                key_kind="beatmapset_id",
                key=key,
                exc_info=True,
            )
            return None
        _log_metadata_fallback(result, key_kind="beatmapset_id", key=key)
        return result

    async def _lookup_mirror_by_checksum(self, checksum_md5: str) -> BeatmapsetSnapshot | None:
        try:
            result = await self.mirror.lookup_by_checksum(checksum_md5)
        except Exception:
            logger.debug(
                "beatmap_metadata_lookup_failed",
                key_kind="checksum_md5",
                key=checksum_md5,
                exc_info=True,
            )
            return None
        _log_metadata_fallback(result, key_kind="checksum_md5", key=checksum_md5)
        return result


class DomainInMemoryBeatmapMetadataProvider:
    """In-memory domain metadata provider for service and E2E tests."""

    def __init__(self) -> None:
        self._by_beatmap_id: dict[int, BeatmapsetSnapshot] = {}
        self._by_beatmapset_id: dict[int, BeatmapsetSnapshot] = {}
        self._checksum_to_beatmap_id: dict[str, int] = {}

    def add_snapshot(self, snapshot: BeatmapsetSnapshot) -> None:
        self._by_beatmapset_id[snapshot.beatmapset_id] = snapshot
        for beatmap in snapshot.beatmaps:
            self._by_beatmap_id[beatmap.beatmap_id] = snapshot
            self._checksum_to_beatmap_id[beatmap.checksum_md5] = beatmap.beatmap_id

    async def lookup_by_beatmap_id(self, beatmap_id: int) -> BeatmapsetSnapshot | None:
        return self._by_beatmap_id.get(beatmap_id)

    async def lookup_by_beatmapset_id(self, beatmapset_id: int) -> BeatmapsetSnapshot | None:
        return self._by_beatmapset_id.get(beatmapset_id)

    async def lookup_by_checksum(self, checksum_md5: str) -> BeatmapsetSnapshot | None:
        beatmap_id = self._checksum_to_beatmap_id.get(checksum_md5)
        if beatmap_id is None:
            return None
        return self._by_beatmap_id.get(beatmap_id)


def provider_snapshot_to_domain(snapshot: ProviderBeatmapsetSnapshot) -> BeatmapsetSnapshot:
    beatmaps = tuple(
        BeatmapSnapshot(
            beatmap_id=beatmap.beatmap_id,
            beatmapset_id=beatmap.beatmapset_id,
            checksum_md5=beatmap.checksum_md5,
            mode=beatmap.mode,
            version=beatmap.version,
            official_status=map_external_status(beatmap.official_status),
            official_status_source=_source_to_domain(beatmap.official_status_source),
            official_status_verified=_verification_to_domain(beatmap.official_status_verified),
            total_length=beatmap.total_length,
            hit_length=beatmap.hit_length,
            max_combo=beatmap.max_combo,
            bpm=beatmap.bpm,
            cs=beatmap.cs,
            od=beatmap.od,
            ar=beatmap.ar,
            hp=beatmap.hp,
            difficulty_rating=beatmap.difficulty_rating,
            last_fetched_at=beatmap.last_fetched_at,
            next_refresh_at=beatmap.next_refresh_at,
        )
        for beatmap in snapshot.beatmaps
    )
    return BeatmapsetSnapshot(
        beatmapset_id=snapshot.beatmapset_id,
        artist=snapshot.artist,
        title=snapshot.title,
        creator=snapshot.creator,
        source=_source_to_domain(snapshot.source),
        verified=_verification_to_domain(snapshot.verified),
        official_status=map_external_status(snapshot.official_status),
        official_status_source=_source_to_domain(snapshot.official_status_source),
        official_status_verified=_verification_to_domain(snapshot.official_status_verified),
        beatmaps=beatmaps,
        artist_unicode=snapshot.artist_unicode,
        title_unicode=snapshot.title_unicode,
        last_fetched_at=snapshot.last_fetched_at,
        next_refresh_at=snapshot.next_refresh_at,
    )


def _log_metadata_fallback(result: BeatmapsetSnapshot | None, *, key_kind: str, key: str) -> None:
    if result is None:
        return
    logger.info(
        "beatmap_mirror_fallback_used",
        source_type="metadata",
        key_kind=key_kind,
        key=key,
    )


def _source_to_domain(source: BeatmapMetadataSourceName) -> BeatmapMetadataSource:
    match source:
        case BeatmapMetadataSourceName.OFFICIAL:
            return BeatmapMetadataSource.OFFICIAL
        case BeatmapMetadataSourceName.LEGACY_OFFICIAL:
            return BeatmapMetadataSource.LEGACY_OFFICIAL
        case BeatmapMetadataSourceName.MIRROR:
            return BeatmapMetadataSource.MIRROR


def _verification_to_domain(verified: bool) -> BeatmapSourceVerification:
    if verified:
        return BeatmapSourceVerification.VERIFIED
    return BeatmapSourceVerification.UNVERIFIED
