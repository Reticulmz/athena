"""Performance completion signal の in-memory 実装を提供する module."""

from __future__ import annotations

import asyncio
from collections import defaultdict
from typing import TYPE_CHECKING

from osu_server.infrastructure.state.interfaces.performance_completion_signal import (
    PerformanceCompletionSignalPayload,
    validate_performance_completion_timeout,
)

if TYPE_CHECKING:
    from datetime import timedelta


class InMemoryPerformanceCompletionSignal:
    """Score 単位の best-effort completion signal を memory で配信する実装.

    Attributes:
        _conditions (defaultdict[int, asyncio.Condition]): score id ごとの現在の待機者を通知する
            condition.

    Notes:
        signal を保存しないため,notify より後に開始した wait は過去の通知を観測しない.
        thread-safe ではなく,同一 asyncio event loop の test と in-memory runtime 向けである.
    """

    def __init__(self) -> None:
        """Score ごとの空の condition registry を初期化する."""
        self._conditions: defaultdict[int, asyncio.Condition] = defaultdict(asyncio.Condition)

    async def notify(self, payload: PerformanceCompletionSignalPayload) -> None:
        """Payload の score を待機中の task だけに wake-up を通知する.

        Args:
            payload (PerformanceCompletionSignalPayload): 通知対象 score を識別する終端 payload.

        Returns:
            None: 現在の待機者への通知処理が完了したことを表す.

        Notes:
            payload は保存せず,通知時に待機していない task には届かない.
        """
        condition = self._conditions[payload.score_id]
        async with condition:
            condition.notify_all()

    async def wait(self, score_id: int, timeout: timedelta) -> bool:
        """Score の通知を期限まで待ち,観測結果を返す.

        Args:
            score_id (int): 待機対象となる正の score id.
            timeout (timedelta): 正である最大待機時間.

        Returns:
            bool: 通知を観測した場合は True,期限切れなら False.

        Raises:
            ValueError: score_id が正でない場合,または timeout が正でない場合.
        """
        validate_performance_completion_timeout(timeout)
        if score_id <= 0:
            msg = "score_id must be positive"
            raise ValueError(msg)

        condition = self._conditions[score_id]
        try:
            async with condition:
                _ = await asyncio.wait_for(condition.wait(), timeout=timeout.total_seconds())
        except TimeoutError:
            return False
        return True
