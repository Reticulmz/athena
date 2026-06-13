"""Query-side beatmap repository contract."""

from __future__ import annotations

from typing import TYPE_CHECKING, Protocol

if TYPE_CHECKING:
    from osu_server.domain.beatmaps import (
        Beatmap,
        BeatmapFetchRecord,
        BeatmapFetchTarget,
        BeatmapFileAttachment,
        BeatmapSet,
    )


class BeatmapQueryRepository(Protocol):
    """Read-only beatmap access for display and compatibility workflows."""

    async def get_beatmap(self, beatmap_id: int) -> Beatmap | None:
        """Return the beatmap with the identifier."""
        ...

    async def get_beatmapset(self, beatmapset_id: int) -> BeatmapSet | None:
        """Return the beatmap set with the identifier."""
        ...

    async def get_beatmap_by_checksum(self, checksum_md5: str) -> Beatmap | None:
        """Return the beatmap with the checksum."""
        ...

    async def get_beatmap_by_filename_in_beatmapset(
        self, beatmapset_id: int, original_filename: str
    ) -> Beatmap | None:
        """Return the beatmap matching a filename within a beatmap set."""
        ...

    async def get_current_file_attachment(self, beatmap_id: int) -> BeatmapFileAttachment | None:
        """Return the current osu file attachment."""
        ...

    async def get_fetch_state(self, target: BeatmapFetchTarget) -> BeatmapFetchRecord | None:
        """Return metadata/file fetch state for a target."""
        ...
