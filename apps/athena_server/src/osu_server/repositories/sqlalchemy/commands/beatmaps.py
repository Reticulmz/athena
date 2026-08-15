"""SQLAlchemy を用いて beatmap,file attachment,fetch state を永続化する command repository."""

from __future__ import annotations

from collections import defaultdict
from dataclasses import replace
from datetime import UTC, datetime
from decimal import Decimal
from hashlib import blake2b
from typing import TYPE_CHECKING, cast

import structlog
from sqlalchemy import func, literal, or_, select, update
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
    DirectCoverageRecord,
    DirectExternalIndexState,
    LocalBeatmapStatus,
    build_beatmapset_search_document,
)
from osu_server.repositories.interfaces.commands.beatmaps import BeatmapSubmissionCounts
from osu_server.repositories.sqlalchemy.commands.error_details import sqlalchemy_error_details
from osu_server.repositories.sqlalchemy.models.beatmap import (
    BeatmapDirectCoverageModel,
    BeatmapDirectExternalIndexStateModel,
    BeatmapFetchStateModel,
    BeatmapFileAttachmentModel,
    BeatmapModel,
    BeatmapSetModel,
)

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession
    from sqlalchemy.sql.dml import ReturningInsert

logger = cast("structlog.stdlib.BoundLogger", structlog.get_logger(__name__))
_BEATMAP_CHILD_LOOKUP_BATCH_SIZE = 1_000


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


class BeatmapSnapshotPersistenceError(ValueError):
    """Beatmapset snapshotの永続化がDB整合性違反で失敗したときに送出する例外."""


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
        attachment_models_by_beatmap_id = await self._get_current_file_attachment_models(
            beatmap_ids=tuple(beatmap.id for beatmap in beatmap_models),
        )
        beatmaps = [
            _beatmap_to_domain(
                beatmap_model,
                attachment_models_by_beatmap_id.get(beatmap_model.id),
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
            None: sessionへの保存とflushが完了したことを示す. transactionの確定は行わない.

        Raises:
            DuplicateBeatmapChecksumError: snapshot 内または保存済み beatmap と checksum が
                衝突する場合.
        """
        _ = await self.save_beatmapset_snapshot_returning_previous(snapshot)

    async def save_beatmapset_snapshot_returning_previous(
        self,
        snapshot: BeatmapSet,
    ) -> BeatmapSet | None:
        """Beatmapset snapshotを保存し保存前のBeatmapSetを返す.

        Args:
            snapshot (BeatmapSet): upstream metadataから得たbeatmapsetと子beatmapのsnapshot.

        Returns:
            BeatmapSet | None: 保存前のBeatmapSet. 初回保存ではNone.

        Raises:
            DuplicateBeatmapChecksumError: snapshot 内または保存済み beatmap と checksum が
                衝突する場合.

        Notes:
            既存の local status override,submission count,欠損した official 日時を保持する.
        """
        snapshot = _deduplicate_snapshot_beatmaps(snapshot)
        await self._lock_beatmapset_snapshot(snapshot.id)
        (
            existing_beatmapset_model,
            previous_beatmapset,
            previous_document,
            existing_beatmap_models_by_id,
        ) = await self._load_existing_snapshot_state(snapshot)
        stored_snapshot = _merge_beatmapset_official_dates(snapshot, existing_beatmapset_model)
        stored_beatmaps: list[Beatmap] = []
        try:
            stored_beatmapset_model = self._store_beatmapset_model(
                stored_snapshot,
                existing_beatmapset_model,
            )
            if existing_beatmapset_model is None and stored_snapshot.beatmaps:
                await self._session.flush()
            for beatmap in stored_snapshot.beatmaps:
                existing = existing_beatmap_models_by_id.get(beatmap.id)
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
                self._store_beatmap_model(
                    stored_beatmap,
                    existing,
                    local_override,
                    local_override_changed_at,
                    play_count,
                    pass_count,
                )
            stored_snapshot = replace(stored_snapshot, beatmaps=tuple(stored_beatmaps))
            document = build_beatmapset_search_document(
                stored_snapshot,
                previous=previous_document,
                updated_at=datetime.now(UTC),
            )
            _apply_search_document_to_beatmapset_model(stored_beatmapset_model, document)
            await self._session.flush()
        except IntegrityError as exc:
            logger.warning(
                "beatmapset_snapshot_persistence_failed",
                beatmapset_id=snapshot.id,
                **sqlalchemy_error_details(exc),
            )
            msg = f"beatmapset snapshot persistence failed for beatmapset {snapshot.id}"
            raise BeatmapSnapshotPersistenceError(msg) from exc
        return previous_beatmapset

    async def _lock_beatmapset_snapshot(self, beatmapset_id: int) -> None:
        """同一beatmapset snapshot保存をtransaction内で直列化する.

        Args:
            beatmapset_id (int): 保存対象beatmapsetの識別子.

        Returns:
            None: transaction advisory lockを取得したことを示す.
        """
        _ = await self._session.execute(
            select(func.pg_advisory_xact_lock(_beatmapset_snapshot_lock_key(beatmapset_id)))
        )

    async def _get_existing_search_document(
        self,
        beatmapset_id: int,
    ) -> BeatmapSetSearchDocument | None:
        """保存済みmetadataから既存の検索document DTOを組み立てる.

        Args:
            beatmapset_id (int): 既存検索documentを読むbeatmapset ID.

        Returns:
            BeatmapSetSearchDocument | None: 保存済みmetadataから復元したDTO. 未登録ならNone.
        """
        model = await self._session.get(BeatmapSetModel, beatmapset_id)
        if not isinstance(model, BeatmapSetModel):
            return None
        beatmap_models = await self._get_beatmap_models_for_set(beatmapset_id=beatmapset_id)
        return _search_document_from_models(model, tuple(beatmap_models))

    async def _load_existing_snapshot_state(
        self,
        snapshot: BeatmapSet,
    ) -> tuple[
        BeatmapSetModel | None,
        BeatmapSet | None,
        BeatmapSetSearchDocument | None,
        dict[int, BeatmapModel],
    ]:
        """Snapshot保存に必要な既存metadataをまとめて読む.

        Args:
            snapshot (BeatmapSet): 保存予定のbeatmapset snapshot.

        Returns:
            tuple[BeatmapSetModel | None, BeatmapSet | None, BeatmapSetSearchDocument | None,
            dict[int, BeatmapModel]]: 既存set model, 保存前domain set, 保存前検索document,
            既存child modelのID別辞書.

        Raises:
            DuplicateBeatmapChecksumError: snapshot内または既存beatmapとchecksumが衝突する場合.
        """
        incoming_beatmap_ids_by_checksum = _incoming_beatmap_ids_by_checksum(snapshot)
        existing_beatmapset_model = await self._session.get(BeatmapSetModel, snapshot.id)
        existing_beatmap_models = await self._get_snapshot_related_beatmap_models(
            beatmapset_id=snapshot.id,
            checksums=tuple(incoming_beatmap_ids_by_checksum),
        )
        _raise_existing_checksum_conflict(
            existing_beatmap_models,
            incoming_beatmap_ids_by_checksum,
        )

        existing_child_models = tuple(
            model for model in existing_beatmap_models if model.beatmapset_id == snapshot.id
        )
        previous_beatmapset: BeatmapSet | None = None
        previous_document: BeatmapSetSearchDocument | None = None
        if existing_beatmapset_model is not None:
            previous_beatmaps = tuple(
                _beatmap_to_domain(beatmap_model, None) for beatmap_model in existing_child_models
            )
            previous_beatmapset = _beatmapset_to_domain(
                existing_beatmapset_model,
                previous_beatmaps,
            )
            previous_document = _search_document_from_models(
                existing_beatmapset_model,
                existing_child_models,
            )
        return (
            existing_beatmapset_model,
            previous_beatmapset,
            previous_document,
            {model.id: model for model in existing_beatmap_models},
        )

    def _store_beatmapset_model(
        self,
        snapshot: BeatmapSet,
        existing: BeatmapSetModel | None,
    ) -> BeatmapSetModel:
        """Beatmapset modelを新規追加または既存model更新としてsessionへ保持する.

        Args:
            snapshot (BeatmapSet): 保存するbeatmapset snapshot.
            existing (BeatmapSetModel | None): 既存の永続model. 新規時はNone.

        Returns:
            BeatmapSetModel: 検索projection更新にも使う保存対象model.
        """
        model = existing or _beatmapset_to_model(snapshot)
        _apply_beatmapset_to_model(model, snapshot)
        self._session.add(model)
        return model

    def _store_beatmap_model(
        self,
        beatmap: Beatmap,
        existing: BeatmapModel | None,
        local_status_override: str | None,
        local_status_override_changed_at: datetime | None,
        play_count: int,
        pass_count: int,
    ) -> None:
        """Beatmap modelを新規追加または既存model更新としてsessionへ保持する.

        Args:
            beatmap (Beatmap): 保存するchild beatmap snapshot.
            existing (BeatmapModel | None): 既存の永続model. 新規時はNone.
            local_status_override (str | None): 保持するlocal status override.
            local_status_override_changed_at (datetime | None): override更新時刻.
            play_count (int): 保持するplay count.
            pass_count (int): 保持するpass count.

        Returns:
            None: sessionへ保存対象modelを登録して完了する.
        """
        model = existing or _beatmap_to_model(
            beatmap,
            local_status_override,
            local_status_override_changed_at,
            play_count,
            pass_count,
        )
        _apply_beatmap_to_model(
            model,
            beatmap,
            local_status_override,
            local_status_override_changed_at,
            play_count,
            pass_count,
        )
        self._session.add(model)

    async def get_search_document(self, beatmapset_id: int) -> BeatmapSetSearchDocument | None:
        """External indexing用に保存済みmetadataから検索document DTOを返す.

        Args:
            beatmapset_id (int): 検索projectionを取得するbeatmapset ID.

        Returns:
            BeatmapSetSearchDocument | None: 保存済みmetadataから組み立てたDTO. 未登録ならNone.
        """
        return await self._get_existing_search_document(beatmapset_id)

    async def list_search_documents(
        self,
        *,
        after_beatmapset_id: int = 0,
        limit: int | None = None,
    ) -> tuple[BeatmapSetSearchDocument, ...]:
        """External index rebuild用に検索document DTOをbeatmapset ID順で返す.

        Args:
            after_beatmapset_id (int): このBeatmapSet IDより大きいprojectionだけを返す.
            limit (int | None): 返す最大件数. Noneなら全件を返す.

        Returns:
            tuple[BeatmapSetSearchDocument, ...]: 保存済みmetadataから組み立てた検索document列.
        """
        statement = select(BeatmapSetModel).where(BeatmapSetModel.id > after_beatmapset_id)
        statement = statement.order_by(BeatmapSetModel.id.asc())
        if limit is not None:
            statement = statement.limit(limit)
        beatmapset_models = (await self._session.execute(statement)).scalars().all()
        beatmap_models_by_set_id = await self._get_beatmap_models_by_set_id(
            beatmapset_ids=tuple(model.id for model in beatmapset_models)
        )
        return tuple(
            _search_document_from_models(
                model,
                beatmap_models_by_set_id.get(model.id, ()),
            )
            for model in beatmapset_models
        )

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
        beatmap_models_by_set_id = await self._get_beatmap_models_by_set_id(
            beatmapset_ids=tuple(model.id for model in beatmapset_models)
        )
        rebuilt_count = 0
        for beatmapset_model in beatmapset_models:
            beatmap_models = beatmap_models_by_set_id.get(beatmapset_model.id, ())
            beatmaps = tuple(
                _beatmap_to_domain(beatmap_model, None) for beatmap_model in beatmap_models
            )
            previous = _search_document_from_models(beatmapset_model, beatmap_models)
            document = build_beatmapset_search_document(
                _beatmapset_to_domain(beatmapset_model, beatmaps),
                previous=previous,
                updated_at=now,
            )
            if document != previous or beatmapset_model.direct_search_text != _direct_search_text(
                document
            ):
                _apply_search_document_to_beatmapset_model(beatmapset_model, document)
            rebuilt_count += 1
        await self._session.flush()
        return rebuilt_count

    async def record_index_state(self, state: DirectExternalIndexState) -> None:
        """External index documentの同期状態を保存する.

        Args:
            state (DirectExternalIndexState): 保存するsuccessまたはfailure state.

        Returns:
            None: 同期状態をupsertしてflushしたことを示す.
        """
        insert_statement = insert(BeatmapDirectExternalIndexStateModel).values(
            backend=state.backend.value,
            beatmapset_id=state.beatmapset_id,
            document_version=state.document_version,
            status=state.status.value,
            last_attempted_at=state.last_attempted_at,
            last_succeeded_at=state.last_succeeded_at,
            failure_reason=state.failure_reason,
        )
        _ = await self._session.execute(
            insert_statement.on_conflict_do_update(
                index_elements=[
                    BeatmapDirectExternalIndexStateModel.backend,
                    BeatmapDirectExternalIndexStateModel.beatmapset_id,
                ],
                set_={
                    "document_version": state.document_version,
                    "status": state.status.value,
                    "last_attempted_at": state.last_attempted_at,
                    "last_succeeded_at": func.coalesce(
                        insert_statement.excluded.last_succeeded_at,
                        BeatmapDirectExternalIndexStateModel.last_succeeded_at,
                    ),
                    "failure_reason": state.failure_reason,
                },
            )
        )
        await self._session.flush()

    async def record_direct_coverage(self, record: DirectCoverageRecord) -> None:
        """osu!direct catalog coverage recordをupsertする.

        Args:
            record (DirectCoverageRecord): feed windowまたはid range crawlのcoverage record.

        Returns:
            None: coverage stateをsessionへ反映してflushしたことを示す.
        """
        insert_statement = insert(BeatmapDirectCoverageModel).values(
            coverage_kind=record.coverage_kind.value,
            source=record.source.value,
            status_scope=record.status_scope.value,
            sort_key=record.sort_key,
            window_key=record.window_key,
            from_beatmapset_id=record.from_beatmapset_id,
            to_beatmapset_id=record.to_beatmapset_id,
            cursor=record.cursor,
            completed_at=record.completed_at,
            failed_at=record.failed_at,
            failure_reason=record.failure_reason,
        )
        _ = await self._session.execute(
            insert_statement.on_conflict_do_update(
                index_elements=[
                    BeatmapDirectCoverageModel.coverage_kind,
                    BeatmapDirectCoverageModel.source,
                    BeatmapDirectCoverageModel.status_scope,
                    BeatmapDirectCoverageModel.sort_key,
                    BeatmapDirectCoverageModel.window_key,
                    BeatmapDirectCoverageModel.from_beatmapset_id,
                    BeatmapDirectCoverageModel.to_beatmapset_id,
                ],
                set_={
                    "cursor": record.cursor,
                    "completed_at": record.completed_at,
                    "failed_at": record.failed_at,
                    "failure_reason": record.failure_reason,
                },
            )
        )
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
        result = await self._session.execute(
            _mark_fetch_completed_statement(
                target=target,
                status=status,
                last_error=last_error,
                now=now,
            )
        )
        row_id = result.scalar_one()
        _ = await self._session.get(
            BeatmapFetchStateModel,
            row_id,
            populate_existing=True,
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

    async def _get_beatmap_models_by_set_id(
        self,
        *,
        beatmapset_ids: tuple[int, ...],
    ) -> dict[int, tuple[BeatmapModel, ...]]:
        """複数BeatmapSetのchild modelをbeatmapset ID別にまとめて返す.

        Args:
            beatmapset_ids (tuple[int, ...]): 子beatmapを取得するBeatmapSet ID列.

        Returns:
            dict[int, tuple[BeatmapModel, ...]]: BeatmapSet IDごとのchild model列.
        """
        if not beatmapset_ids:
            return {}
        models: list[BeatmapModel] = []
        for start_index in range(0, len(beatmapset_ids), _BEATMAP_CHILD_LOOKUP_BATCH_SIZE):
            batch_ids = beatmapset_ids[
                start_index : start_index + _BEATMAP_CHILD_LOOKUP_BATCH_SIZE
            ]
            models.extend(
                (
                    await self._session.execute(
                        select(BeatmapModel)
                        .where(BeatmapModel.beatmapset_id.in_(batch_ids))
                        .order_by(BeatmapModel.beatmapset_id.asc(), BeatmapModel.id.asc())
                    )
                )
                .scalars()
                .all()
            )
        models_by_set_id: defaultdict[int, list[BeatmapModel]] = defaultdict(list)
        for model in models:
            models_by_set_id[model.beatmapset_id].append(model)
        return {
            beatmapset_id: tuple(beatmap_models)
            for beatmapset_id, beatmap_models in models_by_set_id.items()
        }

    async def _get_snapshot_related_beatmap_models(
        self,
        *,
        beatmapset_id: int,
        checksums: tuple[str, ...],
    ) -> tuple[BeatmapModel, ...]:
        """Snapshot保存前に必要な既存childとchecksum所有者をまとめて返す.

        Args:
            beatmapset_id (int): 保存対象beatmapset ID.
            checksums (tuple[str, ...]): 保存予定childのchecksum列.

        Returns:
            tuple[BeatmapModel, ...]: 保存対象setの既存childとchecksum衝突確認対象.
        """
        where_clause = BeatmapModel.beatmapset_id == beatmapset_id
        if checksums:
            where_clause = or_(where_clause, BeatmapModel.checksum_md5.in_(checksums))
        return tuple(
            (
                await self._session.execute(
                    select(BeatmapModel).where(where_clause).order_by(BeatmapModel.id.asc())
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

    async def _get_current_file_attachment_models(
        self, *, beatmap_ids: tuple[int, ...]
    ) -> dict[int, BeatmapFileAttachmentModel]:
        """複数 Beatmap の最大 ID を持つ file attachment model をまとめて返す.

        Args:
            beatmap_ids (tuple[int, ...]): attachment を検索する beatmap ID列.

        Returns:
            dict[int, BeatmapFileAttachmentModel]: beatmap ID別のcurrent attachment model.
        """
        if not beatmap_ids:
            return {}
        rows = (
            (
                await self._session.execute(
                    select(BeatmapFileAttachmentModel)
                    .where(BeatmapFileAttachmentModel.beatmap_id.in_(beatmap_ids))
                    .order_by(
                        BeatmapFileAttachmentModel.beatmap_id.asc(),
                        BeatmapFileAttachmentModel.id.desc(),
                    )
                )
            )
            .scalars()
            .all()
        )
        attachments: dict[int, BeatmapFileAttachmentModel] = {}
        for model in rows:
            if model.beatmap_id not in attachments:
                attachments[model.beatmap_id] = model
        return attachments

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


def _mark_fetch_completed_statement(
    *,
    target: BeatmapFetchTarget,
    status: BeatmapFetchState,
    last_error: str | None,
    now: datetime,
):
    """Fetch stateを完了状態へupsertするstatementを構築する.

    Args:
        target (BeatmapFetchTarget): 更新するfetch target.
        status (BeatmapFetchState): 保存する完了状態.
        last_error (str | None): failed時の理由. fresh時はNone.
        now (datetime): 完了時刻.

    Returns:
        Insert: fetch stateを再読込せずに完了状態へ保存するPostgreSQL upsert statement.
    """
    insert_statement = insert(BeatmapFetchStateModel).values(
        target_type=target.kind.value,
        target_key=target.target_key,
        status=status.value,
        attempt_count=0,
        last_error=last_error,
        pending_since=None,
        last_attempted_at=now,
    )
    return insert_statement.on_conflict_do_update(
        index_elements=[
            BeatmapFetchStateModel.target_type,
            BeatmapFetchStateModel.target_key,
        ],
        set_={
            "status": status.value,
            "last_error": last_error,
            "pending_since": None,
            "last_attempted_at": now,
            "updated_at": func.now(),
        },
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


def _incoming_beatmap_ids_by_checksum(snapshot: BeatmapSet) -> dict[str, int]:
    """Snapshot内のchecksum所有beatmap IDを返す.

    Args:
        snapshot (BeatmapSet): checksum重複を検査するsnapshot.

    Returns:
        dict[str, int]: checksum別のincoming beatmap ID.

    Raises:
        DuplicateBeatmapChecksumError: 同じchecksumが別IDのchildに割り当てられた場合.
    """
    beatmap_ids_by_checksum: dict[str, int] = {}
    for beatmap in snapshot.beatmaps:
        existing_beatmap_id = beatmap_ids_by_checksum.get(beatmap.checksum_md5)
        if existing_beatmap_id is not None and existing_beatmap_id != beatmap.id:
            raise DuplicateBeatmapChecksumError(
                checksum_md5=beatmap.checksum_md5,
                existing_beatmap_id=existing_beatmap_id,
            )
        beatmap_ids_by_checksum[beatmap.checksum_md5] = beatmap.id
    return beatmap_ids_by_checksum


def _deduplicate_snapshot_beatmaps(snapshot: BeatmapSet) -> BeatmapSet:
    """同じbeatmap IDが重複したsnapshotを保存可能な子列へ正規化する.

    Args:
        snapshot (BeatmapSet): providerから得たbeatmapset snapshot.

    Returns:
        BeatmapSet: 各beatmap IDを初出1件にしたsnapshot. 重複がなければ入力をそのまま返す.
    """
    seen_ids: set[int] = set()
    beatmaps: list[Beatmap] = []
    for beatmap in snapshot.beatmaps:
        if beatmap.id in seen_ids:
            continue
        seen_ids.add(beatmap.id)
        beatmaps.append(beatmap)
    if len(beatmaps) == len(snapshot.beatmaps):
        return snapshot
    return replace(snapshot, beatmaps=tuple(beatmaps))


def _raise_existing_checksum_conflict(
    existing_models: tuple[BeatmapModel, ...],
    incoming_beatmap_ids_by_checksum: dict[str, int],
) -> None:
    """既存beatmapとincoming snapshotのchecksum衝突を拒否する.

    Args:
        existing_models (tuple[BeatmapModel, ...]): checksum照合用に取得済みの既存model列.
        incoming_beatmap_ids_by_checksum (dict[str, int]): checksum別のincoming beatmap ID.

    Returns:
        None: checksum所有者が衝突しないことを示す.

    Raises:
        DuplicateBeatmapChecksumError: 既存beatmapが別IDで同じchecksumを所有する場合.
    """
    for model in existing_models:
        if model.checksum_md5 is None:
            continue
        incoming_beatmap_id = incoming_beatmap_ids_by_checksum.get(model.checksum_md5)
        if incoming_beatmap_id is not None and incoming_beatmap_id != model.id:
            raise DuplicateBeatmapChecksumError(
                checksum_md5=model.checksum_md5,
                existing_beatmap_id=model.id,
            )


def _merge_beatmapset_official_dates(
    snapshot: BeatmapSet,
    existing: BeatmapSetModel | None,
) -> BeatmapSet:
    """Incoming snapshotに既存beatmapsetの公式日時を必要に応じて補う.

    Args:
        snapshot (BeatmapSet): 保存するincoming beatmapset snapshot.
        existing (BeatmapSetModel | None): 既存の永続beatmapset model. 未登録時はNone.

    Returns:
        BeatmapSet: incoming値を優先し,欠損した公式日時だけ既存値で補ったsnapshot.
    """
    if existing is None:
        return snapshot
    return replace(
        snapshot,
        official_submitted_at=(
            snapshot.official_submitted_at
            if snapshot.official_submitted_at is not None
            else existing.official_submitted_at
        ),
        official_ranked_at=(
            snapshot.official_ranked_at
            if snapshot.official_ranked_at is not None
            else existing.official_ranked_at
        ),
        official_last_updated_at=(
            snapshot.official_last_updated_at
            if snapshot.official_last_updated_at is not None
            else existing.official_last_updated_at
        ),
    )


def _beatmapset_snapshot_lock_key(beatmapset_id: int) -> int:
    """Beatmapset snapshot保存scopeをPostgreSQL advisory lock keyへ変換する.

    Args:
        beatmapset_id (int): 保存対象beatmapsetの識別子.

    Returns:
        int: `pg_advisory_xact_lock`へ渡すsigned 64-bit key.
    """
    namespace = f"beatmapset_snapshot:{beatmapset_id}"
    return int.from_bytes(
        blake2b(namespace.encode(), digest_size=8).digest(),
        byteorder="big",
        signed=True,
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
        source_text=beatmapset.source_text,
        tags=beatmapset.tags,
        official_status=beatmapset.official_status.value,
        official_status_source=beatmapset.official_status_source.value,
        official_status_verified=(
            beatmapset.official_status_verified is BeatmapSourceVerification.VERIFIED
        ),
        last_fetched_at=beatmapset.last_fetched_at,
        next_refresh_at=beatmapset.next_refresh_at,
        official_submitted_at=beatmapset.official_submitted_at,
        official_ranked_at=beatmapset.official_ranked_at,
        official_last_updated_at=beatmapset.official_last_updated_at,
    )


def _apply_beatmapset_to_model(model: BeatmapSetModel, beatmapset: BeatmapSet) -> None:
    """Domain beatmapsetの保存fieldを既存modelへ反映する.

    Args:
        model (BeatmapSetModel): 更新するSQLAlchemy model.
        beatmapset (BeatmapSet): upstream metadataを含むdomain beatmapset.

    Returns:
        None: modelのmetadata fieldを更新して完了する.
    """
    model.artist = beatmapset.artist
    model.title = beatmapset.title
    model.creator = beatmapset.creator
    model.artist_unicode = beatmapset.artist_unicode
    model.title_unicode = beatmapset.title_unicode
    model.source_text = beatmapset.source_text
    model.tags = beatmapset.tags
    model.official_status = beatmapset.official_status.value
    model.official_status_source = beatmapset.official_status_source.value
    model.official_status_verified = (
        beatmapset.official_status_verified is BeatmapSourceVerification.VERIFIED
    )
    model.last_fetched_at = beatmapset.last_fetched_at
    model.next_refresh_at = beatmapset.next_refresh_at
    model.official_submitted_at = beatmapset.official_submitted_at
    model.official_ranked_at = beatmapset.official_ranked_at
    model.official_last_updated_at = beatmapset.official_last_updated_at


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


def _apply_beatmap_to_model(
    model: BeatmapModel,
    beatmap: Beatmap,
    local_status_override: str | None,
    local_status_override_changed_at: datetime | None,
    play_count: int,
    pass_count: int,
) -> None:
    """Domain beatmapの保存fieldを既存modelへ反映する.

    Args:
        model (BeatmapModel): 更新するSQLAlchemy model.
        beatmap (Beatmap): upstream metadataを含むdomain beatmap.
        local_status_override (str | None): 保持するlocal status override.
        local_status_override_changed_at (datetime | None): override更新時刻.
        play_count (int): 保持するplay count.
        pass_count (int): 保持するpass count.

    Returns:
        None: modelのmetadata fieldを更新して完了する.
    """
    model.beatmapset_id = beatmap.beatmapset_id
    model.checksum_md5 = beatmap.checksum_md5
    model.mode = beatmap.mode.value
    model.version = beatmap.version
    model.total_length = beatmap.total_length
    model.hit_length = beatmap.hit_length
    model.max_combo = beatmap.max_combo
    model.bpm = _decimal_or_none(beatmap.bpm)
    model.cs = _decimal_or_none(beatmap.cs)
    model.od = _decimal_or_none(beatmap.od)
    model.ar = _decimal_or_none(beatmap.ar)
    model.hp = _decimal_or_none(beatmap.hp)
    model.difficulty_rating = _decimal_or_none(beatmap.difficulty_rating)
    model.official_status = beatmap.official_status.value
    model.official_status_source = beatmap.official_status_source.value
    model.official_status_verified = (
        beatmap.official_status_verified is BeatmapSourceVerification.VERIFIED
    )
    model.local_status_override = local_status_override
    model.local_status_override_changed_at = local_status_override_changed_at
    model.play_count = play_count
    model.pass_count = pass_count
    model.official_last_updated_at = beatmap.official_last_updated_at
    model.last_fetched_at = beatmap.last_fetched_at
    model.next_refresh_at = beatmap.next_refresh_at


def _apply_search_document_to_beatmapset_model(
    model: BeatmapSetModel,
    document: BeatmapSetSearchDocument,
) -> None:
    """検索document DTOの永続化対象fieldをbeatmapset modelへ反映する.

    Args:
        model (BeatmapSetModel): 保存するbeatmapset model.
        document (BeatmapSetSearchDocument): metadataとchildから構築した検索document DTO.

    Returns:
        None: modelの検索入力fieldを更新して値を返さず完了する.
    """
    model.direct_search_text = _direct_search_text(document)
    model.search_document_version = document.document_version
    model.search_document_updated_at = document.updated_at


def _search_document_from_models(
    model: BeatmapSetModel,
    beatmap_models: tuple[BeatmapModel, ...],
) -> BeatmapSetSearchDocument:
    """保存済みbeatmapsetとchild beatmapから検索document DTOを復元する.

    Args:
        model (BeatmapSetModel): 保存済みのbeatmapset model.
        beatmap_models (tuple[BeatmapModel, ...]): modelに属するchild beatmap model列.

    Returns:
        BeatmapSetSearchDocument: external indexとversion比較に使う検索document DTO.
    """
    beatmaps = tuple(_beatmap_to_domain(beatmap_model, None) for beatmap_model in beatmap_models)
    document = build_beatmapset_search_document(
        _beatmapset_to_domain(model, beatmaps),
        updated_at=_search_document_updated_at(model),
    )
    return replace(
        document,
        document_version=_search_document_version(model),
        updated_at=_search_document_updated_at(model),
    )


def _direct_search_text(document: BeatmapSetSearchDocument) -> str:
    """ParadeDB/tsvector用のmaterialized検索入力を返す.

    Args:
        document (BeatmapSetSearchDocument): source of truthから組み立てた検索document DTO.

    Returns:
        str: 宣言済みsearchable fieldを空白結合した検索入力.
    """
    return " ".join(
        part
        for part in (
            document.artist,
            document.title,
            document.creator,
            document.source,
            document.tags,
            document.difficulty_names,
            document.artist_unicode or "",
            document.title_unicode or "",
        )
        if part
    )


def _search_document_version(model: BeatmapSetModel) -> int:
    """保存済み検索document versionを返す.

    Args:
        model (BeatmapSetModel): versionを保持するbeatmapset model.

    Returns:
        int: 正の検索document version. 未設定なら初期値の1.
    """
    return model.search_document_version or 1


def _search_document_updated_at(model: BeatmapSetModel) -> datetime:
    """保存済み検索document更新時刻を返す.

    Args:
        model (BeatmapSetModel): 更新時刻を保持するbeatmapset model.

    Returns:
        datetime: 検索document更新時刻. 未設定なら現在UTC時刻.
    """
    return model.search_document_updated_at or datetime.now(UTC)


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
        official_submitted_at=model.official_submitted_at,
        official_ranked_at=model.official_ranked_at,
        official_last_updated_at=model.official_last_updated_at,
        source_text=model.source_text,
        tags=model.tags,
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
