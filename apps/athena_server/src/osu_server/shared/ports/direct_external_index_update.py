"""osu!direct external index update worker wake portを定義する."""

from __future__ import annotations

from typing import Protocol, final


class DirectExternalIndexUpdateWorkerWake(Protocol):
    """external index update jobの起動境界を表す.

    Notes:
        実装は task queue などの runtime adapter に委譲し index update 自体は行わない.
    """

    async def wake_external_index_update(self, *, beatmapset_id: int, reason: str) -> None:
        """指定 beatmapset の external index update を依頼する.

        Args:
            beatmapset_id (int): 更新対象 beatmapset の ID.
            reason (str): 起動理由を表す運用向け文字列.

        Returns:
            None: 起動依頼だけを行い update 結果は返さない.
        """
        ...


@final
class NoopDirectExternalIndexUpdateWorkerWake:
    """worker 起動が未配線の環境で使用する何もしない実装です.

    Notes:
        引数は受け取るが task を enqueue せず 副作用を発生させない.
    """

    async def wake_external_index_update(self, *, beatmapset_id: int, reason: str) -> None:
        """指定 beatmapset の update 依頼を受け取り何もしない.

        Args:
            beatmapset_id (int): 更新対象 beatmapset の ID.
            reason (str): 起動理由を表す運用向け文字列.

        Returns:
            None: 依頼を破棄して完了する.
        """
        _ = (beatmapset_id, reason)


__all__ = [
    "DirectExternalIndexUpdateWorkerWake",
    "NoopDirectExternalIndexUpdateWorkerWake",
]
