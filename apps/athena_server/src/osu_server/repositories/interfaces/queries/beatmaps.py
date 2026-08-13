"""Display と compatibility workflow 用 beatmap read-only repository contract を定義する."""

from __future__ import annotations

from typing import TYPE_CHECKING, Protocol

if TYPE_CHECKING:
    from osu_server.domain.beatmaps import (
        Beatmap,
        BeatmapFetchRecord,
        BeatmapFetchTarget,
        BeatmapFileAttachment,
        BeatmapSet,
        DirectCoverageRecord,
        DirectCoverageStatusScope,
    )


class BeatmapQueryRepository(Protocol):
    """Beatmap read model への read-only access を定義する.

    Notes:
        この Protocol は display と compatibility workflow の参照だけを担う. Beatmap または
        fetch state を変更せず Command Unit of Work を開かず commit/rollback もしない.
    """

    async def get_beatmap(self, beatmap_id: int) -> Beatmap | None:
        """Identifier に対応する Beatmap を返す.

        Args:
            beatmap_id (int): 取得する Beatmap ID.

        Returns:
            Beatmap | None: 対応する Beatmap. 見つからない場合は `None`.
        """
        ...

    async def get_beatmapset(self, beatmapset_id: int) -> BeatmapSet | None:
        """Identifier に対応する BeatmapSet を返す.

        Args:
            beatmapset_id (int): 取得する BeatmapSet ID.

        Returns:
            BeatmapSet | None: 対応する BeatmapSet. 見つからない場合は `None`.
        """
        ...

    async def list_beatmapsets_by_ids(
        self,
        beatmapset_ids: tuple[int, ...],
    ) -> tuple[BeatmapSet, ...]:
        """Identifier列に対応するBeatmapSet列をまとめて返す.

        Args:
            beatmapset_ids (tuple[int, ...]): 取得するBeatmapSet ID列.

        Returns:
            tuple[BeatmapSet, ...]: 入力順に対応するBeatmapSet列. 見つからないIDは省く.
        """
        ...

    async def get_beatmap_by_checksum(self, checksum_md5: str) -> Beatmap | None:
        """MD5 checksum に対応する Beatmap を返す.

        Args:
            checksum_md5 (str): 検索する Beatmap MD5 checksum.

        Returns:
            Beatmap | None: 対応する Beatmap. 見つからない場合は `None`.
        """
        ...

    async def get_beatmap_by_filename_in_beatmapset(
        self, beatmapset_id: int, original_filename: str
    ) -> Beatmap | None:
        """BeatmapSet 内で original filename に一致する Beatmap を返す.

        Args:
            beatmapset_id (int): 検索範囲にする BeatmapSet ID.
            original_filename (str): 検索する original filename.

        Returns:
            Beatmap | None: 一致する Beatmap. 見つからない場合は `None`.
        """
        ...

    async def get_current_file_attachment(self, beatmap_id: int) -> BeatmapFileAttachment | None:
        """Beatmap の current osu file attachment を返す.

        Args:
            beatmap_id (int): Attachment を取得する Beatmap ID.

        Returns:
            BeatmapFileAttachment | None: Current file attachment. 未登録の場合は `None`.
        """
        ...

    async def get_fetch_state(self, target: BeatmapFetchTarget) -> BeatmapFetchRecord | None:
        """Target の metadata または file fetch state を返す.

        Args:
            target (BeatmapFetchTarget): Fetch state を検索する target.

        Returns:
            BeatmapFetchRecord | None: 現在の fetch record. 記録がない場合は `None`.

        Notes:
            この operation は fetch state を作成または更新しない.
        """
        ...

    async def list_completed_direct_search_coverages(
        self,
        status_scopes: tuple[DirectCoverageStatusScope, ...],
        *,
        feed_sort_key: str,
        feed_window_key: str,
    ) -> tuple[DirectCoverageRecord, ...]:
        """完了済みのosu!direct検索用coverageを返す.

        Args:
            status_scopes (tuple[DirectCoverageStatusScope, ...]): 対象にするstatus scope列.
            feed_sort_key (str): 検索request由来feed coverageのsort key.
            feed_window_key (str): 検索request由来feed coverageのwindow key.

        Returns:
            tuple[DirectCoverageRecord, ...]: 完了済みID range coverageと一致feed coverage.
            該当しない場合は空tuple.
        """
        ...
