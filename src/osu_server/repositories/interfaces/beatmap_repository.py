from __future__ import annotations

from typing import TYPE_CHECKING, Protocol, runtime_checkable

from osu_server.domain.beatmaps import BeatmapFetchRecord, BeatmapFetchTarget

if TYPE_CHECKING:
    from datetime import datetime

    from osu_server.domain.beatmaps import (
        Beatmap,
        BeatmapFileAttachment,
        BeatmapSet,
        LocalBeatmapStatus,
    )


class DuplicateBeatmapChecksumError(ValueError):
    checksum_md5: str
    existing_beatmap_id: int

    def __init__(self, *, checksum_md5: str, existing_beatmap_id: int) -> None:
        self.checksum_md5 = checksum_md5
        self.existing_beatmap_id = existing_beatmap_id
        super().__init__(
            f"checksum {checksum_md5} already belongs to beatmap {existing_beatmap_id}"
        )


class BeatmapNotFoundError(LookupError):
    beatmap_id: int

    def __init__(self, beatmap_id: int) -> None:
        self.beatmap_id = beatmap_id
        super().__init__(f"beatmap {beatmap_id} was not found")


@runtime_checkable
class BeatmapRepository(Protocol):
    async def get_beatmap(self, beatmap_id: int) -> Beatmap | None: ...

    async def get_beatmapset(self, beatmapset_id: int) -> BeatmapSet | None: ...

    async def get_beatmap_by_checksum(self, checksum_md5: str) -> Beatmap | None: ...

    async def get_beatmap_by_filename_in_beatmapset(
        self, beatmapset_id: int, original_filename: str
    ) -> Beatmap | None: ...

    async def save_beatmapset_snapshot(self, snapshot: BeatmapSet) -> None: ...

    async def set_local_status_override(
        self, beatmap_id: int, status: LocalBeatmapStatus | None
    ) -> Beatmap: ...

    async def get_current_file_attachment(
        self, beatmap_id: int
    ) -> BeatmapFileAttachment | None: ...

    async def attach_osu_file(
        self, attachment: BeatmapFileAttachment
    ) -> BeatmapFileAttachment: ...

    async def get_fetch_state(self, target: BeatmapFetchTarget) -> BeatmapFetchRecord | None: ...

    async def try_mark_fetch_pending(self, target: BeatmapFetchTarget, now: datetime) -> bool: ...

    async def mark_fetch_succeeded(self, target: BeatmapFetchTarget, now: datetime) -> None: ...

    async def mark_fetch_failed(
        self, target: BeatmapFetchTarget, reason: str, now: datetime
    ) -> None: ...


__all__ = [
    "BeatmapFetchRecord",
    "BeatmapFetchTarget",
    "BeatmapNotFoundError",
    "BeatmapRepository",
    "DuplicateBeatmapChecksumError",
]
