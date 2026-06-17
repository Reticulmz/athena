"""STATUS_CHANGE handler for stable beatmap file warmup."""

from __future__ import annotations

import re
from typing import TYPE_CHECKING, Protocol, cast

import structlog

from osu_server.services.commands.beatmaps import (
    BeatmapFileWarmupEntrance,
    BeatmapFileWarmupRequest,
    BeatmapFileWarmupResult,
)
from osu_server.transports.stable.bancho.handlers.base import HandlerGroup, handles
from osu_server.transports.stable.bancho.protocol.c2s import parse_status_change_payload
from osu_server.transports.stable.bancho.protocol.enums import ClientPacketID
from osu_server.transports.stable.bancho.protocol.errors import PacketReadError

if TYPE_CHECKING:
    from osu_server.transports.stable.bancho.protocol.types import StatusUpdate

logger = cast("structlog.stdlib.BoundLogger", structlog.get_logger(__name__))
_CHECKSUM_MD5_RE = re.compile(r"^[0-9A-Fa-f]{32}$")


class _BeatmapFileWarmupUseCase(Protocol):
    async def execute(
        self,
        request: BeatmapFileWarmupRequest,
    ) -> BeatmapFileWarmupResult: ...


class StatusChangeHandlers(HandlerGroup):
    """Handle STATUS_CHANGE warmup without owning presence state."""

    _beatmap_file_warmup: _BeatmapFileWarmupUseCase

    def __init__(self, *, beatmap_file_warmup: _BeatmapFileWarmupUseCase) -> None:
        self._beatmap_file_warmup = beatmap_file_warmup

    @handles(ClientPacketID.STATUS_CHANGE)
    async def handle_status_change(self, payload: bytes, user_id: int) -> None:
        """Decode STATUS_CHANGE and request beatmap file warmup when possible."""
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


__all__ = ["StatusChangeHandlers"]
