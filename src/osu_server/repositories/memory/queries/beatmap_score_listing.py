"""In-memory query-side legacy getscores repository."""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from osu_server.domain.beatmaps import Beatmap, BeatmapSet
    from osu_server.repositories.interfaces.queries.beatmaps import BeatmapQueryRepository


class InMemoryBeatmapScoreListingQueryRepository:
    """Read-only getscores adapter over an in-memory beatmap query repository."""

    def __init__(self, beatmaps: BeatmapQueryRepository) -> None:
        self._beatmaps: BeatmapQueryRepository = beatmaps

    async def find_by_checksum(self, checksum_md5: str) -> Beatmap | None:
        return await self._beatmaps.get_beatmap_by_checksum(checksum_md5)

    async def find_by_filename_in_beatmapset(
        self, beatmapset_id: int, original_filename: str
    ) -> Beatmap | None:
        return await self._beatmaps.get_beatmap_by_filename_in_beatmapset(
            beatmapset_id,
            original_filename,
        )

    async def get_beatmapset(self, beatmapset_id: int) -> BeatmapSet | None:
        return await self._beatmaps.get_beatmapset(beatmapset_id)
