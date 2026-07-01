"""STATUS_CHANGE handler for stable beatmap file warmup."""

from __future__ import annotations

import re
from typing import TYPE_CHECKING, Protocol, cast

import structlog

from osu_server.domain.compatibility.stable import (
    DEFAULT_STABLE_USER_STATUS,
    StableUserStatus,
)
from osu_server.domain.compatibility.stable.mode import StableMode
from osu_server.domain.scores import Playstyle, Ruleset
from osu_server.services.commands.beatmaps import (
    BeatmapFileWarmupEntrance,
    BeatmapFileWarmupRequest,
    BeatmapFileWarmupResult,
)
from osu_server.services.queries.identity import ListActiveSessionsQueryInput
from osu_server.services.queries.scores import CurrentUserStatsQueryInput
from osu_server.transports.stable.bancho.handlers.base import HandlerGroup, handles
from osu_server.transports.stable.bancho.mappers.user_stats import stable_user_stats_packet
from osu_server.transports.stable.bancho.protocol.c2s import parse_status_change_payload
from osu_server.transports.stable.bancho.protocol.enums import ClientPacketID
from osu_server.transports.stable.bancho.protocol.errors import PacketReadError

if TYPE_CHECKING:
    from osu_server.infrastructure.state.interfaces.packet_queue import PacketQueue
    from osu_server.infrastructure.state.interfaces.stable_user_status_store import (
        StableUserStatusStore,
    )
    from osu_server.services.queries.identity import ListActiveSessionsQuery
    from osu_server.services.queries.scores import CurrentUserStatsQuery
    from osu_server.transports.stable.bancho.protocol.types import StatusUpdate

logger = cast("structlog.stdlib.BoundLogger", structlog.get_logger(__name__))
_CHECKSUM_MD5_RE = re.compile(r"^[0-9A-Fa-f]{32}$")


class _BeatmapFileWarmupUseCase(Protocol):
    async def execute(
        self,
        request: BeatmapFileWarmupRequest,
    ) -> BeatmapFileWarmupResult: ...


class StatusChangeHandlers(HandlerGroup):
    """STATUS_CHANGE の beatmap file warmup と current stats 更新を扱う。"""

    _beatmap_file_warmup: _BeatmapFileWarmupUseCase
    _stable_user_status_store: StableUserStatusStore | None
    _current_user_stats_query: CurrentUserStatsQuery | None
    _packet_queue: PacketQueue | None
    _active_sessions_query: ListActiveSessionsQuery | None

    def __init__(
        self,
        *,
        beatmap_file_warmup: _BeatmapFileWarmupUseCase,
        stable_user_status_store: StableUserStatusStore | None = None,
        current_user_stats_query: CurrentUserStatsQuery | None = None,
        packet_queue: PacketQueue | None = None,
        active_sessions_query: ListActiveSessionsQuery | None = None,
    ) -> None:
        self._beatmap_file_warmup = beatmap_file_warmup
        self._stable_user_status_store = stable_user_status_store
        self._current_user_stats_query = current_user_stats_query
        self._packet_queue = packet_queue
        self._active_sessions_query = active_sessions_query

    @handles(ClientPacketID.STATUS_CHANGE)
    async def handle_status_change(self, payload: bytes, user_id: int) -> None:
        """STATUS_CHANGE payload を解釈し、必要な副作用をキューへ反映する。"""
        try:
            status_update = parse_status_change_payload(payload)
        except PacketReadError as exc:
            logger.info(
                "status_change_warmup_decode_failed",
                user_id=user_id,
                payload_size=len(payload),
                reason=str(exc),
            )
            return

        play_mode = _stable_play_mode(status_update.play_mode)
        if play_mode is not None:
            stable_status = _stable_user_status_from_update(
                status_update,
                play_mode=play_mode,
            )
            await self._store_status(stable_status, user_id=user_id)
            await self._broadcast_current_user_stats(
                stable_status,
                play_mode=play_mode,
                user_id=user_id,
            )
        request = _warmup_request_from_status_update(status_update, user_id=user_id)
        try:
            _ = await self._beatmap_file_warmup.execute(request)
        except Exception as exc:
            logger.info(
                "status_change_warmup_failed",
                user_id=user_id,
                beatmap_id=request.beatmap_id,
                checksum_md5=request.checksum_md5,
                exception_type=type(exc).__name__,
            )

    @handles(ClientPacketID.REQUEST_STATUS)
    async def handle_request_status(self, payload: bytes, user_id: int) -> None:
        """REQUEST_STATUS payload を処理し、自分自身の current stats を返す。"""
        _ = payload
        status = await self._current_status(user_id=user_id)
        play_mode = _stable_play_mode(status.play_mode)
        if play_mode is None:
            play_mode = StableMode.Osu.value
            status = status.with_play_mode(play_mode)
        await self._enqueue_current_user_stats(
            status,
            play_mode=play_mode,
            user_id=user_id,
            recipient_user_ids=(user_id,),
            error_event="request_status_user_stats_enqueue_failed",
        )

    async def _store_status(self, status: StableUserStatus, *, user_id: int) -> None:
        if self._stable_user_status_store is None:
            return
        try:
            await self._stable_user_status_store.set_status(user_id, status)
        except Exception as exc:
            logger.info(
                "status_change_status_store_failed",
                user_id=user_id,
                play_mode=status.play_mode,
                exception_type=type(exc).__name__,
            )

    async def _broadcast_current_user_stats(
        self,
        status: StableUserStatus,
        *,
        play_mode: int,
        user_id: int,
    ) -> None:
        if self._current_user_stats_query is None or self._packet_queue is None:
            return
        recipient_user_ids = (user_id,)
        if self._active_sessions_query is not None:
            try:
                active_sessions = await self._active_sessions_query.execute(
                    ListActiveSessionsQueryInput()
                )
                recipient_user_ids = tuple(
                    dict.fromkeys(
                        (
                            user_id,
                            *(session.user_id for session in active_sessions.sessions),
                        )
                    )
                )
            except Exception:
                logger.exception(
                    "status_change_active_sessions_read_failed",
                    user_id=user_id,
                    play_mode=play_mode,
                )
        await self._enqueue_current_user_stats(
            status,
            play_mode=play_mode,
            user_id=user_id,
            recipient_user_ids=recipient_user_ids,
            error_event="status_change_user_stats_enqueue_failed",
        )

    async def _enqueue_current_user_stats(
        self,
        status: StableUserStatus,
        *,
        play_mode: int,
        user_id: int,
        recipient_user_ids: tuple[int, ...],
        error_event: str,
    ) -> None:
        if self._current_user_stats_query is None or self._packet_queue is None:
            return
        try:
            result = await self._current_user_stats_query.execute(
                CurrentUserStatsQueryInput(
                    user_ids=(user_id,),
                    ruleset=_ruleset_for_play_mode(play_mode),
                    playstyle=Playstyle.VANILLA,
                )
            )
            packet = stable_user_stats_packet(
                user_id=user_id,
                current_stats=result.get(user_id),
                play_mode=play_mode,
                status=status,
            )
            for recipient_user_id in recipient_user_ids:
                await self._packet_queue.enqueue(recipient_user_id, packet)
        except Exception:
            logger.exception(
                error_event,
                user_id=user_id,
                play_mode=play_mode,
            )

    async def _current_status(self, *, user_id: int) -> StableUserStatus:
        if self._stable_user_status_store is None:
            return DEFAULT_STABLE_USER_STATUS
        try:
            statuses = await self._stable_user_status_store.get_statuses((user_id,))
        except Exception:
            logger.exception(
                "request_status_status_read_failed",
                user_id=user_id,
            )
            return DEFAULT_STABLE_USER_STATUS
        return statuses.get(user_id, DEFAULT_STABLE_USER_STATUS)


def _warmup_request_from_status_update(
    status_update: StatusUpdate,
    *,
    user_id: int,
) -> BeatmapFileWarmupRequest:
    beatmap_id = status_update.beatmap_id
    if beatmap_id > 0:
        return BeatmapFileWarmupRequest(
            entrance=BeatmapFileWarmupEntrance.STABLE_STATUS_CHANGE,
            user_id=user_id,
            beatmap_id=beatmap_id,
        )

    checksum_md5 = status_update.beatmap_md5
    usable_checksum_md5 = (
        checksum_md5 if _CHECKSUM_MD5_RE.fullmatch(checksum_md5) is not None else None
    )
    return BeatmapFileWarmupRequest(
        entrance=BeatmapFileWarmupEntrance.STABLE_STATUS_CHANGE,
        user_id=user_id,
        checksum_md5=usable_checksum_md5,
    )


def _stable_play_mode(play_mode: int) -> int | None:
    try:
        return StableMode(play_mode).value
    except ValueError:
        return None


def _stable_user_status_from_update(
    status_update: StatusUpdate,
    *,
    play_mode: int,
) -> StableUserStatus:
    return StableUserStatus(
        status=status_update.status,
        status_text=status_update.status_text,
        beatmap_md5=status_update.beatmap_md5,
        mods=status_update.mods,
        play_mode=play_mode,
        beatmap_id=status_update.beatmap_id,
    )


def _ruleset_for_play_mode(play_mode: int) -> Ruleset:
    try:
        return Ruleset(play_mode)
    except ValueError:
        return Ruleset.OSU


__all__ = ["StatusChangeHandlers"]
