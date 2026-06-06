"""Beatmap metadata provider implementations.

CompositeBeatmapMetadataProvider chains official and mirror providers:
official first, mirror as fallback. Both are expected to return None
on normal lookup misses rather than raising.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import structlog

if TYPE_CHECKING:
    from osu_server.infrastructure.beatmaps.contracts import (
        ProviderBeatmapMetadataProvider,
        ProviderBeatmapsetSnapshot,
    )

logger: structlog.stdlib.BoundLogger = structlog.get_logger(__name__)  # pyright: ignore[reportAny]


class CompositeBeatmapMetadataProvider:
    """Chains official and mirror providers with official-first priority."""

    _official: ProviderBeatmapMetadataProvider
    _mirror: ProviderBeatmapMetadataProvider

    def __init__(
        self,
        *,
        official: ProviderBeatmapMetadataProvider,
        mirror: ProviderBeatmapMetadataProvider,
    ) -> None:
        self._official = official
        self._mirror = mirror

    async def lookup_by_beatmap_id(self, beatmap_id: int) -> ProviderBeatmapsetSnapshot | None:
        key = str(beatmap_id)
        official_failed = False
        try:
            result = await self._official.lookup_by_beatmap_id(beatmap_id)
            if result is not None:
                return result
            official_failed = True
        except Exception:
            official_failed = True
            logger.debug(
                "beatmap_metadata_lookup_failed",
                key_kind="beatmap_id",
                key=key,
                exc_info=True,
            )
        try:
            mirror_result = await self._mirror.lookup_by_beatmap_id(beatmap_id)
        except Exception:
            logger.debug(
                "beatmap_metadata_lookup_failed",
                key_kind="beatmap_id",
                key=key,
                exc_info=True,
            )
            return None
        else:
            if mirror_result is not None and official_failed:
                logger.info(
                    "beatmap_mirror_fallback_used",
                    source_type="metadata",
                    key_kind="beatmap_id",
                    key=key,
                )
            return mirror_result

    async def lookup_by_beatmapset_id(
        self, beatmapset_id: int
    ) -> ProviderBeatmapsetSnapshot | None:
        key = str(beatmapset_id)
        official_failed = False
        try:
            result = await self._official.lookup_by_beatmapset_id(beatmapset_id)
            if result is not None:
                return result
            official_failed = True
        except Exception:
            official_failed = True
            logger.debug(
                "beatmap_metadata_lookup_failed",
                key_kind="beatmapset_id",
                key=key,
                exc_info=True,
            )
        try:
            mirror_result = await self._mirror.lookup_by_beatmapset_id(beatmapset_id)
        except Exception:
            logger.debug(
                "beatmap_metadata_lookup_failed",
                key_kind="beatmapset_id",
                key=key,
                exc_info=True,
            )
            return None
        else:
            if mirror_result is not None and official_failed:
                logger.info(
                    "beatmap_mirror_fallback_used",
                    source_type="metadata",
                    key_kind="beatmapset_id",
                    key=key,
                )
            return mirror_result

    async def lookup_by_checksum(self, checksum_md5: str) -> ProviderBeatmapsetSnapshot | None:
        official_failed = False
        try:
            result = await self._official.lookup_by_checksum(checksum_md5)
            if result is not None:
                return result
            official_failed = True
        except Exception:
            official_failed = True
            logger.debug(
                "beatmap_metadata_lookup_failed",
                key_kind="checksum_md5",
                key=checksum_md5,
                exc_info=True,
            )
        try:
            mirror_result = await self._mirror.lookup_by_checksum(checksum_md5)
        except Exception:
            logger.debug(
                "beatmap_metadata_lookup_failed",
                key_kind="checksum_md5",
                key=checksum_md5,
                exc_info=True,
            )
            return None
        else:
            if mirror_result is not None and official_failed:
                logger.info(
                    "beatmap_mirror_fallback_used",
                    source_type="metadata",
                    key_kind="checksum_md5",
                    key=checksum_md5,
                )
            return mirror_result
