"""Beatmap refresh workflow の command-side repository 契約."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Protocol, runtime_checkable

if TYPE_CHECKING:
    from datetime import datetime

    from osu_server.domain.beatmaps import (
        Beatmap,
        BeatmapFetchRecord,
        BeatmapFetchTarget,
        BeatmapFileAttachment,
        BeatmapSet,
        BeatmapSetSearchDocument,
        DirectCoverageRecord,
        DirectExternalIndexState,
        LocalBeatmapStatus,
    )


@dataclass(frozen=True, slots=True)
class BeatmapSubmissionCounts:
    """Beatmap 単位の submitted play/pass count.

    Attributes:
        play_count (int): 送信済み play の非負累積件数.
        pass_count (int): 送信済み pass の非負累積件数.play_count を超えない.
    """

    play_count: int
    pass_count: int

    def __post_init__(self) -> None:
        """Count として不正な値を拒否する.

        Returns:
            None: Play/pass count が集計制約を満たすことを示す.

        Raises:
            ValueError: いずれかの count が負の場合,または pass_count が play_count を
                超える場合に送出する.
        """
        if self.play_count < 0:
            msg = "play_count must be non-negative"
            raise ValueError(msg)
        if self.pass_count < 0:
            msg = "pass_count must be non-negative"
            raise ValueError(msg)
        if self.pass_count > self.play_count:
            msg = "pass_count must not exceed play_count"
            raise ValueError(msg)


@runtime_checkable
class BeatmapCommandRepository(Protocol):
    """Beatmap refresh workflow の mutation と consistency-check port.

    Notes:
        Runtime 実装は command Unit of Work から取得する.各操作は同じ Unit of Work が
        所有する transaction に参加し,この repository 自身は commit または rollback を
        実行しない.
    """

    async def get_beatmap(self, beatmap_id: int) -> Beatmap | None:
        """Command-side consistency check 用に Beatmap を返す.

        Args:
            beatmap_id (int): 取得する Beatmap ID.

        Returns:
            Beatmap | None: 一致する Beatmap.存在しない場合は None.
        """
        ...

    async def get_beatmapset(self, beatmapset_id: int) -> BeatmapSet | None:
        """Command-side consistency check 用に BeatmapSet を返す.

        Args:
            beatmapset_id (int): 取得する BeatmapSet ID.

        Returns:
            BeatmapSet | None: 一致する BeatmapSet.存在しない場合は None.
        """
        ...

    async def get_beatmap_by_checksum(self, checksum_md5: str) -> Beatmap | None:
        """Command-side consistency check 用に checksum から Beatmap を返す.

        Args:
            checksum_md5 (str): 検索する Beatmap の MD5 checksum.

        Returns:
            Beatmap | None: 一致する Beatmap.存在しない場合は None.
        """
        ...

    async def get_beatmap_by_filename_in_beatmapset(
        self, beatmapset_id: int, original_filename: str
    ) -> Beatmap | None:
        """Command check 用に BeatmapSet 内の filename から Beatmap を返す.

        Args:
            beatmapset_id (int): 検索範囲となる BeatmapSet ID.
            original_filename (str): BeatmapSet 内で照合する元の filename.

        Returns:
            Beatmap | None: 範囲内で一致する Beatmap.存在しない場合は None.
        """
        ...

    async def save_beatmapset_snapshot(self, snapshot: BeatmapSet) -> None:
        """取得済み BeatmapSet snapshot を永続化する.

        Args:
            snapshot (BeatmapSet): 保存する取得済み BeatmapSet snapshot.

        Returns:
            None: Snapshot の保存が Unit of Work に反映されたことを示す.

        Raises:
            ValueError: Snapshot 内または保存済み Beatmap と,同じ checksum を異なる Beatmap ID に
                対応付けようとした場合に送出する.
        """
        ...

    async def save_beatmapset_snapshot_returning_previous(
        self,
        snapshot: BeatmapSet,
    ) -> BeatmapSet | None:
        """取得済みBeatmapSet snapshotを保存し保存前の値を返す.

        Args:
            snapshot (BeatmapSet): 保存する取得済みBeatmapSet snapshot.

        Returns:
            BeatmapSet | None: 保存前のBeatmapSet. 初回保存ではNone.

        Raises:
            ValueError: Snapshot 内または保存済み Beatmap と,同じ checksum を異なる Beatmap ID に
                対応付けようとした場合に送出する.
        """
        ...

    async def get_search_document(self, beatmapset_id: int) -> BeatmapSetSearchDocument | None:
        """External indexing用に保存済み検索projectionを返す.

        Args:
            beatmapset_id (int): 取得するbeatmapset検索projectionの識別子.

        Returns:
            BeatmapSetSearchDocument | None: 保存済みprojection. 存在しない場合はNone.
        """
        ...

    async def list_search_documents(
        self,
        *,
        after_beatmapset_id: int = 0,
        limit: int | None = None,
    ) -> tuple[BeatmapSetSearchDocument, ...]:
        """External index rebuild用に検索projectionを列挙する.

        Args:
            after_beatmapset_id (int): このBeatmapSet IDより大きいprojectionだけを返す.
            limit (int | None): 返す最大件数. Noneなら全件を返す.

        Returns:
            tuple[BeatmapSetSearchDocument, ...]: beatmapset ID順の検索projection.
        """
        ...

    async def rebuild_search_projection(self, *, now: datetime) -> int:
        """保存済みmetadataから検索projectionを再構築する.

        Args:
            now (datetime): 変更されたprojectionへ設定するUTC timestamp.

        Returns:
            int: 再構築対象として処理したbeatmapset数.
        """
        ...

    async def record_index_state(self, state: DirectExternalIndexState) -> None:
        """External index documentの同期状態を記録する.

        Args:
            state (DirectExternalIndexState): 保存するsuccessまたはfailure state.

        Returns:
            None: stateがUnit of Workへ反映されたことを示す.
        """
        ...

    async def set_local_status_override(
        self, beatmap_id: int, status: LocalBeatmapStatus | None
    ) -> Beatmap:
        """Local Beatmap status override を永続化する.

        Args:
            beatmap_id (int): Override する Beatmap ID.
            status (LocalBeatmapStatus | None): 設定する local status.None の場合は override を
                解除する.

        Returns:
            Beatmap: 更新後の Beatmap.

        Raises:
            LookupError: beatmap_id に対応する Beatmap が存在しない場合に送出する.
        """
        ...

    async def increment_submission_counts(
        self,
        beatmap_id: int,
        *,
        passed: bool,
    ) -> BeatmapSubmissionCounts:
        """Submitted play/pass count を増やし,更新後の値を返す.

        Args:
            beatmap_id (int): Count を増やす Beatmap ID.
            passed (bool): Pass count も増やす成功 submission かどうか.

        Returns:
            BeatmapSubmissionCounts: 増分を反映した play/pass count.

        Raises:
            LookupError: 永続化対象の Beatmap が存在せず,count increment を実行できない場合に
                送出する.
        """
        ...

    async def get_current_file_attachment(self, beatmap_id: int) -> BeatmapFileAttachment | None:
        """Command-side check 用に現在の file attachment を返す.

        Args:
            beatmap_id (int): Attachment を取得する Beatmap ID.

        Returns:
            BeatmapFileAttachment | None: 現在の attachment.未登録時は None.
        """
        ...

    async def attach_osu_file(self, attachment: BeatmapFileAttachment) -> BeatmapFileAttachment:
        """Osu file blob を Beatmap に関連付ける.

        Args:
            attachment (BeatmapFileAttachment): 保存する Beatmap と blob の関連付け.

        Returns:
            BeatmapFileAttachment: 永続化後の attachment.

        Raises:
            LookupError: attachment が参照する Beatmap が存在しない場合に送出する.
        """
        ...

    async def get_fetch_state(self, target: BeatmapFetchTarget) -> BeatmapFetchRecord | None:
        """Command-side concurrency check 用に fetch state を返す.

        Args:
            target (BeatmapFetchTarget): 状態を取得する fetch target.

        Returns:
            BeatmapFetchRecord | None: 現在の fetch state.未登録時は None.
        """
        ...

    async def try_mark_fetch_pending(self, target: BeatmapFetchTarget, now: datetime) -> bool:
        """Fetch target を work 用に claim する.

        Args:
            target (BeatmapFetchTarget): Claim を試行する fetch target.
            now (datetime): Pending 状態を記録する現在日時.

        Returns:
            bool: Work を claim できた場合は True.既存状態により claim できない場合は False.
        """
        ...

    async def mark_fetch_succeeded(self, target: BeatmapFetchTarget, now: datetime) -> None:
        """Fetch target を成功完了として記録する.

        Args:
            target (BeatmapFetchTarget): 成功完了にする fetch target.
            now (datetime): 成功日時.

        Returns:
            None: 成功状態が Unit of Work に反映されたことを示す.
        """
        ...

    async def mark_fetch_failed(
        self, target: BeatmapFetchTarget, reason: str, now: datetime
    ) -> None:
        """Fetch target を失敗として記録する.

        Args:
            target (BeatmapFetchTarget): 失敗にする fetch target.
            reason (str): Operator が確認できる失敗理由.
            now (datetime): 失敗日時.

        Returns:
            None: 失敗状態が Unit of Work に反映されたことを示す.
        """
        ...

    async def record_direct_coverage(self, record: DirectCoverageRecord) -> None:
        """osu!direct catalog coverage recordを保存する.

        Args:
            record (DirectCoverageRecord): feed windowまたはid range crawlのcoverage record.

        Returns:
            None: coverage stateがUnit of Workへ反映されたことを示す.
        """
        ...
