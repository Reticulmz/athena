"""SQLAlchemy を用いて beatmap,file attachment,fetch state を永続化する command repository."""

from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime
from decimal import Decimal
from typing import TYPE_CHECKING, cast

from sqlalchemy import func, literal, select, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.exc import IntegrityError

from osu_server.domain.beatmaps import (
    Beatmap,
    BeatmapFetchRecord,
    BeatmapFetchState,
    BeatmapFetchTarget,
    BeatmapFetchTargetKind,
    BeatmapFileAttachment,
    BeatmapFileSource,
    BeatmapFileState,
    BeatmapMetadataSource,
    BeatmapMode,
    BeatmapRankStatus,
    BeatmapSet,
    BeatmapSetSearchDocument,
    BeatmapSourceVerification,
    DirectExternalIndexState,
    LocalBeatmapStatus,
    build_beatmapset_search_document,
)
from osu_server.repositories.interfaces.commands.beatmaps import BeatmapSubmissionCounts
from osu_server.repositories.sqlalchemy.models.beatmap import (
    BeatmapDirectExternalIndexStateModel,
    BeatmapFetchStateModel,
    BeatmapFileAttachmentModel,
    BeatmapModel,
    BeatmapSetModel,
    BeatmapSetSearchDocumentModel,
)

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession
    from sqlalchemy.sql.dml import ReturningInsert


class DuplicateBeatmapChecksumError(ValueError):
    """同一 checksum が複数の beatmap に割り当てられたときに送出する例外.

    Attributes:
        checksum_md5 (str): 衝突した beatmap file の MD5 checksum.
        existing_beatmap_id (int): 先に checksum を所有していた beatmap ID.
    """

    checksum_md5: str
    existing_beatmap_id: int

    def __init__(self, *, checksum_md5: str, existing_beatmap_id: int) -> None:
        """Checksum の競合内容を保持して ValueError を初期化する.

        Args:
            checksum_md5 (str): 既存 beatmap と重複した MD5 checksum.
            existing_beatmap_id (int): checksum を既に所有する beatmap ID.
        """
        self.checksum_md5 = checksum_md5
        self.existing_beatmap_id = existing_beatmap_id
        super().__init__(
            f"checksum {checksum_md5} already belongs to beatmap {existing_beatmap_id}"
        )


class BeatmapNotFoundError(LookupError):
    """Beatmap command が未登録の beatmap を必要としたときに送出する例外.

    Attributes:
        beatmap_id (int): 見つからなかった beatmap ID.
    """

    beatmap_id: int

    def __init__(self, beatmap_id: int) -> None:
        """未登録 beatmap の ID を保持して LookupError を初期化する.

        Args:
            beatmap_id (int): command が要求した beatmap ID.
        """
        self.beatmap_id = beatmap_id
        super().__init__(f"beatmap {beatmap_id} was not found")


class SQLAlchemyBeatmapCommandRepository:
    """UoW 所有の SQLAlchemy session で beatmap command state を永続化する repository.

    Attributes:
        _session (AsyncSession): 呼び出し元の Unit of Work が所有する非同期 session.
    """

    def __init__(self, session: AsyncSession) -> None:
        """Unit of Work 所有の SQLAlchemy session を保存する.

        Args:
            session (AsyncSession): command transaction を共有する非同期 session.
        """
        self._session: AsyncSession = session

    async def get_beatmap(self, beatmap_id: int) -> Beatmap | None:
        """Beatmap ID と現在の file attachment から domain beatmap を返す.

        Args:
            beatmap_id (int): 検索する beatmap ID.

        Returns:
            Beatmap | None: current file attachment を含む beatmap. 未登録時は None.
        """
        model = await self._session.get(BeatmapModel, beatmap_id)
        if not isinstance(model, BeatmapModel):
            return None
        attachment = await self._get_current_file_attachment_model(beatmap_id=beatmap_id)
        return _beatmap_to_domain(model, attachment)

    async def get_beatmapset(self, beatmapset_id: int) -> BeatmapSet | None:
        """Beatmapset ID とその子 beatmap から domain beatmapset を返す.

        Args:
            beatmapset_id (int): 検索する beatmapset ID.

        Returns:
            BeatmapSet | None: 各子 beatmap の current file attachment を含む set. 未登録時は None.
        """
        model = await self._session.get(BeatmapSetModel, beatmapset_id)
        if not isinstance(model, BeatmapSetModel):
            return None

        beatmap_models = await self._get_beatmap_models_for_set(beatmapset_id=beatmapset_id)
        beatmaps = [
            _beatmap_to_domain(
                beatmap_model,
                await self._get_current_file_attachment_model(beatmap_id=beatmap_model.id),
            )
            for beatmap_model in beatmap_models
        ]
        return _beatmapset_to_domain(model, tuple(beatmaps))

    async def get_beatmap_by_checksum(self, checksum_md5: str) -> Beatmap | None:
        """MD5 checksum に一致する beatmap と現在の file attachment を返す.

        Args:
            checksum_md5 (str): 検索する beatmap file の MD5 checksum.

        Returns:
            Beatmap | None: checksum が一致する beatmap. 未登録時は None.
        """
        model = (
            await self._session.execute(
                select(BeatmapModel).where(BeatmapModel.checksum_md5 == checksum_md5)
            )
        ).scalar_one_or_none()
        if not isinstance(model, BeatmapModel):
            return None
        attachment = await self._get_current_file_attachment_model(beatmap_id=model.id)
        return _beatmap_to_domain(model, attachment)

    async def get_beatmap_by_filename_in_beatmapset(
        self, beatmapset_id: int, original_filename: str
    ) -> Beatmap | None:
        """Beatmapset 内の original filename に一致する beatmap を返す.

        Args:
            beatmapset_id (int): file attachment を検索する beatmapset ID.
            original_filename (str): attachment に保存された original filename.

        Returns:
            Beatmap | None: 最初に一致した beatmap とその current attachment. 未登録時は None.
        """
        model = (
            await self._session.execute(
                select(BeatmapModel)
                .join(
                    BeatmapFileAttachmentModel,
                    BeatmapFileAttachmentModel.beatmap_id == BeatmapModel.id,
                )
                .where(
                    BeatmapModel.beatmapset_id == beatmapset_id,
                    BeatmapFileAttachmentModel.original_filename == original_filename,
                )
                .limit(1)
            )
        ).scalar_one_or_none()
        if not isinstance(model, BeatmapModel):
            return None
        attachment = await self._get_current_file_attachment_model(beatmap_id=model.id)
        return _beatmap_to_domain(model, attachment)

    async def save_beatmapset_snapshot(self, snapshot: BeatmapSet) -> None:
        """Beatmapset snapshot と子 beatmap を既存のローカル状態を保って保存する.

        Args:
            snapshot (BeatmapSet): upstream metadata から得た beatmapset と子 beatmap の snapshot.

        Returns:
            None: session への merge と flush が完了したことを示す. transaction の確定は行わない.

        Raises:
            DuplicateBeatmapChecksumError: snapshot 内または保存済み beatmap と checksum が
                衝突する場合.

        Notes:
            既存の local status override,submission count,欠損した official last updated
            時刻を保持する.
        """
        await self._check_checksum_conflicts(snapshot)
        _ = await self._session.merge(_beatmapset_to_model(snapshot))
        stored_beatmaps: list[Beatmap] = []
        try:
            for beatmap in snapshot.beatmaps:
                existing = await self._session.get(BeatmapModel, beatmap.id)
                local_override = (
                    existing.local_status_override
                    if isinstance(existing, BeatmapModel)
                    else beatmap.local_status_override.value
                    if beatmap.local_status_override is not None
                    else None
                )
                local_override_changed_at = (
                    existing.local_status_override_changed_at
                    if isinstance(existing, BeatmapModel)
                    else beatmap.local_status_override_changed_at
                )
                official_last_updated_at = (
                    beatmap.official_last_updated_at
                    if beatmap.official_last_updated_at is not None
                    else existing.official_last_updated_at
                    if isinstance(existing, BeatmapModel)
                    else None
                )
                play_count = (
                    _existing_count(existing.play_count)
                    if isinstance(existing, BeatmapModel)
                    else 0
                )
                pass_count = (
                    _existing_count(existing.pass_count)
                    if isinstance(existing, BeatmapModel)
                    else 0
                )
                stored_beatmap = replace(
                    beatmap,
                    local_status_override=(
                        LocalBeatmapStatus(local_override) if local_override is not None else None
                    ),
                    local_status_override_changed_at=local_override_changed_at,
                    official_last_updated_at=official_last_updated_at,
                )
                stored_beatmaps.append(stored_beatmap)
                _ = await self._session.merge(
                    _beatmap_to_model(
                        stored_beatmap,
                        local_override,
                        local_override_changed_at,
                        play_count,
                        pass_count,
                    )
                )
            await self._upsert_search_document(replace(snapshot, beatmaps=tuple(stored_beatmaps)))
            await self._session.flush()
        except IntegrityError as exc:
            checksum_md5 = snapshot.beatmaps[0].checksum_md5 if snapshot.beatmaps else ""
            raise DuplicateBeatmapChecksumError(
                checksum_md5=checksum_md5,
                existing_beatmap_id=0,
            ) from exc

    async def _upsert_search_document(self, snapshot: BeatmapSet) -> None:
        """Metadata保存transaction内でosu!direct検索projectionを更新する.

        Args:
            snapshot (BeatmapSet): 永続化するchild状態を反映したbeatmapset snapshot.

        Returns:
            None: projection modelを必要に応じてsessionへmergeして完了する.
        """
        existing = await self._session.get(BeatmapSetSearchDocumentModel, snapshot.id)
        previous = (
            _search_document_to_domain(existing)
            if isinstance(existing, BeatmapSetSearchDocumentModel)
            else None
        )
        document = build_beatmapset_search_document(
            snapshot,
            previous=previous,
            updated_at=datetime.now(UTC),
        )
        if document == previous:
            return
        _ = await self._session.merge(_search_document_to_model(document))

    async def get_search_document(self, beatmapset_id: int) -> BeatmapSetSearchDocument | None:
        """External indexing用に保存済み検索projectionを返す.

        Args:
            beatmapset_id (int): 検索projectionを取得するbeatmapset ID.

        Returns:
            BeatmapSetSearchDocument | None: 保存済みprojection. 未登録ならNone.
        """
        model = await self._session.get(BeatmapSetSearchDocumentModel, beatmapset_id)
        if not isinstance(model, BeatmapSetSearchDocumentModel):
            return None
        return _search_document_to_domain(model)

    async def list_search_documents(self) -> tuple[BeatmapSetSearchDocument, ...]:
        """External index rebuild用に検索projectionをbeatmapset ID順で返す.

        Returns:
            tuple[BeatmapSetSearchDocument, ...]: 保存済み検索projection列.
        """
        models = (
            (
                await self._session.execute(
                    select(BeatmapSetSearchDocumentModel).order_by(
                        BeatmapSetSearchDocumentModel.beatmapset_id.asc()
                    )
                )
            )
            .scalars()
            .all()
        )
        return tuple(_search_document_to_domain(model) for model in models)

    async def rebuild_search_projection(self, *, now: datetime) -> int:
        """保存済みmetadataから検索projectionを再構築する.

        Args:
            now (datetime): 変更されたprojectionへ設定するUTC timestamp.

        Returns:
            int: 再構築対象として処理したbeatmapset数.
        """
        beatmapset_models = (
            (
                await self._session.execute(
                    select(BeatmapSetModel).order_by(BeatmapSetModel.id.asc())
                )
            )
            .scalars()
            .all()
        )
        rebuilt_count = 0
        for beatmapset_model in beatmapset_models:
            beatmap_models = await self._get_beatmap_models_for_set(
                beatmapset_id=beatmapset_model.id
            )
            beatmaps = tuple(
                _beatmap_to_domain(beatmap_model, None) for beatmap_model in beatmap_models
            )
            previous_model = await self._session.get(
                BeatmapSetSearchDocumentModel,
                beatmapset_model.id,
            )
            previous = (
                _search_document_to_domain(previous_model)
                if isinstance(previous_model, BeatmapSetSearchDocumentModel)
                else None
            )
            document = build_beatmapset_search_document(
                _beatmapset_to_domain(beatmapset_model, beatmaps),
                previous=previous,
                updated_at=now,
            )
            if document != previous:
                _ = await self._session.merge(_search_document_to_model(document))
            rebuilt_count += 1
        await self._session.flush()
        return rebuilt_count

    async def record_index_state(self, state: DirectExternalIndexState) -> None:
        """External index documentの同期状態を保存する.

        Args:
            state (DirectExternalIndexState): 保存するsuccessまたはfailure state.

        Returns:
            None: sessionへ同期状態をmergeしてflushしたことを示す.
        """
        _ = await self._session.merge(_index_state_to_model(state))
        await self._session.flush()

    async def set_local_status_override(
        self, beatmap_id: int, status: LocalBeatmapStatus | None
    ) -> Beatmap:
        """Beatmap の local status override を設定または解除して更新後の domain value を返す.

        Args:
            beatmap_id (int): 更新する beatmap ID.
            status (LocalBeatmapStatus | None): 設定する local status. None の場合は override
                を解除する.

        Returns:
            Beatmap: current file attachment を含む更新後の beatmap.

        Raises:
            BeatmapNotFoundError: beatmap ID が保存されていない場合.
        """
        model = await self._session.get(BeatmapModel, beatmap_id)
        if not isinstance(model, BeatmapModel):
            raise BeatmapNotFoundError(beatmap_id)

        new_status = status.value if status is not None else None
        if model.local_status_override != new_status:
            model.local_status_override = new_status
            model.local_status_override_changed_at = (
                datetime.now(UTC) if new_status is not None else None
            )
        elif new_status is not None and model.local_status_override_changed_at is None:
            model.local_status_override_changed_at = datetime.now(UTC)
        await self._session.flush()
        attachment = await self._get_current_file_attachment_model(beatmap_id=beatmap_id)
        return _beatmap_to_domain(model, attachment)

    async def increment_submission_counts(
        self,
        beatmap_id: int,
        *,
        passed: bool,
    ) -> BeatmapSubmissionCounts:
        """Beatmap の submit count と必要に応じて pass count を atomic に増加する.

        Args:
            beatmap_id (int): score submission を記録する beatmap ID.
            passed (bool): pass count も増加する submission なら True.

        Returns:
            BeatmapSubmissionCounts: update statement が返した増加後の play count と pass count.

        Raises:
            BeatmapNotFoundError: beatmap ID が保存されていない場合.
        """
        result = await self._session.execute(
            _increment_submission_counts_statement(beatmap_id, passed=passed)
        )
        row = result.one_or_none()
        if row is None:
            raise BeatmapNotFoundError(beatmap_id)
        play_count, pass_count = cast("tuple[object, object]", cast("object", row))
        return BeatmapSubmissionCounts(
            play_count=_count_value(play_count),
            pass_count=_count_value(pass_count),
        )

    async def get_current_file_attachment(self, beatmap_id: int) -> BeatmapFileAttachment | None:
        """Beatmap に最後に保存された file attachment を domain value として返す.

        Args:
            beatmap_id (int): attachment を検索する beatmap ID.

        Returns:
            BeatmapFileAttachment | None: 最大 ID の attachment. 未登録時は None.
        """
        model = await self._get_current_file_attachment_model(beatmap_id=beatmap_id)
        return _attachment_to_domain(model) if model is not None else None

    async def attach_osu_file(self, attachment: BeatmapFileAttachment) -> BeatmapFileAttachment:
        """Beatmap file attachment を保存し同じ checksum の既存 attachment は再利用する.

        Args:
            attachment (BeatmapFileAttachment): 保存する verified osu! file attachment.

        Returns:
            BeatmapFileAttachment: 新規保存または既存再利用した attachment.

        Raises:
            BeatmapNotFoundError: 対象 beatmap が未登録または attachment の flush が外部キーで
                失敗した場合.
        """
        beatmap = await self._session.get(BeatmapModel, attachment.beatmap_id)
        if not isinstance(beatmap, BeatmapModel):
            raise BeatmapNotFoundError(attachment.beatmap_id)

        existing = await self._get_file_attachment_by_key(attachment)
        if existing is not None:
            return _attachment_to_domain(existing)

        model = _attachment_to_model(attachment)
        self._session.add(model)
        try:
            await self._session.flush()
        except IntegrityError as exc:
            raise BeatmapNotFoundError(attachment.beatmap_id) from exc
        await self._session.refresh(model)
        return _attachment_to_domain(model)

    async def get_fetch_state(self, target: BeatmapFetchTarget) -> BeatmapFetchRecord | None:
        """Beatmap metadata または file の fetch state を返す.

        Args:
            target (BeatmapFetchTarget): target kind と key による fetch state の識別子.

        Returns:
            BeatmapFetchRecord | None: 保存済みの fetch state. 未登録時は None.
        """
        model = await self._get_fetch_state_model(target)
        return _fetch_state_to_domain(model) if model is not None else None

    async def try_mark_fetch_pending(self, target: BeatmapFetchTarget, now: datetime) -> bool:
        """Fetch target を pending_fetch に atomic に遷移する.

        Args:
            target (BeatmapFetchTarget): fetch state の対象.
            now (datetime): pending_since と last_attempted_at に保存する時刻.

        Returns:
            bool: この呼び出しが fetch lock を取得した場合は True. 既に pending_fetch の場合は
                False.

        Notes:
            PostgreSQL の ON CONFLICT で判定し並列 INSERT 競合を起こさない.
        """
        result = await self._session.execute(_mark_fetch_pending_statement(target, now))
        row_id = result.scalar_one_or_none()
        if row_id is None:
            return False
        _ = await self._session.get(
            BeatmapFetchStateModel,
            row_id,
            populate_existing=True,
        )
        return True

    async def mark_fetch_succeeded(self, target: BeatmapFetchTarget, now: datetime) -> None:
        """Fetch target を fresh に遷移して成功時刻と空の error を保存する.

        Args:
            target (BeatmapFetchTarget): 成功した metadata または file fetch の対象.
            now (datetime): last_attempted_at に保存する成功時刻.

        Returns:
            None: fetch state の flush が完了したことを示す. transaction の確定は行わない.
        """
        await self._mark_fetch_completed(
            target=target,
            status=BeatmapFetchState.FRESH,
            last_error=None,
            now=now,
        )

    async def mark_fetch_failed(
        self, target: BeatmapFetchTarget, reason: str, now: datetime
    ) -> None:
        """Fetch target を failed に遷移して失敗理由と試行時刻を保存する.

        Args:
            target (BeatmapFetchTarget): 失敗した metadata または file fetch の対象.
            reason (str): 呼び出し元へ返すため保存する失敗理由.
            now (datetime): last_attempted_at に保存する失敗時刻.

        Returns:
            None: fetch state の flush が完了したことを示す. transaction の確定は行わない.
        """
        await self._mark_fetch_completed(
            target=target,
            status=BeatmapFetchState.FAILED,
            last_error=reason,
            now=now,
        )

    async def _mark_fetch_completed(
        self,
        *,
        target: BeatmapFetchTarget,
        status: BeatmapFetchState,
        last_error: str | None,
        now: datetime,
    ) -> None:
        """Fetch state を完了状態へ保存し pending marker を解除する.

        Args:
            target (BeatmapFetchTarget): 更新する target kind と key.
            status (BeatmapFetchState): 保存する terminal fetch state.
            last_error (str | None): failed 時に保存する理由. fresh 時は None.
            now (datetime): last_attempted_at に保存する完了時刻.

        Returns:
            None: 新規 state の追加または既存 state の更新と flush が完了したことを示す.
        """
        model = await self._get_fetch_state_model(target)
        if model is None:
            model = BeatmapFetchStateModel(
                target_type=target.kind.value,
                target_key=target.target_key,
                status=status.value,
                attempt_count=0,
                last_error=last_error,
                pending_since=None,
                last_attempted_at=now,
            )
            self._session.add(model)
        else:
            model.status = status.value
            model.last_error = last_error
            model.pending_since = None
            model.last_attempted_at = now
        await self._session.flush()

    async def _check_checksum_conflicts(self, snapshot: BeatmapSet) -> None:
        """Snapshot 内と保存済み beatmap の MD5 checksum 衝突を検証する.

        Args:
            snapshot (BeatmapSet): 保存前に検証する beatmapset snapshot.

        Returns:
            None: checksum がすべて各 beatmap ID に一意であることを示す.

        Raises:
            DuplicateBeatmapChecksumError: 同じ checksum が異なる beatmap ID に属する場合.
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

            existing = (
                await self._session.execute(
                    select(BeatmapModel).where(BeatmapModel.checksum_md5 == beatmap.checksum_md5)
                )
            ).scalar_one_or_none()
            if isinstance(existing, BeatmapModel) and existing.id != beatmap.id:
                raise DuplicateBeatmapChecksumError(
                    checksum_md5=beatmap.checksum_md5,
                    existing_beatmap_id=existing.id,
                )

    async def _get_beatmap_models_for_set(self, *, beatmapset_id: int) -> list[BeatmapModel]:
        """Beatmapset に属する SQLAlchemy beatmap model をすべて返す.

        Args:
            beatmapset_id (int): 子 beatmap を検索する beatmapset ID.

        Returns:
            list[BeatmapModel]: query が返した child model. 未登録時は空 list.
        """
        return list(
            (
                await self._session.execute(
                    select(BeatmapModel)
                    .where(BeatmapModel.beatmapset_id == beatmapset_id)
                    .order_by(BeatmapModel.id.asc())
                )
            )
            .scalars()
            .all()
        )

    async def _get_current_file_attachment_model(
        self, *, beatmap_id: int
    ) -> BeatmapFileAttachmentModel | None:
        """Beatmap の最大 ID を持つ file attachment model を返す.

        Args:
            beatmap_id (int): attachment を検索する beatmap ID.

        Returns:
            BeatmapFileAttachmentModel | None: current attachment model. 未登録時は None.
        """
        model = (
            await self._session.execute(
                select(BeatmapFileAttachmentModel)
                .where(BeatmapFileAttachmentModel.beatmap_id == beatmap_id)
                .order_by(BeatmapFileAttachmentModel.id.desc())
                .limit(1)
            )
        ).scalar_one_or_none()
        return model if isinstance(model, BeatmapFileAttachmentModel) else None

    async def _get_file_attachment_by_key(
        self, attachment: BeatmapFileAttachment
    ) -> BeatmapFileAttachmentModel | None:
        """Beatmap ID と checksum が一致する既存 file attachment model を返す.

        Args:
            attachment (BeatmapFileAttachment): 重複を確認する attachment の natural key.

        Returns:
            BeatmapFileAttachmentModel | None: 同じ natural key の保存 model. 未登録時は None.
        """
        model = (
            await self._session.execute(
                select(BeatmapFileAttachmentModel).where(
                    BeatmapFileAttachmentModel.beatmap_id == attachment.beatmap_id,
                    BeatmapFileAttachmentModel.checksum_md5 == attachment.checksum_md5,
                )
            )
        ).scalar_one_or_none()
        return model if isinstance(model, BeatmapFileAttachmentModel) else None

    async def _get_fetch_state_model(
        self, target: BeatmapFetchTarget
    ) -> BeatmapFetchStateModel | None:
        """Target kind と key に一致する fetch state model を返す.

        Args:
            target (BeatmapFetchTarget): 検索する fetch state の識別子.

        Returns:
            BeatmapFetchStateModel | None: 保存済み fetch state model. 未登録時は None.
        """
        model = (
            await self._session.execute(
                select(BeatmapFetchStateModel).where(
                    BeatmapFetchStateModel.target_type == target.kind.value,
                    BeatmapFetchStateModel.target_key == target.target_key,
                )
            )
        ).scalar_one_or_none()
        return model if isinstance(model, BeatmapFetchStateModel) else None


def _mark_fetch_pending_statement(
    target: BeatmapFetchTarget,
    now: datetime,
) -> ReturningInsert[tuple[int]]:
    """Pending でない fetch state だけを pending_fetch へ遷移する UPSERT statement を構築する.

    Args:
        target (BeatmapFetchTarget): target kind と key による fetch state の識別子.
        now (datetime): 新規または更新する pending_since と last_attempted_at の時刻.

    Returns:
        ReturningInsert[tuple[int]]: lock 取得時だけ fetch state ID を返す PostgreSQL UPSERT
            statement.

    Notes:
        既に pending_fetch の row では conflict update を行わず returning row も返さない.
    """
    insert_statement = insert(BeatmapFetchStateModel).values(
        target_type=target.kind.value,
        target_key=target.target_key,
        status=BeatmapFetchState.PENDING_FETCH.value,
        attempt_count=1,
        last_error=None,
        pending_since=now,
        last_attempted_at=now,
    )
    return insert_statement.on_conflict_do_update(
        index_elements=[
            BeatmapFetchStateModel.target_type,
            BeatmapFetchStateModel.target_key,
        ],
        set_={
            "status": BeatmapFetchState.PENDING_FETCH.value,
            "attempt_count": BeatmapFetchStateModel.attempt_count + 1,
            "last_error": None,
            "pending_since": now,
            "last_attempted_at": now,
            "updated_at": func.now(),
        },
        where=BeatmapFetchStateModel.status != BeatmapFetchState.PENDING_FETCH.value,
    ).returning(BeatmapFetchStateModel.id)


def _increment_submission_counts_statement(beatmap_id: int, *, passed: bool):
    """Submission count を atomic に増加して更新後の count を返す UPDATE statement を構築する.

    Args:
        beatmap_id (int): score submission を記録する beatmap ID.
        passed (bool): pass count も 1 増加する submission なら True.

    Returns:
        Update: play_count を必ず 1 増加し passed 時だけ pass_count を 1 増加する statement.
    """
    pass_increment = 1 if passed else 0
    return (
        update(BeatmapModel)
        .where(BeatmapModel.id == beatmap_id)
        .values(
            play_count=BeatmapModel.play_count + literal(1),
            pass_count=BeatmapModel.pass_count + literal(pass_increment),
            updated_at=func.now(),
        )
        .returning(BeatmapModel.play_count, BeatmapModel.pass_count)
    )


def _beatmapset_to_model(beatmapset: BeatmapSet) -> BeatmapSetModel:
    """Domain beatmapset を SQLAlchemy の保存 model へ変換する.

    Args:
        beatmapset (BeatmapSet): upstream metadata を含む domain beatmapset.

    Returns:
        BeatmapSetModel: enum と source verification を永続化値へ変換した未保存 model.
    """
    return BeatmapSetModel(
        id=beatmapset.id,
        artist=beatmapset.artist,
        title=beatmapset.title,
        creator=beatmapset.creator,
        artist_unicode=beatmapset.artist_unicode,
        title_unicode=beatmapset.title_unicode,
        official_status=beatmapset.official_status.value,
        official_status_source=beatmapset.official_status_source.value,
        official_status_verified=(
            beatmapset.official_status_verified is BeatmapSourceVerification.VERIFIED
        ),
        last_fetched_at=beatmapset.last_fetched_at,
        next_refresh_at=beatmapset.next_refresh_at,
    )


def _beatmap_to_model(
    beatmap: Beatmap,
    local_status_override: str | None,
    local_status_override_changed_at: datetime | None,
    play_count: int,
    pass_count: int,
) -> BeatmapModel:
    """Domain beatmap と保持対象のローカル状態を SQLAlchemy 保存 model へ変換する.

    Args:
        beatmap (Beatmap): upstream metadata を含む domain beatmap.
        local_status_override (str | None): 保持する local status override の永続化値.
        local_status_override_changed_at (datetime | None): override を最後に変更した時刻.
        play_count (int): 保持する score submission の累計数.
        pass_count (int): 保持する pass submission の累計数.

    Returns:
        BeatmapModel: decimal,enum,verification を永続化値へ変換した未保存 model.
    """
    return BeatmapModel(
        id=beatmap.id,
        beatmapset_id=beatmap.beatmapset_id,
        checksum_md5=beatmap.checksum_md5,
        mode=beatmap.mode.value,
        version=beatmap.version,
        total_length=beatmap.total_length,
        hit_length=beatmap.hit_length,
        max_combo=beatmap.max_combo,
        bpm=_decimal_or_none(beatmap.bpm),
        cs=_decimal_or_none(beatmap.cs),
        od=_decimal_or_none(beatmap.od),
        ar=_decimal_or_none(beatmap.ar),
        hp=_decimal_or_none(beatmap.hp),
        difficulty_rating=_decimal_or_none(beatmap.difficulty_rating),
        official_status=beatmap.official_status.value,
        official_status_source=beatmap.official_status_source.value,
        official_status_verified=(
            beatmap.official_status_verified is BeatmapSourceVerification.VERIFIED
        ),
        local_status_override=local_status_override,
        local_status_override_changed_at=local_status_override_changed_at,
        play_count=play_count,
        pass_count=pass_count,
        official_last_updated_at=beatmap.official_last_updated_at,
        last_fetched_at=beatmap.last_fetched_at,
        next_refresh_at=beatmap.next_refresh_at,
    )


def _search_document_to_model(document: BeatmapSetSearchDocument) -> BeatmapSetSearchDocumentModel:
    """Domain検索projectionをSQLAlchemy保存modelへ変換する.

    Args:
        document (BeatmapSetSearchDocument): osu!direct検索projectionのdomain値.

    Returns:
        BeatmapSetSearchDocumentModel: enumとmodeを永続化値へ変換したmodel.
    """
    return BeatmapSetSearchDocumentModel(
        beatmapset_id=document.beatmapset_id,
        artist=document.artist,
        title=document.title,
        creator=document.creator,
        artist_unicode=document.artist_unicode,
        title_unicode=document.title_unicode,
        source=document.source,
        tags=document.tags,
        difficulty_names=document.difficulty_names,
        modes=[mode.value for mode in document.modes],
        status=document.status.value,
        last_update_at=document.last_update_at,
        is_active=document.is_active,
        document_version=document.document_version,
        updated_at=document.updated_at,
    )


def _search_document_to_domain(
    model: BeatmapSetSearchDocumentModel,
) -> BeatmapSetSearchDocument:
    """SQLAlchemy検索projection modelをdomain値へ変換する.

    Args:
        model (BeatmapSetSearchDocumentModel): 保存済みのosu!direct検索projection model.

    Returns:
        BeatmapSetSearchDocument: version比較に使うdomain projection.
    """
    return BeatmapSetSearchDocument(
        beatmapset_id=model.beatmapset_id,
        artist=model.artist,
        title=model.title,
        creator=model.creator,
        artist_unicode=model.artist_unicode,
        title_unicode=model.title_unicode,
        source=model.source,
        tags=model.tags,
        difficulty_names=model.difficulty_names,
        modes=tuple(BeatmapMode(value) for value in model.modes),
        status=BeatmapRankStatus(model.status),
        last_update_at=model.last_update_at,
        is_active=model.is_active,
        document_version=model.document_version,
        updated_at=model.updated_at,
    )


def _index_state_to_model(state: DirectExternalIndexState) -> BeatmapDirectExternalIndexStateModel:
    """Domain external index stateをSQLAlchemy保存modelへ変換する.

    Args:
        state (DirectExternalIndexState): 保存するexternal index同期状態.

    Returns:
        BeatmapDirectExternalIndexStateModel: enumを永続化値へ変換したmodel.
    """
    return BeatmapDirectExternalIndexStateModel(
        backend=state.backend.value,
        beatmapset_id=state.beatmapset_id,
        document_version=state.document_version,
        status=state.status.value,
        last_attempted_at=state.last_attempted_at,
        last_succeeded_at=state.last_succeeded_at,
        failure_reason=state.failure_reason,
    )


def _beatmapset_to_domain(model: BeatmapSetModel, beatmaps: tuple[Beatmap, ...]) -> BeatmapSet:
    """SQLAlchemy beatmapset model と子 beatmap を domain value へ変換する.

    Args:
        model (BeatmapSetModel): 永続化済みの beatmapset model.
        beatmaps (tuple[Beatmap, ...]): model に属する変換済みの子 beatmap.

    Returns:
        BeatmapSet: enum と verification を復元した domain beatmapset.

    Raises:
        ValueError: 保存済みの official status または metadata source が不正な場合.
    """
    return BeatmapSet(
        id=model.id,
        artist=model.artist,
        title=model.title,
        creator=model.creator,
        artist_unicode=model.artist_unicode,
        title_unicode=model.title_unicode,
        official_status=BeatmapRankStatus(model.official_status),
        official_status_source=BeatmapMetadataSource(model.official_status_source),
        official_status_verified=_verification_from_bool(model.official_status_verified),
        beatmaps=beatmaps,
        last_fetched_at=model.last_fetched_at,
        next_refresh_at=model.next_refresh_at,
    )


def _beatmap_to_domain(
    model: BeatmapModel, attachment_model: BeatmapFileAttachmentModel | None
) -> Beatmap:
    """SQLAlchemy beatmap model と current attachment を domain value へ変換する.

    Args:
        model (BeatmapModel): 永続化済みの beatmap model.
        attachment_model (BeatmapFileAttachmentModel | None): 現在の attachment model. 未登録時は
            None.

    Returns:
        Beatmap: enum,decimal,file state,current attachment を復元した domain beatmap.

    Raises:
        ValueError: 保存済みの enum 値または attachment source が不正な場合.
    """
    attachment = _attachment_to_domain(attachment_model) if attachment_model is not None else None
    return Beatmap(
        id=model.id,
        beatmapset_id=model.beatmapset_id,
        checksum_md5=model.checksum_md5 or "",
        mode=BeatmapMode(model.mode),
        version=model.version,
        total_length=model.total_length,
        hit_length=model.hit_length,
        max_combo=model.max_combo,
        bpm=float(model.bpm) if model.bpm is not None else None,
        cs=float(model.cs) if model.cs is not None else None,
        od=float(model.od) if model.od is not None else None,
        ar=float(model.ar) if model.ar is not None else None,
        hp=float(model.hp) if model.hp is not None else None,
        difficulty_rating=(
            float(model.difficulty_rating) if model.difficulty_rating is not None else None
        ),
        official_status=BeatmapRankStatus(model.official_status),
        official_status_source=BeatmapMetadataSource(model.official_status_source),
        official_status_verified=_verification_from_bool(model.official_status_verified),
        local_status_override=(
            LocalBeatmapStatus(model.local_status_override)
            if model.local_status_override is not None
            else None
        ),
        metadata_fetch_state=BeatmapFetchState.FRESH,
        file_state=(
            BeatmapFileState.AVAILABLE if attachment is not None else BeatmapFileState.MISSING
        ),
        file_attachment=attachment,
        last_fetched_at=model.last_fetched_at,
        next_refresh_at=model.next_refresh_at,
        official_last_updated_at=model.official_last_updated_at,
        local_status_override_changed_at=model.local_status_override_changed_at,
    )


def _attachment_to_model(attachment: BeatmapFileAttachment) -> BeatmapFileAttachmentModel:
    """Domain beatmap file attachment を SQLAlchemy 保存 model へ変換する.

    Args:
        attachment (BeatmapFileAttachment): verified checksum と blob ID を持つ domain attachment.

    Returns:
        BeatmapFileAttachmentModel: verified MD5 を attachment checksum として設定した未保存 model.
    """
    return BeatmapFileAttachmentModel(
        beatmap_id=attachment.beatmap_id,
        blob_id=attachment.blob_id,
        checksum_md5=attachment.checksum_md5,
        verified_md5=attachment.checksum_md5,
        source=attachment.source.value,
        original_filename=attachment.original_filename,
        fetched_at=attachment.fetched_at,
        verified_at=attachment.verified_at,
    )


def _attachment_to_domain(model: BeatmapFileAttachmentModel) -> BeatmapFileAttachment:
    """SQLAlchemy file attachment model を domain attachment へ変換する.

    Args:
        model (BeatmapFileAttachmentModel): 永続化済みの beatmap file attachment model.

    Returns:
        BeatmapFileAttachment: file source と時刻を復元した domain attachment.

    Raises:
        ValueError: 保存済みの file source が不正な場合.
    """
    return BeatmapFileAttachment(
        beatmap_id=model.beatmap_id,
        blob_id=model.blob_id,
        checksum_md5=model.checksum_md5,
        source=BeatmapFileSource(model.source),
        original_filename=model.original_filename,
        fetched_at=model.fetched_at,
        verified_at=model.verified_at,
        id=model.id,
    )


def _fetch_state_to_domain(model: BeatmapFetchStateModel) -> BeatmapFetchRecord:
    """SQLAlchemy fetch state model を domain fetch record へ変換する.

    Args:
        model (BeatmapFetchStateModel): 永続化済みの target kind,key,state を持つ model.

    Returns:
        BeatmapFetchRecord: target と lifecycle state を復元した domain fetch record.

    Raises:
        ValueError: 保存済みの target kind または fetch state が不正な場合.
    """
    return BeatmapFetchRecord(
        target=BeatmapFetchTarget(
            target_type=BeatmapFetchTargetKind(model.target_type),
            target_key=model.target_key,
        ),
        status=BeatmapFetchState(model.status),
        attempt_count=model.attempt_count,
        last_error=model.last_error,
        pending_since=model.pending_since,
        last_attempted_at=model.last_attempted_at,
    )


def _verification_from_bool(is_verified: bool) -> BeatmapSourceVerification:
    """永続化された verification flag を domain enum へ変換する.

    Args:
        is_verified (bool): upstream source を検証済みとして保存した flag.

    Returns:
        BeatmapSourceVerification: True は VERIFIED. False は UNVERIFIED.
    """
    return (
        BeatmapSourceVerification.VERIFIED if is_verified else BeatmapSourceVerification.UNVERIFIED
    )


def _decimal_or_none(value: float | None) -> Decimal | None:
    """Optional float を精度を保つ Decimal へ変換する.

    Args:
        value (float | None): beatmap difficulty metadata の浮動小数値. 未提供時は None.

    Returns:
        Decimal | None: str 表現を経由して生成した Decimal. value が None の場合は None.
    """
    if value is None:
        return None
    return Decimal(str(value))


def _count_value(value: object) -> int:
    """SQLAlchemy returning row の count 値が int であることを検証する.

    Args:
        value (object): returning row から取得した play count または pass count.

    Returns:
        int: int 型と確認した count 値.

    Raises:
        TypeError: value が int ではない場合.
    """
    if not isinstance(value, int):
        msg = f"expected integer count value, got {type(value).__name__}"
        raise TypeError(msg)
    return value


def _existing_count(value: object) -> int:
    """既存 model の optional count を非 null int へ正規化する.

    Args:
        value (object): 保存済み count. legacy row では None を取り得る.

    Returns:
        int: value が None の場合は 0. それ以外は検証済みの int.

    Raises:
        TypeError: None 以外の value が int ではない場合.
    """
    if value is None:
        return 0
    return _count_value(value)
