"""Committed in-memory state から Beatmap を読む query adapter を提供する."""

from __future__ import annotations

from typing import TYPE_CHECKING

from osu_server.domain.beatmaps import DirectCoverageKind

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
    from osu_server.repositories.memory.unit_of_work import InMemoryUnitOfWorkFactory


class InMemoryBeatmapQueryRepository:
    """Committed in-memory state を読む read-only Beatmap repository.

    Attributes:
        _factory (InMemoryUnitOfWorkFactory): query ごとの committed snapshot を生成する factory.

    Notes:
        各 query は factory の snapshot だけを読み, factory state を変更しない.
    """

    _factory: InMemoryUnitOfWorkFactory

    def __init__(self, uow_factory: InMemoryUnitOfWorkFactory) -> None:
        """Committed snapshot を取得する factory を保持する.

        Args:
            uow_factory (InMemoryUnitOfWorkFactory): read に使用する committed state factory.
        """
        self._factory = uow_factory

    async def get_beatmap(self, beatmap_id: int) -> Beatmap | None:
        """ID で Beatmap を取得する.

        Args:
            beatmap_id (int): 取得する Beatmap の ID.

        Returns:
            Beatmap | None: snapshot 内の Beatmap. ID がなければ None.
        """
        state = self._factory.snapshot()
        return state.beatmaps_by_id.get(beatmap_id)

    async def get_beatmapset(self, beatmapset_id: int) -> BeatmapSet | None:
        """ID で BeatmapSet を取得する.

        Args:
            beatmapset_id (int): 取得する BeatmapSet の ID.

        Returns:
            BeatmapSet | None: snapshot 内の BeatmapSet. ID がなければ None.
        """
        state = self._factory.snapshot()
        return state.beatmapsets_by_id.get(beatmapset_id)

    async def list_beatmapsets_by_ids(
        self,
        beatmapset_ids: tuple[int, ...],
    ) -> tuple[BeatmapSet, ...]:
        """ID列でBeatmapSetをまとめて取得する.

        Args:
            beatmapset_ids (tuple[int, ...]): 取得するBeatmapSet ID列.

        Returns:
            tuple[BeatmapSet, ...]: snapshot内に存在するBeatmapSetを入力順で返す.
        """
        state = self._factory.snapshot()
        return tuple(
            beatmapset
            for beatmapset_id in beatmapset_ids
            if (beatmapset := state.beatmapsets_by_id.get(beatmapset_id)) is not None
        )

    async def get_beatmap_by_checksum(self, checksum_md5: str) -> Beatmap | None:
        """Checksum MD5 の索引から Beatmap を取得する.

        Args:
            checksum_md5 (str): 検索する Beatmap checksum.

        Returns:
            Beatmap | None: 索引先の Beatmap. checksum または Beatmap がなければ None.
        """
        state = self._factory.snapshot()
        beatmap_id = state.beatmap_id_by_checksum.get(checksum_md5)
        if beatmap_id is None:
            return None
        return state.beatmaps_by_id.get(beatmap_id)

    async def get_beatmap_by_filename_in_beatmapset(
        self, beatmapset_id: int, original_filename: str
    ) -> Beatmap | None:
        """BeatmapSet 内で元 filename が一致する Beatmap を取得する.

        Args:
            beatmapset_id (int): 検索対象 BeatmapSet の ID.
            original_filename (str): 一致させる file attachment の元 filename.

        Returns:
            Beatmap | None: 最初に一致した Beatmap. BeatmapSet または一致 file がなければ None.
        """
        state = self._factory.snapshot()
        beatmapset = state.beatmapsets_by_id.get(beatmapset_id)
        if beatmapset is None:
            return None
        for beatmap in beatmapset.beatmaps:
            attachment = beatmap.file_attachment
            if attachment is not None and attachment.original_filename == original_filename:
                return beatmap
        return None

    async def get_current_file_attachment(self, beatmap_id: int) -> BeatmapFileAttachment | None:
        """Beatmap の最後に記録された file attachment を取得する.

        Args:
            beatmap_id (int): attachment を取得する Beatmap の ID.

        Returns:
            BeatmapFileAttachment | None: attachment key の末尾に対応する attachment.
            key がなければ None.

        Raises:
            KeyError: 最後の attachment key が attachment 索引に存在しない場合.
        """
        state = self._factory.snapshot()
        keys = state.attachment_keys_by_beatmap_id.get(beatmap_id)
        if not keys:
            return None
        return state.attachments_by_key[keys[-1]]

    async def get_fetch_state(self, target: BeatmapFetchTarget) -> BeatmapFetchRecord | None:
        """Fetch target の取得状態を取得する.

        Args:
            target (BeatmapFetchTarget): 状態を読む fetch target.

        Returns:
            BeatmapFetchRecord | None: snapshot 内の fetch record. 記録がなければ None.
        """
        state = self._factory.snapshot()
        return state.fetch_states_by_target.get(target)

    async def list_completed_direct_search_coverages(
        self,
        status_scopes: tuple[DirectCoverageStatusScope, ...],
        *,
        feed_sort_key: str,
        feed_window_key: str,
    ) -> tuple[DirectCoverageRecord, ...]:
        """完了済みのosu!direct検索用coverageを取得する.

        Args:
            status_scopes (tuple[DirectCoverageStatusScope, ...]): 対象にするstatus scope列.
            feed_sort_key (str): 検索request由来feed coverageのsort key.
            feed_window_key (str): 検索request由来feed coverageのwindow key.

        Returns:
            tuple[DirectCoverageRecord, ...]: snapshot内の完了済みID range coverageと
            一致feed coverage.
        """
        scope_set = set(status_scopes)
        state = self._factory.snapshot()
        return tuple(
            record
            for record in state.direct_coverage_records_by_scope.values()
            if record.status_scope in scope_set
            and record.completed_at is not None
            and record.failed_at is None
            and (
                record.coverage_kind is DirectCoverageKind.ID_RANGE
                or (
                    record.coverage_kind is DirectCoverageKind.FEED_WINDOW
                    and record.sort_key == feed_sort_key
                    and record.window_key == feed_window_key
                )
            )
        )
