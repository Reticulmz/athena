"""in-memory beatmap command/query state用のtest supportを提供する."""

from __future__ import annotations

from typing import TYPE_CHECKING

from osu_server.repositories.memory.commands.state import InMemoryCommandRepositoryState
from osu_server.repositories.memory.queries.beatmaps import InMemoryBeatmapQueryRepository
from osu_server.repositories.memory.unit_of_work import InMemoryUnitOfWorkFactory

if TYPE_CHECKING:
    from datetime import datetime

    from osu_server.domain.beatmaps import (
        Beatmap,
        BeatmapFetchRecord,
        BeatmapFetchTarget,
        BeatmapFileAttachment,
        BeatmapSet,
        LocalBeatmapStatus,
    )
    from osu_server.repositories.interfaces.queries.beatmaps import BeatmapQueryRepository
    from osu_server.repositories.interfaces.unit_of_work import UnitOfWorkFactory


class InMemoryBeatmapStore:
    """commandとquery testで共有するin-memory beatmap stateを提供する.

    Attributes:
        _uow_factory (InMemoryUnitOfWorkFactory): command mutationをcommitするUnit of Work factory.
        _query_repository (InMemoryBeatmapQueryRepository): 同じstateを読むquery repository.
    """

    _uow_factory: InMemoryUnitOfWorkFactory
    _query_repository: InMemoryBeatmapQueryRepository

    def __init__(self) -> None:
        """共有command stateとそれを読むquery repositoryを初期化する.

        Notes:
            factoryとrepositoryは同じin-memory stateを共有する.
        """
        state = InMemoryCommandRepositoryState()
        self._uow_factory = InMemoryUnitOfWorkFactory(state)
        self._query_repository = InMemoryBeatmapQueryRepository(self._uow_factory)

    @property
    def uow_factory(self) -> UnitOfWorkFactory:
        """共有command stateをmutationするUnit of Work factoryを返す.

        Returns:
            UnitOfWorkFactory: testがcommand boundaryへ渡せるfactory.
        """
        return self._uow_factory

    @property
    def query_repository(self) -> BeatmapQueryRepository:
        """共有command stateを読むbeatmap query repositoryを返す.

        Returns:
            BeatmapQueryRepository: testがquery boundaryへ渡せるrepository.
        """
        return self._query_repository

    async def get_beatmap(self, beatmap_id: int) -> Beatmap | None:
        """共有stateからbeatmap IDに対応するbeatmapを取得する.

        Args:
            beatmap_id (int): 取得するbeatmapの識別子.

        Returns:
            Beatmap | None: 保存済みbeatmap. 対応するrecordがない場合はNone.
        """
        return await self._query_repository.get_beatmap(beatmap_id)

    async def get_beatmapset(self, beatmapset_id: int) -> BeatmapSet | None:
        """共有stateからbeatmapset IDに対応するbeatmapsetを取得する.

        Args:
            beatmapset_id (int): 取得するbeatmapsetの識別子.

        Returns:
            BeatmapSet | None: 保存済みbeatmapset. 対応するrecordがない場合はNone.
        """
        return await self._query_repository.get_beatmapset(beatmapset_id)

    async def get_beatmap_by_checksum(self, checksum_md5: str) -> Beatmap | None:
        """共有stateからMD5 checksumに対応するbeatmapを取得する.

        Args:
            checksum_md5 (str): 取得対象beatmapのMD5 checksum.

        Returns:
            Beatmap | None: checksumが一致するbeatmap. 対応するrecordがない場合はNone.
        """
        return await self._query_repository.get_beatmap_by_checksum(checksum_md5)

    async def get_beatmap_by_filename_in_beatmapset(
        self, beatmapset_id: int, original_filename: str
    ) -> Beatmap | None:
        """beatmapset内のoriginal filenameに対応するbeatmapを取得する.

        Args:
            beatmapset_id (int): 検索対象beatmapsetの識別子.
            original_filename (str): beatmapset内で照合するoriginal filename.

        Returns:
            Beatmap | None: filenameが一致するbeatmap. 対応するrecordがない場合はNone.
        """
        return await self._query_repository.get_beatmap_by_filename_in_beatmapset(
            beatmapset_id,
            original_filename,
        )

    async def get_current_file_attachment(self, beatmap_id: int) -> BeatmapFileAttachment | None:
        """beatmapに現在紐付くosu file attachmentを取得する.

        Args:
            beatmap_id (int): attachmentを取得するbeatmapの識別子.

        Returns:
            BeatmapFileAttachment | None: 現在のattachment. 未登録の場合はNone.
        """
        return await self._query_repository.get_current_file_attachment(beatmap_id)

    async def get_fetch_state(self, target: BeatmapFetchTarget) -> BeatmapFetchRecord | None:
        """指定fetch targetの現在のfetch recordを取得する.

        Args:
            target (BeatmapFetchTarget): fetch stateを照会するtarget.

        Returns:
            BeatmapFetchRecord | None: 保存済みfetch record. 未登録の場合はNone.
        """
        return await self._query_repository.get_fetch_state(target)

    async def save_beatmapset_snapshot(self, snapshot: BeatmapSet) -> None:
        """Beatmapset snapshotを共有command stateへ保存してcommitする.

        Args:
            snapshot (BeatmapSet): 保存するbeatmapsetとそのbeatmap snapshot.

        Returns:
            None: snapshotをcommitし, 呼び出し側へ値を返さずに完了する.
        """
        async with self._uow_factory() as uow:
            await uow.beatmaps.save_beatmapset_snapshot(snapshot)
            await uow.commit()

    async def set_local_status_override(
        self, beatmap_id: int, status: LocalBeatmapStatus | None
    ) -> Beatmap:
        """beatmapのlocal status overrideを保存して更新後のbeatmapを返す.

        Args:
            beatmap_id (int): overrideを設定するbeatmapの識別子.
            status (LocalBeatmapStatus | None): 保存するlocal status. Noneはoverride解除を表す.

        Returns:
            Beatmap: commit済みの更新後beatmap.
        """
        async with self._uow_factory() as uow:
            beatmap = await uow.beatmaps.set_local_status_override(beatmap_id, status)
            await uow.commit()
            return beatmap

    async def try_mark_fetch_pending(self, target: BeatmapFetchTarget, now: datetime) -> bool:
        """Fetch targetをpendingへ遷移できたかをcommit後に返す.

        Args:
            target (BeatmapFetchTarget): pending取得を試行するtarget.
            now (datetime): pending transitionを記録する現在時刻.

        Returns:
            bool: pending ownershipを取得できた場合はTrue. 既存状態が阻害する場合はFalse.
        """
        async with self._uow_factory() as uow:
            acquired = await uow.beatmaps.try_mark_fetch_pending(target, now)
            await uow.commit()
            return acquired
