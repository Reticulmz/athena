"""Command-side beatmap repository contract."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Protocol, runtime_checkable

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


@dataclass(frozen=True, slots=True)
class BeatmapSubmissionCounts:
    """beatmap 単位の submitted play/pass count。"""

    play_count: int
    pass_count: int

    def __post_init__(self) -> None:
        """count として不正な負数を拒否する。"""
        if self.play_count < 0:
            msg = "play_count must be non-negative"
            raise ValueError(msg)
        if self.pass_count < 0:
            msg = "pass_count must be non-negative"
            raise ValueError(msg)
        if self.pass_count > self.play_count:
            msg = "pass_count must not exceed play_count"
            raise ValueError(msg)


@runtime_checkable
class BeatmapCommandRepository(Protocol):
    """Mutation and consistency-check port for beatmap refresh workflows."""

    async def get_beatmap(self, beatmap_id: int) -> Beatmap | None:
        """Return a beatmap for command-side consistency checks."""
        ...

    async def get_beatmapset(self, beatmapset_id: int) -> BeatmapSet | None:
        """Return a beatmap set for command-side consistency checks."""
        ...

    async def get_beatmap_by_checksum(self, checksum_md5: str) -> Beatmap | None:
        """Return a beatmap by checksum for command-side consistency checks."""
        ...

    async def get_beatmap_by_filename_in_beatmapset(
        self, beatmapset_id: int, original_filename: str
    ) -> Beatmap | None:
        """Return a beatmap by filename within a set for command checks."""
        ...

    async def save_beatmapset_snapshot(self, snapshot: BeatmapSet) -> None:
        """Persist a fetched beatmap set snapshot."""
        ...

    async def set_local_status_override(
        self, beatmap_id: int, status: LocalBeatmapStatus | None
    ) -> Beatmap:
        """Persist a local beatmap status override."""
        ...

    async def increment_submission_counts(
        self,
        beatmap_id: int,
        *,
        passed: bool,
    ) -> BeatmapSubmissionCounts:
        """Increment submitted play/pass count and return the post-increment values."""
        ...

    async def get_current_file_attachment(self, beatmap_id: int) -> BeatmapFileAttachment | None:
        """Return the current file attachment for command-side checks."""
        ...

    async def attach_osu_file(self, attachment: BeatmapFileAttachment) -> BeatmapFileAttachment:
        """Attach an osu file blob to a beatmap."""
        ...

    async def get_fetch_state(self, target: BeatmapFetchTarget) -> BeatmapFetchRecord | None:
        """Return fetch state for command-side concurrency checks."""
        ...

    async def try_mark_fetch_pending(self, target: BeatmapFetchTarget, now: datetime) -> bool:
        """Try to claim a fetch target for work."""
        ...

    async def mark_fetch_succeeded(self, target: BeatmapFetchTarget, now: datetime) -> None:
        """Mark a fetch target as completed successfully."""
        ...

    async def mark_fetch_failed(
        self, target: BeatmapFetchTarget, reason: str, now: datetime
    ) -> None:
        """Mark a fetch target as failed."""
        ...
