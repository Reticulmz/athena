"""Stable stats request packet handlers."""

from __future__ import annotations

from collections import defaultdict
from typing import TYPE_CHECKING, cast

import structlog

from osu_server.domain.compatibility.stable.mode import StableMode
from osu_server.domain.identity.leaderboard_visibility import is_leaderboard_visible_user
from osu_server.domain.identity.system_users import BANCHO_BOT_IDENTITY
from osu_server.domain.scores import Playstyle, Ruleset
from osu_server.services.queries.identity import GetActiveSessionsByUserIdsQueryInput
from osu_server.services.queries.scores import CurrentUserStatsQueryInput
from osu_server.transports.stable.bancho.handlers.base import HandlerGroup, handles
from osu_server.transports.stable.bancho.mappers.user_stats import (
    bot_user_stats_packet,
    stable_user_stats_packet,
)
from osu_server.transports.stable.bancho.protocol.c2s import parse_stats_request_payload
from osu_server.transports.stable.bancho.protocol.enums import ClientPacketID
from osu_server.transports.stable.bancho.protocol.errors import PacketReadError

if TYPE_CHECKING:
    from collections.abc import Mapping

    from osu_server.domain.compatibility.stable import StableUserStatus
    from osu_server.domain.identity.system_users import SystemUserIdentity
    from osu_server.domain.scores.user_stats import UserCurrentStats
    from osu_server.infrastructure.state.interfaces.packet_queue import PacketQueue
    from osu_server.infrastructure.state.interfaces.stable_user_status_store import (
        StableUserStatusStore,
    )
    from osu_server.services.queries.identity import GetActiveSessionsByUserIdsQuery
    from osu_server.services.queries.scores import CurrentUserStatsQuery

logger = cast("structlog.stdlib.BoundLogger", structlog.get_logger(__name__))


class StatsRequestHandler(HandlerGroup):
    """C2S STATS_REQUEST handler."""

    _current_user_stats_query: CurrentUserStatsQuery
    _packet_queue: PacketQueue
    _stable_user_status_store: StableUserStatusStore | None
    _active_sessions_by_user_ids_query: GetActiveSessionsByUserIdsQuery | None
    _bot_identity: SystemUserIdentity

    def __init__(
        self,
        *,
        current_user_stats_query: CurrentUserStatsQuery,
        packet_queue: PacketQueue,
        stable_user_status_store: StableUserStatusStore | None = None,
        active_sessions_by_user_ids_query: GetActiveSessionsByUserIdsQuery | None = None,
        bot_identity: SystemUserIdentity | None = None,
    ) -> None:
        self._current_user_stats_query = current_user_stats_query
        self._packet_queue = packet_queue
        self._stable_user_status_store = stable_user_status_store
        self._active_sessions_by_user_ids_query = active_sessions_by_user_ids_query
        self._bot_identity = bot_identity or BANCHO_BOT_IDENTITY

    @handles(ClientPacketID.STATS_REQUEST)
    async def handle_stats_request(self, payload: bytes, user_id: int) -> None:
        """STATS_REQUEST (85) - requested users の current stats を返す。"""
        requested_user_ids = _parse_stats_request(payload)
        if requested_user_ids is None:
            return

        lookup_user_ids = tuple(
            dict.fromkeys(
                requested_user_id
                for requested_user_id in requested_user_ids
                if requested_user_id != user_id
            )
        )
        if len(lookup_user_ids) == 0:
            return

        visible_user_ids = await self._visible_online_user_ids(lookup_user_ids)
        if len(visible_user_ids) == 0:
            return

        stats_user_ids = tuple(
            visible_user_id
            for visible_user_id in visible_user_ids
            if visible_user_id != self._bot_identity.user_id
        )
        statuses_by_user_id = await self._statuses_by_user_id(stats_user_ids)
        play_modes_by_user_id = _play_modes_by_user_id(statuses_by_user_id)
        stats_by_user_id = await self._stats_by_user_id(
            stats_user_ids,
            play_modes_by_user_id=play_modes_by_user_id,
        )
        requester_play_mode = await self._requester_play_mode(user_id)

        packets: list[bytes] = []
        for requested_user_id in visible_user_ids:
            if requested_user_id == self._bot_identity.user_id:
                packets.append(
                    bot_user_stats_packet(
                        self._bot_identity,
                        play_mode=requester_play_mode,
                    )
                )
                continue
            stats = stats_by_user_id.get(requested_user_id)
            if stats is not None:
                packets.append(
                    stable_user_stats_packet(
                        user_id=requested_user_id,
                        current_stats=stats,
                        play_mode=_play_mode_for_user(
                            requested_user_id,
                            play_modes_by_user_id,
                        ),
                        status=statuses_by_user_id.get(requested_user_id),
                    )
                )
        packets_tuple = tuple(packets)
        if len(packets_tuple) == 0:
            return

        await self._packet_queue.enqueue(user_id, *packets_tuple)

    async def _visible_online_user_ids(self, user_ids: tuple[int, ...]) -> tuple[int, ...]:
        bot_user_id = self._bot_identity.user_id
        session_user_ids = tuple(user_id for user_id in user_ids if user_id != bot_user_id)
        if self._active_sessions_by_user_ids_query is None:
            return user_ids
        try:
            result = await self._active_sessions_by_user_ids_query.execute(
                GetActiveSessionsByUserIdsQueryInput(user_ids=session_user_ids)
            )
        except Exception:
            logger.exception(
                "stable_stats_request_active_sessions_read_failed",
                requested_user_ids=user_ids,
            )
            return ()

        visible_user_id_set = {
            session.user_id
            for session in result.sessions
            if is_leaderboard_visible_user(session.privileges)
        }
        return tuple(
            user_id
            for user_id in user_ids
            if user_id == bot_user_id or user_id in visible_user_id_set
        )

    async def _stats_by_user_id(
        self,
        user_ids: tuple[int, ...],
        *,
        play_modes_by_user_id: Mapping[int, int],
    ) -> dict[int, UserCurrentStats]:
        stats_by_user_id: dict[int, UserCurrentStats] = {}
        for play_mode, scoped_user_ids in _user_ids_by_play_mode(
            user_ids,
            play_modes_by_user_id,
        ).items():
            ruleset = _ruleset_for_play_mode(play_mode)
            try:
                result = await self._current_user_stats_query.execute(
                    CurrentUserStatsQueryInput(
                        user_ids=scoped_user_ids,
                        ruleset=ruleset,
                        playstyle=Playstyle.VANILLA,
                    )
                )
            except Exception:
                logger.exception(
                    "stable_stats_request_read_failed",
                    requested_user_ids=scoped_user_ids,
                    play_mode=play_mode,
                )
                continue
            stats_by_user_id.update(result.stats_by_user_id)
        return stats_by_user_id

    async def _statuses_by_user_id(
        self,
        user_ids: tuple[int, ...],
    ) -> dict[int, StableUserStatus]:
        if self._stable_user_status_store is None:
            return {}
        try:
            return await self._stable_user_status_store.get_statuses(user_ids)
        except Exception:
            logger.exception(
                "stable_stats_request_status_read_failed", requested_user_ids=user_ids
            )
            return {}

    async def _requester_play_mode(self, user_id: int) -> int:
        if self._stable_user_status_store is None:
            return StableMode.Osu.value
        try:
            play_mode = await self._stable_user_status_store.get_play_mode(user_id)
        except Exception:
            logger.exception(
                "stable_stats_requester_status_read_failed",
                user_id=user_id,
            )
            return StableMode.Osu.value
        return _stable_play_mode(play_mode)


def _parse_stats_request(payload: bytes) -> tuple[int, ...] | None:
    try:
        return parse_stats_request_payload(payload)
    except PacketReadError as exc:
        logger.warning(
            "c2s_malformed_payload",
            packet="STATS_REQUEST",
            payload_size=len(payload),
            reason=str(exc),
        )
        return None


def _user_ids_by_play_mode(
    user_ids: tuple[int, ...],
    play_modes_by_user_id: Mapping[int, int],
) -> dict[int, tuple[int, ...]]:
    grouped: dict[int, list[int]] = defaultdict(list)
    for user_id in user_ids:
        grouped[_play_mode_for_user(user_id, play_modes_by_user_id)].append(user_id)
    return {play_mode: tuple(scoped_user_ids) for play_mode, scoped_user_ids in grouped.items()}


def _play_modes_by_user_id(
    statuses_by_user_id: Mapping[int, StableUserStatus],
) -> dict[int, int]:
    return {user_id: status.play_mode for user_id, status in statuses_by_user_id.items()}


def _play_mode_for_user(
    user_id: int,
    play_modes_by_user_id: Mapping[int, int],
) -> int:
    play_mode = play_modes_by_user_id.get(user_id, StableMode.Osu.value)
    try:
        return StableMode(play_mode).value
    except ValueError:
        return StableMode.Osu.value


def _ruleset_for_play_mode(play_mode: int) -> Ruleset:
    try:
        return Ruleset(play_mode)
    except ValueError:
        return Ruleset.OSU


def _stable_play_mode(play_mode: int | None) -> int:
    if play_mode is None:
        return StableMode.Osu.value
    try:
        return StableMode(play_mode).value
    except ValueError:
        return StableMode.Osu.value


__all__ = ["StatsRequestHandler"]
