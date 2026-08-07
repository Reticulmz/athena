"""Legacy getscores response 用 beatmap read-only repository contract を定義する."""

from __future__ import annotations

from typing import TYPE_CHECKING, Protocol

if TYPE_CHECKING:
    from osu_server.domain.beatmaps import (
        Beatmap,
        BeatmapFetchRecord,
        BeatmapFetchTarget,
        BeatmapSet,
    )


class BeatmapScoreListingQueryRepository(Protocol):
    """Stable getscores response の beatmap 解決用 read-only port を定義する.

    Notes:
        この Protocol は response construction 用の read model を返すだけである. Beatmap
        metadata や fetch state を変更せず Command Unit of Work の transaction を開始または
        commit/rollback しない.
    """

    async def find_by_checksum(self, checksum_md5: str) -> Beatmap | None:
        """Stable client checksum に一致する Beatmap を返す.

        Args:
            checksum_md5 (str): Stable client が送った Beatmap MD5 checksum.

        Returns:
            Beatmap | None: 一致する Beatmap. 見つからない場合は `None`.
        """
        ...

    async def find_by_filename_in_beatmapset(
        self, beatmapset_id: int, original_filename: str
    ) -> Beatmap | None:
        """BeatmapSet 内で original filename に一致する Beatmap を返す.

        Args:
            beatmapset_id (int): 検索範囲にする BeatmapSet ID.
            original_filename (str): Stable client が参照する original filename.

        Returns:
            Beatmap | None: 一致する Beatmap. 見つからない場合は `None`.
        """
        ...

    async def get_beatmapset(self, beatmapset_id: int) -> BeatmapSet | None:
        """Response header construction 用の BeatmapSet を返す.

        Args:
            beatmapset_id (int): 取得する BeatmapSet ID.

        Returns:
            BeatmapSet | None: 対応する BeatmapSet. 見つからない場合は `None`.
        """
        ...

    async def get_fetch_state(self, target: BeatmapFetchTarget) -> BeatmapFetchRecord | None:
        """Fetch target の現在の取得 state を返す.

        Args:
            target (BeatmapFetchTarget): 取得 state を検索する target.

        Returns:
            BeatmapFetchRecord | None: 現在の fetch record. 記録がない場合は `None`.

        Notes:
            この operation は fetch state を作成または更新しない.
        """
        ...
