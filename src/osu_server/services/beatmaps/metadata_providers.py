"""Beatmap metadata provider implementations.

CompositeBeatmapMetadataProvider chains official and mirror providers:
official first, mirror as fallback. Both are expected to return None
on normal lookup failures rather than raising.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import structlog

if TYPE_CHECKING:
    from osu_server.domain.beatmap import BeatmapMetadataProvider, BeatmapsetSnapshot

logger: structlog.stdlib.BoundLogger = structlog.get_logger(__name__)  # pyright: ignore[reportAny]


class CompositeBeatmapMetadataProvider:
    """Chains official and mirror providers with official-first priority.

    If the official provider returns a snapshot, the mirror provider
    is never called. If the official provider returns ``None`` or raises
    an exception, the mirror provider is tried. If both fail, ``None``
    is returned.
    """

    _official: BeatmapMetadataProvider
    _mirror: BeatmapMetadataProvider

    def __init__(
        self,
        *,
        official: BeatmapMetadataProvider,
        mirror: BeatmapMetadataProvider,
    ) -> None:
        self._official = official
        self._mirror = mirror

    async def lookup_by_beatmap_id(self, beatmap_id: int) -> BeatmapsetSnapshot | None:
        try:
            result = await self._official.lookup_by_beatmap_id(beatmap_id)
            if result is not None:
                return result
        except Exception:
            logger.debug(
                "beatmap_metadata_lookup_failed",
                key_kind="beatmap_id",
                key=str(beatmap_id),
                exc_info=True,
            )
        try:
            return await self._mirror.lookup_by_beatmap_id(beatmap_id)
        except Exception:
            logger.debug(
                "beatmap_metadata_lookup_failed",
                key_kind="beatmap_id",
                key=str(beatmap_id),
                exc_info=True,
            )
            return None

    async def lookup_by_beatmapset_id(self, beatmapset_id: int) -> BeatmapsetSnapshot | None:
        try:
            result = await self._official.lookup_by_beatmapset_id(beatmapset_id)
            if result is not None:
                return result
        except Exception:
            logger.debug(
                "beatmap_metadata_lookup_failed",
                key_kind="beatmapset_id",
                key=str(beatmapset_id),
                exc_info=True,
            )
        try:
            return await self._mirror.lookup_by_beatmapset_id(beatmapset_id)
        except Exception:
            logger.debug(
                "beatmap_metadata_lookup_failed",
                key_kind="beatmapset_id",
                key=str(beatmapset_id),
                exc_info=True,
            )
            return None

    async def lookup_by_checksum(self, checksum_md5: str) -> BeatmapsetSnapshot | None:
        try:
            result = await self._official.lookup_by_checksum(checksum_md5)
            if result is not None:
                return result
        except Exception:
            logger.debug(
                "beatmap_metadata_lookup_failed",
                key_kind="checksum_md5",
                key=checksum_md5,
                exc_info=True,
            )
        try:
            return await self._mirror.lookup_by_checksum(checksum_md5)
        except Exception:
            logger.debug(
                "beatmap_metadata_lookup_failed",
                key_kind="checksum_md5",
                key=checksum_md5,
                exc_info=True,
            )
            return None
