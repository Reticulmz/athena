"""Concrete ``BeatmapMetadataProvider`` implementations.

Provides:
    * ``InMemoryBeatmapMetadataProvider`` -- stores snapshots in memory for test environments.
    * ``OsuApiMetadataProvider`` -- placeholder official API provider (not yet implemented).
    * ``MirrorMetadataProvider`` -- placeholder mirror API provider (not yet implemented).
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import structlog

if TYPE_CHECKING:
    from osu_server.domain.beatmap import BeatmapsetSnapshot

logger: structlog.stdlib.BoundLogger = structlog.get_logger(__name__)  # pyright: ignore[reportAny]


class InMemoryBeatmapMetadataProvider:
    """Stores ``BeatmapsetSnapshot`` data in dicts for test environments.

    Snapshots can be preloaded via ``add_snapshot()`` so that composition
    tests and integration tests can arrange known beatmap data without
    real external credentials.
    """

    def __init__(self) -> None:
        self._by_beatmap_id: dict[int, BeatmapsetSnapshot] = {}
        self._by_beatmapset_id: dict[int, BeatmapsetSnapshot] = {}
        self._checksum_to_beatmap_id: dict[str, int] = {}

    def add_snapshot(self, snapshot: BeatmapsetSnapshot) -> None:
        """Preload a snapshot so lookups return it."""
        self._by_beatmapset_id[snapshot.beatmapset_id] = snapshot
        for bm in snapshot.beatmaps:
            self._by_beatmap_id[bm.beatmap_id] = snapshot
            if bm.checksum_md5:
                self._checksum_to_beatmap_id[bm.checksum_md5] = bm.beatmap_id

    async def lookup_by_beatmap_id(self, beatmap_id: int) -> BeatmapsetSnapshot | None:
        return self._by_beatmap_id.get(beatmap_id)

    async def lookup_by_beatmapset_id(self, beatmapset_id: int) -> BeatmapsetSnapshot | None:
        return self._by_beatmapset_id.get(beatmapset_id)

    async def lookup_by_checksum(self, checksum_md5: str) -> BeatmapsetSnapshot | None:
        beatmap_id = self._checksum_to_beatmap_id.get(checksum_md5)
        if beatmap_id is None:
            return None
        return self._by_beatmap_id.get(beatmap_id)


class OsuApiMetadataProvider:
    """Placeholder official osu! API metadata provider.

    Returns ``None`` for all lookups.  Real API integration will be added
    once a license-compatible osu! API client is selected.
    """

    async def lookup_by_beatmap_id(self, beatmap_id: int) -> BeatmapsetSnapshot | None:
        logger.debug("osu_api_metadata_provider_not_implemented", beatmap_id=beatmap_id)
        return None

    async def lookup_by_beatmapset_id(self, beatmapset_id: int) -> BeatmapsetSnapshot | None:
        logger.debug("osu_api_metadata_provider_not_implemented", beatmapset_id=beatmapset_id)
        return None

    async def lookup_by_checksum(self, checksum_md5: str) -> BeatmapsetSnapshot | None:
        logger.debug("osu_api_metadata_provider_not_implemented", checksum_md5=checksum_md5)
        return None


class MirrorMetadataProvider:
    """Placeholder mirror API metadata provider.

    Returns ``None`` for all lookups.  Real mirror integration will be added
    once the mirror endpoint configuration is finalized.
    """

    async def lookup_by_beatmap_id(self, beatmap_id: int) -> BeatmapsetSnapshot | None:
        logger.debug("mirror_metadata_provider_not_implemented", beatmap_id=beatmap_id)
        return None

    async def lookup_by_beatmapset_id(self, beatmapset_id: int) -> BeatmapsetSnapshot | None:
        logger.debug("mirror_metadata_provider_not_implemented", beatmapset_id=beatmapset_id)
        return None

    async def lookup_by_checksum(self, checksum_md5: str) -> BeatmapsetSnapshot | None:
        logger.debug("mirror_metadata_provider_not_implemented", checksum_md5=checksum_md5)
        return None
