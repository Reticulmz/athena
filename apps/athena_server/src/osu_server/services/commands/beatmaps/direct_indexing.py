"""osu!direct検索projectionとexternal indexのrebuild commandを提供するmodule."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from enum import StrEnum
from typing import TYPE_CHECKING, Protocol

from osu_server.domain.beatmaps import (
    DirectExternalIndexBackend,
    DirectExternalIndexState,
    DirectExternalIndexStatus,
)

if TYPE_CHECKING:
    from collections.abc import Sequence

    from osu_server.domain.beatmaps import BeatmapSetSearchDocument
    from osu_server.repositories.interfaces.unit_of_work import UnitOfWorkFactory

_EXTERNAL_INDEX_REBUILD_BATCH_SIZE = 250


class DirectExternalIndexWriter(Protocol):
    """Projection documentをexternal indexへ同期するportを定義する."""

    async def index_document(self, document: BeatmapSetSearchDocument) -> None:
        """Projection documentをexternal indexへ書き込む.

        Args:
            document (BeatmapSetSearchDocument): committed storageから読んだprojection.

        Returns:
            None: external indexが更新要求を受理したことを示す.
        """
        ...


class DirectExternalIndexUpdateOutcome(StrEnum):
    """External index document更新のcommand結果を表す.

    Attributes:
        SUCCEEDED (DirectExternalIndexUpdateOutcome): external index更新とstate記録に成功した.
        FAILED (DirectExternalIndexUpdateOutcome): external index更新に失敗しfailure stateを
            記録した.
        MISSING (DirectExternalIndexUpdateOutcome): 対象projectionが存在しなかった.
    """

    SUCCEEDED = "succeeded"
    FAILED = "failed"
    MISSING = "missing"


@dataclass(slots=True, frozen=True)
class DirectSearchProjectionRebuildResult:
    """Search projection rebuild commandの結果を表す.

    Attributes:
        rebuilt_count (int): 再構築対象として処理したbeatmapset数.
    """

    rebuilt_count: int


@dataclass(slots=True, frozen=True)
class DirectExternalIndexUpdateResult:
    """External index update commandの結果を表す.

    Attributes:
        outcome (DirectExternalIndexUpdateOutcome): document単位の更新結果.
    """

    outcome: DirectExternalIndexUpdateOutcome


@dataclass(slots=True, frozen=True)
class DirectExternalIndexRebuildResult:
    """External index rebuild commandの結果を表す.

    Attributes:
        succeeded_count (int): external index更新とstate記録に成功したdocument数.
        failed_count (int): failure stateを記録したdocument数.
    """

    succeeded_count: int
    failed_count: int


class DirectIndexingCommands:
    """osu!direct検索projectionとexternal indexをoperator操作で再構築する.

    Attributes:
        _unit_of_work_factory (UnitOfWorkFactory): command repositoryを開くUoW factory.
        _external_index_backend (DirectExternalIndexWriter | None): optional external index.
        _backend (DirectExternalIndexBackend): 記録するexternal index backend種別.
    """

    _unit_of_work_factory: UnitOfWorkFactory
    _external_index_backend: DirectExternalIndexWriter | None
    _backend: DirectExternalIndexBackend

    def __init__(
        self,
        *,
        unit_of_work_factory: UnitOfWorkFactory,
        external_index_backend: DirectExternalIndexWriter | None = None,
        backend: DirectExternalIndexBackend = DirectExternalIndexBackend.MEILISEARCH,
    ) -> None:
        """Direct indexing commandに必要な依存を保持する.

        Args:
            unit_of_work_factory (UnitOfWorkFactory): command transactionを開くfactory.
            external_index_backend (DirectExternalIndexWriter | None): optional external index.
            backend (DirectExternalIndexBackend): index stateへ記録するbackend種別.
        """
        self._unit_of_work_factory = unit_of_work_factory
        self._external_index_backend = external_index_backend
        self._backend = backend

    async def rebuild_search_projection(self) -> DirectSearchProjectionRebuildResult:
        """保存済みmetadataからsearch projectionを再構築する.

        Returns:
            DirectSearchProjectionRebuildResult: 処理したbeatmapset数.
        """
        async with self._unit_of_work_factory() as uow:
            rebuilt_count = await uow.beatmaps.rebuild_search_projection(now=datetime.now(UTC))
            await uow.commit()
        return DirectSearchProjectionRebuildResult(rebuilt_count=rebuilt_count)

    async def update_external_index(self, beatmapset_id: int) -> DirectExternalIndexUpdateResult:
        """Committed projectionを読みexternal indexへ同期してstateを記録する.

        Args:
            beatmapset_id (int): external indexへ同期するbeatmapset ID.

        Returns:
            DirectExternalIndexUpdateResult: document単位の同期結果.
        """
        async with self._unit_of_work_factory() as uow:
            document = await uow.beatmaps.get_search_document(beatmapset_id)
            await uow.commit()
        if document is None:
            return DirectExternalIndexUpdateResult(
                outcome=DirectExternalIndexUpdateOutcome.MISSING
            )
        return await self._sync_document(document)

    async def rebuild_external_index(self) -> DirectExternalIndexRebuildResult:
        """Current projection群をexternal indexへ再送してstateを再構築する.

        Returns:
            DirectExternalIndexRebuildResult: 成功/失敗したdocument件数.
        """
        succeeded_count = 0
        failed_count = 0
        after_beatmapset_id = 0
        while True:
            async with self._unit_of_work_factory() as uow:
                documents = await uow.beatmaps.list_search_documents(
                    after_beatmapset_id=after_beatmapset_id,
                    limit=_EXTERNAL_INDEX_REBUILD_BATCH_SIZE,
                )
                await uow.commit()
            if not documents:
                break
            states: list[DirectExternalIndexState] = []
            for document in documents:
                state = await self._sync_document_state(document)
                states.append(state)
                if state.status is DirectExternalIndexStatus.SUCCEEDED:
                    succeeded_count += 1
                else:
                    failed_count += 1
            await self._record_index_states(states)
            after_beatmapset_id = documents[-1].beatmapset_id
        return DirectExternalIndexRebuildResult(
            succeeded_count=succeeded_count,
            failed_count=failed_count,
        )

    async def _sync_document(
        self,
        document: BeatmapSetSearchDocument,
    ) -> DirectExternalIndexUpdateResult:
        """1件のprojectionをexternal indexへ同期してstateを記録する.

        Args:
            document (BeatmapSetSearchDocument): committed storageから読んだprojection.

        Returns:
            DirectExternalIndexUpdateResult: 同期結果.
        """
        state = await self._sync_document_state(document)
        await self._record_index_states((state,))
        outcome = (
            DirectExternalIndexUpdateOutcome.SUCCEEDED
            if state.status is DirectExternalIndexStatus.SUCCEEDED
            else DirectExternalIndexUpdateOutcome.FAILED
        )
        return DirectExternalIndexUpdateResult(outcome=outcome)

    async def _sync_document_state(
        self,
        document: BeatmapSetSearchDocument,
    ) -> DirectExternalIndexState:
        """1件のprojectionをexternal indexへ同期して記録用stateを返す.

        Args:
            document (BeatmapSetSearchDocument): committed storageから読んだprojection.

        Returns:
            DirectExternalIndexState: commit前のdocument単位同期結果.
        """
        attempted_at = datetime.now(UTC)
        if self._external_index_backend is None:
            status = DirectExternalIndexStatus.FAILED
            failure_reason = "external index backend unavailable"
        else:
            try:
                await self._external_index_backend.index_document(document)
            except Exception as exc:
                status = DirectExternalIndexStatus.FAILED
                failure_reason = _sanitize_failure_reason(exc)
            else:
                status = DirectExternalIndexStatus.SUCCEEDED
                failure_reason = None

        return DirectExternalIndexState(
            backend=self._backend,
            beatmapset_id=document.beatmapset_id,
            document_version=document.document_version,
            status=status,
            last_attempted_at=attempted_at,
            last_succeeded_at=(
                attempted_at if status is DirectExternalIndexStatus.SUCCEEDED else None
            ),
            failure_reason=failure_reason,
        )

    async def _record_index_states(
        self,
        states: Sequence[DirectExternalIndexState],
    ) -> None:
        """External index同期状態を1つのUnit of Workで記録する.

        Args:
            states (Sequence[DirectExternalIndexState]): 保存するdocument単位の同期結果.

        Returns:
            None: index state群をcommitして完了する.
        """
        if not states:
            return
        async with self._unit_of_work_factory() as uow:
            for state in states:
                await uow.beatmaps.record_index_state(state)
            await uow.commit()


def _sanitize_failure_reason(exc: Exception) -> str:
    """External index失敗をoperator向けの固定messageへ変換する.

    Args:
        exc (Exception): external index backendから伝播した例外.

    Returns:
        str: credentialやresponse bodyを含まない失敗理由.
    """
    return f"{type(exc).__name__}: external index update failed"


__all__ = [
    "DirectExternalIndexRebuildResult",
    "DirectExternalIndexUpdateOutcome",
    "DirectExternalIndexUpdateResult",
    "DirectExternalIndexWriter",
    "DirectIndexingCommands",
    "DirectSearchProjectionRebuildResult",
]
