"""Stable friend relationship packet handlers."""

from __future__ import annotations

from typing import TYPE_CHECKING

import structlog

from osu_server.services.commands.identity import (
    AddFriendCommand,
    RemoveFriendCommand,
    UpdateFriendOnlyDmCommand,
)
from osu_server.transports.stable.bancho.handlers.base import HandlerGroup, handles
from osu_server.transports.stable.bancho.protocol.c2s.friends import (
    parse_friend_only_dms_payload,
    parse_friend_user_id_payload,
)
from osu_server.transports.stable.bancho.protocol.enums import ClientPacketID
from osu_server.transports.stable.bancho.protocol.errors import PacketReadError

if TYPE_CHECKING:
    from osu_server.services.commands.identity import (
        AddFriendCommandUseCase,
        RemoveFriendCommandUseCase,
        UpdateFriendOnlyDmCommandUseCase,
    )

logger: structlog.stdlib.BoundLogger = structlog.get_logger(__name__)  # pyright: ignore[reportAny]


class FriendHandlers(HandlerGroup):
    """C2S friend add/remove and friend-only DM handlers."""

    def __init__(
        self,
        *,
        add_friend: AddFriendCommandUseCase,
        remove_friend: RemoveFriendCommandUseCase,
        update_friend_only_dm: UpdateFriendOnlyDmCommandUseCase,
    ) -> None:
        self._add_friend: AddFriendCommandUseCase = add_friend
        self._remove_friend: RemoveFriendCommandUseCase = remove_friend
        self._update_friend_only_dm: UpdateFriendOnlyDmCommandUseCase = update_friend_only_dm

    @handles(ClientPacketID.ADD_FRIEND)
    async def handle_add_friend(self, payload: bytes, user_id: int) -> None:
        """ADD_FRIEND (73) — add one directed friend relationship."""
        target_user_id = _parse_friend_user_id(payload, "ADD_FRIEND")
        if target_user_id is None:
            return
        _ = await self._add_friend.execute(
            AddFriendCommand(owner_user_id=user_id, target_user_id=target_user_id)
        )

    @handles(ClientPacketID.REMOVE_FRIEND)
    async def handle_remove_friend(self, payload: bytes, user_id: int) -> None:
        """REMOVE_FRIEND (74) — remove one directed friend relationship."""
        target_user_id = _parse_friend_user_id(payload, "REMOVE_FRIEND")
        if target_user_id is None:
            return
        _ = await self._remove_friend.execute(
            RemoveFriendCommand(owner_user_id=user_id, target_user_id=target_user_id)
        )

    @handles(ClientPacketID.CHANGE_FRIENDONLY_DMS)
    async def handle_change_friendonly_dms(self, payload: bytes, user_id: int) -> None:
        """CHANGE_FRIENDONLY_DMS (99) — update active session PM privacy."""
        enabled = _parse_friend_only_dms(payload)
        if enabled is None:
            return
        _ = await self._update_friend_only_dm.execute(
            UpdateFriendOnlyDmCommand(user_id=user_id, enabled=enabled)
        )


def _parse_friend_user_id(payload: bytes, packet_name: str) -> int | None:
    try:
        return parse_friend_user_id_payload(payload, packet_name=packet_name)
    except PacketReadError as exc:
        logger.warning(
            "c2s_malformed_payload",
            packet=packet_name,
            payload_size=len(payload),
            reason=str(exc),
        )
        return None


def _parse_friend_only_dms(payload: bytes) -> bool | None:
    try:
        return parse_friend_only_dms_payload(payload)
    except PacketReadError as exc:
        logger.warning(
            "c2s_malformed_payload",
            packet="CHANGE_FRIENDONLY_DMS",
            payload_size=len(payload),
            reason=str(exc),
        )
        return None
