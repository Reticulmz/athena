"""Legacy getscores 向けの in-memory Beatmap query adapter を提供する."""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from osu_server.domain.beatmaps import (
        Beatmap,
        BeatmapFetchRecord,
        BeatmapFetchTarget,
        BeatmapSet,
    )
    from osu_server.repositories.interfaces.queries.beatmaps import BeatmapQueryRepository


class InMemoryBeatmapScoreListingQueryRepository:
    """Read-only Beatmap query repository を getscores 用に公開する adapter.

    Attributes:
        _beatmaps (BeatmapQueryRepository): Beatmap と取得状態を読む委譲先.

    Notes:
        自身では state を保持または変更せず, 委譲先の戻り値をそのまま返す.
    """

    def __init__(self, beatmaps: BeatmapQueryRepository) -> None:
        """Beatmap query repository を委譲先として保持する.

        Args:
            beatmaps (BeatmapQueryRepository): getscores read に使用する Beatmap repository.

        Returns:
            None: 委譲先を保持する adapter を構築する.
        """
        self._beatmaps: BeatmapQueryRepository = beatmaps

    async def find_by_checksum(self, checksum_md5: str) -> Beatmap | None:
        """Checksum MD5 で Beatmap を検索する.

        Args:
            checksum_md5 (str): 検索する Beatmap checksum.

        Returns:
            Beatmap | None: 委譲先が返す Beatmap. 見つからなければ None.
        """
        return await self._beatmaps.get_beatmap_by_checksum(checksum_md5)

    async def find_by_filename_in_beatmapset(
        self, beatmapset_id: int, original_filename: str
    ) -> Beatmap | None:
        """BeatmapSet 内の元 filename で Beatmap を検索する.

        Args:
            beatmapset_id (int): 検索対象 BeatmapSet の ID.
            original_filename (str): 添付 file の元 filename.

        Returns:
            Beatmap | None: 委譲先が返す一致 Beatmap. 見つからなければ None.
        """
        return await self._beatmaps.get_beatmap_by_filename_in_beatmapset(
            beatmapset_id,
            original_filename,
        )

    async def get_beatmapset(self, beatmapset_id: int) -> BeatmapSet | None:
        """ID で BeatmapSet を取得する.

        Args:
            beatmapset_id (int): 取得する BeatmapSet の ID.

        Returns:
            BeatmapSet | None: 委譲先が返す BeatmapSet. 見つからなければ None.
        """
        return await self._beatmaps.get_beatmapset(beatmapset_id)

    async def get_fetch_state(self, target: BeatmapFetchTarget) -> BeatmapFetchRecord | None:
        """Fetch target の現在の取得状態を取得する.

        Args:
            target (BeatmapFetchTarget): 状態を読む fetch target.

        Returns:
            BeatmapFetchRecord | None: 委譲先が返す取得状態. 記録がなければ None.
        """
        return await self._beatmaps.get_fetch_state(target)
