"""In-memory performance completion signal."""

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
    """Score-scoped best-effort signal for tests and in-memory runtimes."""

    def __init__(self) -> None:
        self._conditions: defaultdict[int, asyncio.Condition] = defaultdict(asyncio.Condition)

    async def notify(self, payload: PerformanceCompletionSignalPayload) -> None:
        """Wake current waiters for the payload score without storing the signal."""
        condition = self._conditions[payload.score_id]
        async with condition:
            condition.notify_all()

    async def wait(self, score_id: int, timeout: timedelta) -> bool:
        """Wait for a score signal and return False on timeout."""
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
