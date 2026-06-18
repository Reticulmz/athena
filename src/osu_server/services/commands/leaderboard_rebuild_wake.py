"""Adapter-independent boundary for waking Beatmap Leaderboard rebuild workers."""

from __future__ import annotations

from typing import Protocol, final


class BeatmapLeaderboardRebuildWorkerWake(Protocol):
    """Boundary used by commands that need asynchronous leaderboard reconciliation."""

    async def wake_user_rebuild(self, *, user_id: int, reason: str) -> None:
        """Wake rebuild processing for all leaderboard projections owned by one user."""
        ...

    async def wake_beatmapset_rebuild(self, *, beatmapset_id: int, reason: str) -> None:
        """Wake rebuild processing for one beatmapset projection slice."""
        ...


@final
class NoopBeatmapLeaderboardRebuildWorkerWake:
    """Worker wake boundary used when async rebuild dispatch is not wired."""

    async def wake_user_rebuild(self, *, user_id: int, reason: str) -> None:
        _ = (user_id, reason)

    async def wake_beatmapset_rebuild(self, *, beatmapset_id: int, reason: str) -> None:
        _ = (beatmapset_id, reason)


__all__ = [
    "BeatmapLeaderboardRebuildWorkerWake",
    "NoopBeatmapLeaderboardRebuildWorkerWake",
]
