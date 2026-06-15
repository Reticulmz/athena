"""Query-side legacy getscores repository contract."""

from __future__ import annotations

from typing import TYPE_CHECKING, Protocol

if TYPE_CHECKING:
    from osu_server.domain.beatmaps import Beatmap, BeatmapSet


class BeatmapScoreListingQueryRepository(Protocol):
    """Read-only beatmap resolution port for stable getscores responses."""

    async def find_by_checksum(self, checksum_md5: str) -> Beatmap | None:
        """Return a beatmap matching the stable client checksum."""
        ...

    async def find_by_filename_in_beatmapset(
        self, beatmapset_id: int, original_filename: str
    ) -> Beatmap | None:
        """Return a beatmap matching a filename within a beatmap set."""
        ...

    async def get_beatmapset(self, beatmapset_id: int) -> BeatmapSet | None:
        """Return the beatmap set for response header construction."""
        ...
