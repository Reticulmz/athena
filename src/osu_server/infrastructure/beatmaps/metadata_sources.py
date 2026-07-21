"""ビートマップメタデータproviderを優先順位付きで合成する.

公式providerを優先し、通常の未検出または取得失敗時だけmirror providerへ
フォールバックする. 両providerは通常の未検出を ``None`` で表す.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import structlog

if TYPE_CHECKING:
    from osu_server.domain.beatmaps import BeatmapMetadataProvider, BeatmapsetSnapshot

logger: structlog.stdlib.BoundLogger = structlog.get_logger(__name__)  # pyright: ignore[reportAny]


class CompositeBeatmapMetadataProvider:
    """公式providerを優先してメタデータ取得を合成する.

    Attributes:
        _official (BeatmapMetadataProvider): 最初に照会する公式provider.
        _mirror (BeatmapMetadataProvider): 公式providerが結果を返さない場合の代替provider.
    """

    _official: BeatmapMetadataProvider
    _mirror: BeatmapMetadataProvider

    def __init__(
        self,
        *,
        official: BeatmapMetadataProvider,
        mirror: BeatmapMetadataProvider,
    ) -> None:
        """公式providerと代替mirror providerを保持する.

        Args:
            official (BeatmapMetadataProvider): 最優先で照会する公式provider.
            mirror (BeatmapMetadataProvider): 公式providerの未検出または失敗後に照会するprovider.
        """
        self._official = official
        self._mirror = mirror

    async def lookup_by_beatmap_id(self, beatmap_id: int) -> BeatmapsetSnapshot | None:
        """ビートマップIDからスナップショットを優先順位付きで取得する.

        Args:
            beatmap_id (int): 検索対象のビートマップID.

        Returns:
            BeatmapsetSnapshot | None: 取得したスナップショット.
                全providerが未検出または失敗した場合は
                ``None``.
        """
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

    async def lookup_by_beatmapset_id(self, beatmapset_id: int) -> BeatmapsetSnapshot | None:
        """ビートマップセットIDからスナップショットを優先順位付きで取得する.

        Args:
            beatmapset_id (int): 検索対象のビートマップセットID.

        Returns:
            BeatmapsetSnapshot | None: 取得したスナップショット.
                全providerが未検出または失敗した場合は
                ``None``.
        """
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

    async def lookup_by_checksum(self, checksum_md5: str) -> BeatmapsetSnapshot | None:
        """MD5チェックサムからスナップショットを優先順位付きで取得する.

        Args:
            checksum_md5 (str): 検索対象のビートマップMD5チェックサム.

        Returns:
            BeatmapsetSnapshot | None: 取得したスナップショット.
                全providerが未検出または失敗した場合は
                ``None``.
        """
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
