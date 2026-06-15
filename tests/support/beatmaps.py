"""Test helpers for in-memory beatmap command/query state."""

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
    """Shared in-memory beatmap state for command and query tests."""

    _uow_factory: InMemoryUnitOfWorkFactory
    _query_repository: InMemoryBeatmapQueryRepository

    def __init__(self) -> None:
        state = InMemoryCommandRepositoryState()
        self._uow_factory = InMemoryUnitOfWorkFactory(state)
        self._query_repository = InMemoryBeatmapQueryRepository(self._uow_factory)

    @property
    def uow_factory(self) -> UnitOfWorkFactory:
        return self._uow_factory

    @property
    def query_repository(self) -> BeatmapQueryRepository:
        return self._query_repository

    async def get_beatmap(self, beatmap_id: int) -> Beatmap | None:
        return await self._query_repository.get_beatmap(beatmap_id)

    async def get_beatmapset(self, beatmapset_id: int) -> BeatmapSet | None:
        return await self._query_repository.get_beatmapset(beatmapset_id)

    async def get_beatmap_by_checksum(self, checksum_md5: str) -> Beatmap | None:
        return await self._query_repository.get_beatmap_by_checksum(checksum_md5)

    async def get_beatmap_by_filename_in_beatmapset(
        self, beatmapset_id: int, original_filename: str
    ) -> Beatmap | None:
        return await self._query_repository.get_beatmap_by_filename_in_beatmapset(
            beatmapset_id,
            original_filename,
        )

    async def get_current_file_attachment(self, beatmap_id: int) -> BeatmapFileAttachment | None:
        return await self._query_repository.get_current_file_attachment(beatmap_id)

    async def get_fetch_state(self, target: BeatmapFetchTarget) -> BeatmapFetchRecord | None:
        return await self._query_repository.get_fetch_state(target)

    async def save_beatmapset_snapshot(self, snapshot: BeatmapSet) -> None:
        async with self._uow_factory() as uow:
            await uow.beatmaps.save_beatmapset_snapshot(snapshot)
            await uow.commit()

    async def set_local_status_override(
        self, beatmap_id: int, status: LocalBeatmapStatus | None
    ) -> Beatmap:
        async with self._uow_factory() as uow:
            beatmap = await uow.beatmaps.set_local_status_override(beatmap_id, status)
            await uow.commit()
            return beatmap

    async def try_mark_fetch_pending(self, target: BeatmapFetchTarget, now: datetime) -> bool:
        async with self._uow_factory() as uow:
            acquired = await uow.beatmaps.try_mark_fetch_pending(target, now)
            await uow.commit()
            return acquired
