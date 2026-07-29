"""Beatmap leaderboard 再構築 worker を起動する port を定義する."""

from __future__ import annotations

from typing import Protocol, final


class BeatmapLeaderboardRebuildWorkerWake(Protocol):
    """leaderboard 投影の非同期再構築を依頼する境界を表す.

    Notes:
        実装は task queue などの runtime adapter に委譲し 投影の更新自体は行わない.
    """

    async def wake_user_rebuild(self, *, user_id: int, reason: str) -> None:
        """指定 user が所有する leaderboard 投影の再構築を依頼する.

        Args:
            user_id (int): 再構築対象 user の ID.
            reason (str): 起動理由を表す運用向け文字列.

        Returns:
            None: 起動依頼だけを行い 再構築結果は返さない.
        """
        ...

    async def wake_beatmapset_rebuild(self, *, beatmapset_id: int, reason: str) -> None:
        """指定 beatmapset の leaderboard 投影の再構築を依頼する.

        Args:
            beatmapset_id (int): 再構築対象 beatmapset の ID.
            reason (str): 起動理由を表す運用向け文字列.

        Returns:
            None: 起動依頼だけを行い 再構築結果は返さない.
        """
        ...


@final
class NoopBeatmapLeaderboardRebuildWorkerWake:
    """worker 起動が未配線の環境で使用する何もしない実装です.

    Notes:
        引数は受け取るが task を enqueue せず 副作用を発生させない.
    """

    async def wake_user_rebuild(self, *, user_id: int, reason: str) -> None:
        """指定 user の再構築依頼を受け取り何も実行しない.

        Args:
            user_id (int): 再構築対象 user の ID.
            reason (str): 起動理由を表す運用向け文字列.

        Returns:
            None: 依頼を破棄して完了する.
        """
        _ = (user_id, reason)

    async def wake_beatmapset_rebuild(self, *, beatmapset_id: int, reason: str) -> None:
        """指定 beatmapset の再構築依頼を受け取り何も実行しない.

        Args:
            beatmapset_id (int): 再構築対象 beatmapset の ID.
            reason (str): 起動理由を表す運用向け文字列.

        Returns:
            None: 依頼を破棄して完了する.
        """
        _ = (beatmapset_id, reason)


__all__ = [
    "BeatmapLeaderboardRebuildWorkerWake",
    "NoopBeatmapLeaderboardRebuildWorkerWake",
]
