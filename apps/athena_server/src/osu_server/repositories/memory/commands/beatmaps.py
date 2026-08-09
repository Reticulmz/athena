"""In-memory command 側 beatmap repository を実装する module."""

from __future__ import annotations

from dataclasses import replace
from typing import TYPE_CHECKING

from osu_server.domain.beatmaps import (
    BeatmapFetchRecord,
    BeatmapFetchState,
    BeatmapFetchTarget,
    BeatmapFileState,
    BeatmapSetSearchDocument,
    DirectExternalIndexState,
    build_beatmapset_search_document,
)
from osu_server.repositories.interfaces.commands.beatmaps import BeatmapSubmissionCounts
from osu_server.repositories.memory.commands.state import now_utc

if TYPE_CHECKING:
    from datetime import datetime

    from osu_server.domain.beatmaps import (
        Beatmap,
        BeatmapFileAttachment,
        BeatmapSet,
        LocalBeatmapStatus,
    )
    from osu_server.repositories.memory.commands.state import InMemoryCommandRepositoryState


class DuplicateBeatmapChecksumError(ValueError):
    """一つの MD5 checksum が複数 beatmap に割り当てられたことを示す.

    Attributes:
        checksum_md5 (str): 重複を検出した MD5 checksum.
        existing_beatmap_id (int): checksum をすでに所有する beatmap ID.
    """

    checksum_md5: str
    existing_beatmap_id: int

    def __init__(self, *, checksum_md5: str, existing_beatmap_id: int) -> None:
        """重複する checksum と既存 beatmap ID を保持して例外を初期化する.

        Args:
            checksum_md5 (str): 新たに保存しようとした MD5 checksum.
            existing_beatmap_id (int): checksum を所有する既存 beatmap ID.
        """
        self.checksum_md5 = checksum_md5
        self.existing_beatmap_id = existing_beatmap_id
        super().__init__(
            f"checksum {checksum_md5} already belongs to beatmap {existing_beatmap_id}"
        )


class BeatmapNotFoundError(LookupError):
    """必須の beatmap が state に存在しないことを示す."""

    def __init__(self, beatmap_id: int) -> None:
        """未登録 beatmap ID を含む LookupError message を初期化する.

        Args:
            beatmap_id (int): 見つからなかった beatmap の識別子.
        """
        super().__init__(f"beatmap {beatmap_id} was not found")


class InMemoryBeatmapCommandRepository:
    """Beatmap snapshot, file attachment, fetch state を command 用に管理する.

    Attributes:
        _state (InMemoryCommandRepositoryState): 所有 Unit of Work の可変 state snapshot.

    Notes:
        この repository は lock 又は thread synchronization を提供しない. 同じ state を
        複数 task 又は thread から同時に変更してはならない.
    """

    def __init__(self, state: InMemoryCommandRepositoryState) -> None:
        """Active Unit of Work の state snapshot を保持する.

        Args:
            state (InMemoryCommandRepositoryState): repository が直接読み書きする state.

        Notes:
            state は clone せずに保持する. caller は state の排他所有を保証する必要がある.
        """
        self._state: InMemoryCommandRepositoryState = state

    async def get_beatmap(self, beatmap_id: int) -> Beatmap | None:
        """Beatmap ID から保存済み beatmap を返す.

        Args:
            beatmap_id (int): 検索する beatmap の識別子.

        Returns:
            Beatmap | None: 保存済み beatmap. 未登録なら None.
        """
        return self._state.beatmaps_by_id.get(beatmap_id)

    async def get_beatmapset(self, beatmapset_id: int) -> BeatmapSet | None:
        """Beatmapset ID から保存済み beatmapset snapshot を返す.

        Args:
            beatmapset_id (int): 検索する beatmapset の識別子.

        Returns:
            BeatmapSet | None: 保存済み beatmapset. 未登録なら None.
        """
        return self._state.beatmapsets_by_id.get(beatmapset_id)

    async def get_beatmap_by_checksum(self, checksum_md5: str) -> Beatmap | None:
        """MD5 checksum から保存済み beatmap を返す.

        Args:
            checksum_md5 (str): 検索する beatmap の MD5 checksum.

        Returns:
            Beatmap | None: index と主記録が存在する beatmap. 未登録又は不整合時は None.
        """
        beatmap_id = self._state.beatmap_id_by_checksum.get(checksum_md5)
        if beatmap_id is None:
            return None
        return self._state.beatmaps_by_id.get(beatmap_id)

    async def get_beatmap_by_filename_in_beatmapset(
        self, beatmapset_id: int, original_filename: str
    ) -> Beatmap | None:
        """Beatmapset 内の original filename と一致する beatmap を返す.

        Args:
            beatmapset_id (int): 検索する beatmapset の識別子.
            original_filename (str): file attachment の original filename.

        Returns:
            Beatmap | None: 一致する attachment を持つ最初の beatmap. 該当なしなら None.
        """
        beatmapset = self._state.beatmapsets_by_id.get(beatmapset_id)
        if beatmapset is None:
            return None
        for beatmap in beatmapset.beatmaps:
            attachment = beatmap.file_attachment
            if attachment is not None and attachment.original_filename == original_filename:
                return beatmap
        return None

    async def save_beatmapset_snapshot(self, snapshot: BeatmapSet) -> None:
        """Beatmapset snapshot と子 beatmap を保存し checksum index を更新する.

        Args:
            snapshot (BeatmapSet): 保存する beatmapset とその子 beatmap snapshots.

        Returns:
            None: beatmapset, 子 beatmap, checksum index の更新が完了したことを示す.

        Raises:
            DuplicateBeatmapChecksumError: snapshot 内又は既存 state と MD5 checksum が競合する
                場合.

        Notes:
            既存 beatmap の local status override と file attachment を優先して保持する.
            checksum 競合は state を変更する前に検証する.
        """
        self._check_checksum_conflicts(snapshot)
        stored_beatmaps = tuple(
            self._merge_beatmap_snapshot(beatmap) for beatmap in snapshot.beatmaps
        )
        stored_snapshot = replace(snapshot, beatmaps=stored_beatmaps)
        for beatmap in stored_beatmaps:
            self._store_beatmap(beatmap)
        self._state.beatmapsets_by_id[snapshot.id] = stored_snapshot
        self._state.search_documents_by_beatmapset_id[snapshot.id] = (
            build_beatmapset_search_document(
                stored_snapshot,
                previous=self._state.search_documents_by_beatmapset_id.get(snapshot.id),
                updated_at=now_utc(),
            )
        )

    async def get_search_document(self, beatmapset_id: int) -> BeatmapSetSearchDocument | None:
        """External indexing用に保存済み検索projectionを返す.

        Args:
            beatmapset_id (int): 検索projectionを取得するbeatmapset ID.

        Returns:
            BeatmapSetSearchDocument | None: 保存済みprojection. 未登録ならNone.
        """
        return self._state.search_documents_by_beatmapset_id.get(beatmapset_id)

    async def list_search_documents(self) -> tuple[BeatmapSetSearchDocument, ...]:
        """External index rebuild用に検索projectionをbeatmapset ID順で返す.

        Returns:
            tuple[BeatmapSetSearchDocument, ...]: 保存済み検索projection列.
        """
        return tuple(
            self._state.search_documents_by_beatmapset_id[beatmapset_id]
            for beatmapset_id in sorted(self._state.search_documents_by_beatmapset_id)
        )

    async def rebuild_search_projection(self, *, now: datetime) -> int:
        """保存済みmetadataから検索projectionを再構築する.

        Args:
            now (datetime): 変更されたprojectionへ設定するUTC timestamp.

        Returns:
            int: 再構築対象として処理したbeatmapset数.
        """
        rebuilt_count = 0
        for beatmapset_id in sorted(self._state.beatmapsets_by_id):
            beatmapset = self._state.beatmapsets_by_id[beatmapset_id]
            self._state.search_documents_by_beatmapset_id[beatmapset_id] = (
                build_beatmapset_search_document(
                    beatmapset,
                    previous=self._state.search_documents_by_beatmapset_id.get(beatmapset_id),
                    updated_at=now,
                )
            )
            rebuilt_count += 1
        return rebuilt_count

    async def record_index_state(self, state: DirectExternalIndexState) -> None:
        """External index documentの同期状態を保存する.

        Args:
            state (DirectExternalIndexState): 保存するsuccessまたはfailure state.

        Returns:
            None: in-memory stateへ同期状態を保存して完了する.
        """
        self._state.external_index_states_by_key[(state.backend, state.beatmapset_id)] = state

    async def set_local_status_override(
        self, beatmap_id: int, status: LocalBeatmapStatus | None
    ) -> Beatmap:
        """Beatmap の local status override と変更時刻を更新する.

        Args:
            beatmap_id (int): 更新する beatmap の識別子.
            status (LocalBeatmapStatus | None): 設定する override. None は override を解除する.

        Returns:
            Beatmap: status と変更時刻を反映して保存した beatmap.

        Raises:
            BeatmapNotFoundError: beatmap_id が state に存在しない場合.

        Notes:
            新しい non-None status 又は欠落した変更時刻を持つ non-None status には現在 UTC
            時刻を記録する. 更新後の child は保存済み beatmapset snapshot にも反映する.
        """
        existing = self._require_beatmap(beatmap_id)
        if existing.local_status_override != status:
            changed_at = now_utc() if status is not None else None
        elif status is not None and existing.local_status_override_changed_at is None:
            changed_at = now_utc()
        else:
            changed_at = existing.local_status_override_changed_at
        updated = replace(
            existing,
            local_status_override=status,
            local_status_override_changed_at=changed_at,
        )
        self._store_beatmap(updated)
        self._refresh_beatmapset_child(updated)
        return updated

    async def increment_submission_counts(
        self,
        beatmap_id: int,
        *,
        passed: bool,
    ) -> BeatmapSubmissionCounts:
        """Beatmap の submission play count と optional pass count を増やす.

        Args:
            beatmap_id (int): 集計する beatmap の識別子.
            passed (bool): submission が pass なら True.

        Returns:
            BeatmapSubmissionCounts: 増分を適用して state に保存した集計値.

        Notes:
            beatmap の主記録がなくても count entry を 0 から作成する.
        """
        existing = self._state.beatmap_submission_counts_by_id.get(beatmap_id)
        play_count = 0 if existing is None else existing.play_count
        pass_count = 0 if existing is None else existing.pass_count
        counts = BeatmapSubmissionCounts(
            play_count=play_count + 1,
            pass_count=pass_count + (1 if passed else 0),
        )
        self._state.beatmap_submission_counts_by_id[beatmap_id] = counts
        return counts

    async def get_current_file_attachment(self, beatmap_id: int) -> BeatmapFileAttachment | None:
        """Beatmap に最後に追加した file attachment を返す.

        Args:
            beatmap_id (int): attachment を検索する beatmap の識別子.

        Returns:
            BeatmapFileAttachment | None: 最後に追加した attachment. 未登録なら None.

        Raises:
            KeyError: attachment index が主記録に存在しない key を参照する場合.
        """
        keys = self._state.attachment_keys_by_beatmap_id.get(beatmap_id)
        if not keys:
            return None
        return self._state.attachments_by_key[keys[-1]]

    async def attach_osu_file(self, attachment: BeatmapFileAttachment) -> BeatmapFileAttachment:
        """Beatmap に osu file attachment を追加し beatmap snapshot を available にする.

        Args:
            attachment (BeatmapFileAttachment): 追加する beatmap file metadata.

        Returns:
            BeatmapFileAttachment: 新規保存した attachment 又は同一 key の既存 attachment.

        Raises:
            BeatmapNotFoundError: attachment.beatmap_id が state に存在しない場合.

        Notes:
            新規 attachment では insertion-order index を追加し, file state を AVAILABLE にして
            保存済み beatmapset の子 snapshot も更新する. 同一 beatmap ID と checksum の行は
            idempotent に既存 attachment を返し state を変更しない.
        """
        existing_beatmap = self._require_beatmap(attachment.beatmap_id)
        key = (attachment.beatmap_id, attachment.checksum_md5)
        existing_attachment = self._state.attachments_by_key.get(key)
        if existing_attachment is not None:
            return existing_attachment

        self._state.attachments_by_key[key] = attachment
        self._state.attachment_keys_by_beatmap_id.setdefault(attachment.beatmap_id, []).append(key)
        updated_beatmap = replace(
            existing_beatmap,
            file_state=BeatmapFileState.AVAILABLE,
            file_attachment=attachment,
        )
        self._store_beatmap(updated_beatmap)
        self._refresh_beatmapset_child(updated_beatmap)
        return attachment

    async def get_fetch_state(self, target: BeatmapFetchTarget) -> BeatmapFetchRecord | None:
        """Beatmap fetch target の最後の fetch state を返す.

        Args:
            target (BeatmapFetchTarget): 検索する fetch target.

        Returns:
            BeatmapFetchRecord | None: 保存済み fetch record. 未登録なら None.
        """
        return self._state.fetch_states_by_target.get(target)

    async def try_mark_fetch_pending(self, target: BeatmapFetchTarget, now: datetime) -> bool:
        """Fetch target を pending に遷移できる場合だけ state を更新する.

        Args:
            target (BeatmapFetchTarget): pending にする fetch target.
            now (datetime): pending_since と last_attempted_at に保存する timestamp.

        Returns:
            bool: pending record を作成又は更新した場合は True. すでに pending なら False.

        Notes:
            新規 target の attempt_count は 1 とし, pending 以外の既存 record は count を 1
            増やす. すでに pending の場合は state を変更しない.
        """
        existing = self._state.fetch_states_by_target.get(target)
        if existing is not None and existing.status is BeatmapFetchState.PENDING_FETCH:
            return False

        attempt_count = 1 if existing is None else existing.attempt_count + 1
        self._state.fetch_states_by_target[target] = BeatmapFetchRecord(
            target=target,
            status=BeatmapFetchState.PENDING_FETCH,
            attempt_count=attempt_count,
            last_error=None,
            pending_since=now,
            last_attempted_at=now,
        )
        return True

    async def mark_fetch_succeeded(self, target: BeatmapFetchTarget, now: datetime) -> None:
        """Fetch target の state を fresh に更新する.

        Args:
            target (BeatmapFetchTarget): 成功として記録する fetch target.
            now (datetime): last_attempted_at に保存する timestamp.

        Returns:
            None: fresh fetch record を state に保存したことを示す.

        Notes:
            既存 record があれば attempt_count を保持する. 未登録 target では count を 0 とする.
        """
        existing = self._state.fetch_states_by_target.get(target)
        self._state.fetch_states_by_target[target] = BeatmapFetchRecord(
            target=target,
            status=BeatmapFetchState.FRESH,
            attempt_count=0 if existing is None else existing.attempt_count,
            last_error=None,
            pending_since=None,
            last_attempted_at=now,
        )

    async def mark_fetch_failed(
        self, target: BeatmapFetchTarget, reason: str, now: datetime
    ) -> None:
        """Fetch target の state を failed に更新し理由を保存する.

        Args:
            target (BeatmapFetchTarget): failure を記録する fetch target.
            reason (str): 保存する failure 理由.
            now (datetime): last_attempted_at に保存する timestamp.

        Returns:
            None: failed fetch record を state に保存したことを示す.

        Notes:
            既存 record があれば attempt_count を保持する. 未登録 target では count を 0 とする.
        """
        existing = self._state.fetch_states_by_target.get(target)
        self._state.fetch_states_by_target[target] = BeatmapFetchRecord(
            target=target,
            status=BeatmapFetchState.FAILED,
            attempt_count=0 if existing is None else existing.attempt_count,
            last_error=reason,
            pending_since=None,
            last_attempted_at=now,
        )

    def _check_checksum_conflicts(self, snapshot: BeatmapSet) -> None:
        """Snapshot 内及び state 内の beatmap checksum 一意性を検証する.

        Args:
            snapshot (BeatmapSet): 検証する beatmapset snapshot.

        Returns:
            None: すべての child checksum が一意であることを示す.

        Raises:
            DuplicateBeatmapChecksumError: 同一 checksum が異なる beatmap ID に割り当てられる場合.

        Notes:
            この helper は state を変更しない.
        """
        incoming_beatmap_ids_by_checksum: dict[str, int] = {}
        for beatmap in snapshot.beatmaps:
            incoming_beatmap_id = incoming_beatmap_ids_by_checksum.get(beatmap.checksum_md5)
            if incoming_beatmap_id is not None and incoming_beatmap_id != beatmap.id:
                raise DuplicateBeatmapChecksumError(
                    checksum_md5=beatmap.checksum_md5,
                    existing_beatmap_id=incoming_beatmap_id,
                )
            incoming_beatmap_ids_by_checksum[beatmap.checksum_md5] = beatmap.id

            existing_beatmap_id = self._state.beatmap_id_by_checksum.get(beatmap.checksum_md5)
            if existing_beatmap_id is not None and existing_beatmap_id != beatmap.id:
                raise DuplicateBeatmapChecksumError(
                    checksum_md5=beatmap.checksum_md5,
                    existing_beatmap_id=existing_beatmap_id,
                )

    def _merge_beatmap_snapshot(self, beatmap: Beatmap) -> Beatmap:
        """Incoming beatmap snapshot に既存の local-only state を統合する.

        Args:
            beatmap (Beatmap): 外部 snapshot から得た incoming beatmap.

        Returns:
            Beatmap: 既存の override と attachment を必要に応じて保持した保存用 beatmap.

        Notes:
            既存 beatmap がなければ引数をそのまま返す. 既存 local status override, attachment,
            official_last_updated_at を優先し, attachment があれば file state を AVAILABLE にする.
        """
        existing = self._state.beatmaps_by_id.get(beatmap.id)
        if existing is None:
            return beatmap

        if existing.local_status_override is not None:
            local_status_override = existing.local_status_override
            local_status_override_changed_at = existing.local_status_override_changed_at
        else:
            local_status_override = beatmap.local_status_override
            local_status_override_changed_at = beatmap.local_status_override_changed_at
        file_attachment = existing.file_attachment or beatmap.file_attachment
        file_state = (
            BeatmapFileState.AVAILABLE if file_attachment is not None else beatmap.file_state
        )
        return replace(
            beatmap,
            local_status_override=local_status_override,
            local_status_override_changed_at=local_status_override_changed_at,
            official_last_updated_at=beatmap.official_last_updated_at
            or existing.official_last_updated_at,
            file_state=file_state,
            file_attachment=file_attachment,
        )

    def _store_beatmap(self, beatmap: Beatmap) -> None:
        """Beatmap 主記録と checksum index を state に保存する.

        Args:
            beatmap (Beatmap): 保存する beatmap snapshot.

        Returns:
            None: 主記録と checksum index の更新が完了したことを示す.

        Notes:
            同じ beatmap ID の checksum が変わる場合は古い checksum index を先に削除する.
        """
        existing = self._state.beatmaps_by_id.get(beatmap.id)
        if existing is not None and existing.checksum_md5 != beatmap.checksum_md5:
            _ = self._state.beatmap_id_by_checksum.pop(existing.checksum_md5, None)

        self._state.beatmaps_by_id[beatmap.id] = beatmap
        self._state.beatmap_id_by_checksum[beatmap.checksum_md5] = beatmap.id

    def _refresh_beatmapset_child(self, beatmap: Beatmap) -> None:
        """保存済み beatmapset 内の対応する child snapshot を更新する.

        Args:
            beatmap (Beatmap): child として差し替える保存済み beatmap.

        Returns:
            None: parent beatmapset があれば child を差し替えたことを示す.

        Notes:
            parent beatmapset が state にない場合は state を変更しない.
        """
        beatmapset = self._state.beatmapsets_by_id.get(beatmap.beatmapset_id)
        if beatmapset is None:
            return
        self._state.beatmapsets_by_id[beatmapset.id] = replace(
            beatmapset,
            beatmaps=tuple(
                beatmap if existing.id == beatmap.id else existing
                for existing in beatmapset.beatmaps
            ),
        )

    def _require_beatmap(self, beatmap_id: int) -> Beatmap:
        """State に存在する beatmap を取得し, 欠落時は例外を送出する.

        Args:
            beatmap_id (int): 必須として取得する beatmap の識別子.

        Returns:
            Beatmap: state に保存された beatmap.

        Raises:
            BeatmapNotFoundError: beatmap_id が state に存在しない場合.
        """
        beatmap = self._state.beatmaps_by_id.get(beatmap_id)
        if beatmap is None:
            raise BeatmapNotFoundError(beatmap_id)
        return beatmap
