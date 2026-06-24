"""Beatmap leaderboard 再構築 worker 起動 port です."""

from __future__ import annotations

from typing import Protocol, final


class BeatmapLeaderboardRebuildWorkerWake(Protocol):
    """leaderboard 投影の非同期再構築を依頼する境界です."""

    async def wake_user_rebuild(self, *, user_id: int, reason: str) -> None:
        """指定 user が所有する leaderboard 投影の再構築を依頼します.

        Args:
            user_id: 再構築対象 user の ID です.
            reason: 起動理由を表す運用向け文字列です.

        Returns:
            None です.

        Raises:
            実装が worker 起動に失敗した場合は、その実装の例外を送出します.
        """
        ...

    async def wake_beatmapset_rebuild(self, *, beatmapset_id: int, reason: str) -> None:
        """指定 beatmapset の leaderboard 投影の再構築を依頼します.

        Args:
            beatmapset_id: 再構築対象 beatmapset の ID です.
            reason: 起動理由を表す運用向け文字列です.

        Returns:
            None です.

        Raises:
            実装が worker 起動に失敗した場合は、その実装の例外を送出します.
        """
        ...


@final
class NoopBeatmapLeaderboardRebuildWorkerWake:
    """worker 起動が未配線の環境で使用する何もしない実装です."""

    async def wake_user_rebuild(self, *, user_id: int, reason: str) -> None:
        """指定 user の再構築依頼を受け取り、何も実行しません.

        Args:
            user_id: 再構築対象 user の ID です.
            reason: 起動理由を表す運用向け文字列です.

        Returns:
            None です.

        Raises:
            送出しません.
        """
        _ = (user_id, reason)

    async def wake_beatmapset_rebuild(self, *, beatmapset_id: int, reason: str) -> None:
        """指定 beatmapset の再構築依頼を受け取り、何も実行しません.

        Args:
            beatmapset_id: 再構築対象 beatmapset の ID です.
            reason: 起動理由を表す運用向け文字列です.

        Returns:
            None です.

        Raises:
            送出しません.
        """
        _ = (beatmapset_id, reason)


__all__ = [
    "BeatmapLeaderboardRebuildWorkerWake",
    "NoopBeatmapLeaderboardRebuildWorkerWake",
]
