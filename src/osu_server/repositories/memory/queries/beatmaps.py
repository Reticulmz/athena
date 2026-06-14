"""In-memory query-side beatmap repository adapters."""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from osu_server.domain.beatmaps import (
        Beatmap,
        BeatmapFetchRecord,
        BeatmapFetchTarget,
        BeatmapFileAttachment,
        BeatmapSet,
    )
    from osu_server.repositories.interfaces.queries.beatmaps import BeatmapQueryRepository


class InMemoryBeatmapQueryRepository:
    """Read-only beatmap query adapter over the current in-memory beatmap store."""

    _repository: BeatmapQueryRepository

    def __init__(self, repository: BeatmapQueryRepository) -> None:
        self._repository = repository

    async def get_beatmap(self, beatmap_id: int) -> Beatmap | None:
        return await self._repository.get_beatmap(beatmap_id)

    async def get_beatmapset(self, beatmapset_id: int) -> BeatmapSet | None:
        return await self._repository.get_beatmapset(beatmapset_id)

    async def get_beatmap_by_checksum(self, checksum_md5: str) -> Beatmap | None:
        return await self._repository.get_beatmap_by_checksum(checksum_md5)

    async def get_beatmap_by_filename_in_beatmapset(
        self, beatmapset_id: int, original_filename: str
    ) -> Beatmap | None:
        return await self._repository.get_beatmap_by_filename_in_beatmapset(
            beatmapset_id,
            original_filename,
        )

    async def get_current_file_attachment(self, beatmap_id: int) -> BeatmapFileAttachment | None:
        return await self._repository.get_current_file_attachment(beatmap_id)

    async def get_fetch_state(self, target: BeatmapFetchTarget) -> BeatmapFetchRecord | None:
        return await self._repository.get_fetch_state(target)
