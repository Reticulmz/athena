"""Current UserStats event listeners for stable Bancho packet fanout."""

from __future__ import annotations

from typing import TYPE_CHECKING, cast

import structlog

from osu_server.domain.compatibility.stable import (
    DEFAULT_STABLE_USER_STATUS,
    StableUserStatus,
)
from osu_server.domain.events.scores import CurrentUserStatsUpdated
from osu_server.services.queries.scores import CurrentUserStatsQueryInput
from osu_server.transports.stable.bancho.listeners.base import ListenerGroup, listens
from osu_server.transports.stable.bancho.mappers.user_stats import stable_user_stats_packet

if TYPE_CHECKING:
    from osu_server.domain.scores.user_stats import UserCurrentStats
    from osu_server.infrastructure.state.interfaces.packet_queue import PacketQueue
    from osu_server.infrastructure.state.interfaces.stable_user_status_store import (
        StableUserStatusStore,
    )
    from osu_server.services.queries.scores import CurrentUserStatsQuery

logger = cast("structlog.stdlib.BoundLogger", structlog.get_logger(__name__))


class UserStatsListeners(ListenerGroup):
    """current UserStats 更新 event を Stable USER_STATS packet に変換する。"""

    _packet_queue: PacketQueue
    _current_user_stats_query: CurrentUserStatsQuery
    _stable_user_status_store: StableUserStatusStore | None

    def __init__(
        self,
        *,
        packet_queue: PacketQueue,
        current_user_stats_query: CurrentUserStatsQuery,
        stable_user_status_store: StableUserStatusStore | None = None,
    ) -> None:
        self._packet_queue = packet_queue
        self._current_user_stats_query = current_user_stats_query
        self._stable_user_status_store = stable_user_status_store

    @listens(CurrentUserStatsUpdated)
    async def on_current_user_stats_updated(self, event: CurrentUserStatsUpdated) -> None:
        """score submit 後の current stats を submit user の packet queue へ積む。"""
        play_mode = event.ruleset.value
        should_notify, current_stats = await self._current_stats_for_event(event)
        if not should_notify:
            return
        status = (await self._current_status(event.user_id)).with_play_mode(play_mode)
        await self._packet_queue.enqueue(
            event.user_id,
            stable_user_stats_packet(
                user_id=event.user_id,
                current_stats=current_stats,
                play_mode=play_mode,
                status=status,
            ),
        )

    async def _current_stats_for_event(
        self,
        event: CurrentUserStatsUpdated,
    ) -> tuple[bool, UserCurrentStats | None]:
        if event.current_stats is not None:
            return True, event.current_stats
        try:
            result = await self._current_user_stats_query.execute(
                CurrentUserStatsQueryInput(
                    user_ids=(event.user_id,),
                    ruleset=event.ruleset,
                    playstyle=event.playstyle,
                )
            )
        except Exception:
            logger.exception(
                "current_user_stats_event_query_failed",
                user_id=event.user_id,
                ruleset=event.ruleset.value,
                playstyle=event.playstyle.value,
            )
            return False, None
        return True, result.get(event.user_id)

    async def _current_status(self, user_id: int) -> StableUserStatus:
        if self._stable_user_status_store is None:
            return DEFAULT_STABLE_USER_STATUS
        try:
            statuses = await self._stable_user_status_store.get_statuses((user_id,))
        except Exception:
            logger.exception(
                "current_user_stats_event_status_read_failed",
                user_id=user_id,
            )
            return DEFAULT_STABLE_USER_STATUS
        return statuses.get(user_id, DEFAULT_STABLE_USER_STATUS)


__all__ = ["UserStatsListeners"]
