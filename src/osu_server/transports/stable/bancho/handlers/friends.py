"""stable Banchoのfriend relationship C2S packetをcommandへ適応する."""

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
    """friend relationshipとfriend-only DM設定のC2S handlerを提供する.

    Attributes:
        _add_friend (AddFriendCommandUseCase): friend追加commandを実行するuse case.
        _remove_friend (RemoveFriendCommandUseCase): friend削除commandを実行するuse case.
        _update_friend_only_dm (UpdateFriendOnlyDmCommandUseCase): DM公開設定を更新するuse case.
    """

    def __init__(
        self,
        *,
        add_friend: AddFriendCommandUseCase,
        remove_friend: RemoveFriendCommandUseCase,
        update_friend_only_dm: UpdateFriendOnlyDmCommandUseCase,
    ) -> None:
        """friend関連command use caseを初期化する.

        Args:
            add_friend (AddFriendCommandUseCase): friend追加用のuse case.
            remove_friend (RemoveFriendCommandUseCase): friend削除用のuse case.
            update_friend_only_dm (UpdateFriendOnlyDmCommandUseCase): DM公開設定更新用のuse case.
        """
        self._add_friend: AddFriendCommandUseCase = add_friend
        self._remove_friend: RemoveFriendCommandUseCase = remove_friend
        self._update_friend_only_dm: UpdateFriendOnlyDmCommandUseCase = update_friend_only_dm

    @handles(ClientPacketID.ADD_FRIEND)
    async def handle_add_friend(self, payload: bytes, user_id: int) -> None:
        """ADD_FRIEND payloadから片方向friend relationshipを追加する.

        Args:
            payload (bytes): target user IDを含むC2S packet payload.
            user_id (int): relationshipを所有する認証済みuserのID.

        Returns:
            None: 不正payloadをdropするか,追加commandを実行して値を返さずに完了する.
        """
        target_user_id = _parse_friend_user_id(payload, "ADD_FRIEND")
        if target_user_id is None:
            return
        _ = await self._add_friend.execute(
            AddFriendCommand(owner_user_id=user_id, target_user_id=target_user_id)
        )

    @handles(ClientPacketID.REMOVE_FRIEND)
    async def handle_remove_friend(self, payload: bytes, user_id: int) -> None:
        """REMOVE_FRIEND payloadから片方向friend relationshipを削除する.

        Args:
            payload (bytes): target user IDを含むC2S packet payload.
            user_id (int): relationshipを所有する認証済みuserのID.

        Returns:
            None: 不正payloadをdropするか,削除commandを実行して値を返さずに完了する.
        """
        target_user_id = _parse_friend_user_id(payload, "REMOVE_FRIEND")
        if target_user_id is None:
            return
        _ = await self._remove_friend.execute(
            RemoveFriendCommand(owner_user_id=user_id, target_user_id=target_user_id)
        )

    @handles(ClientPacketID.CHANGE_FRIENDONLY_DMS)
    async def handle_change_friendonly_dms(self, payload: bytes, user_id: int) -> None:
        """CHANGE_FRIENDONLY_DMS payloadでDM公開設定を更新する.

        Args:
            payload (bytes): friend-only DMの有効状態を含むC2S packet payload.
            user_id (int): 更新対象となる認証済みuserのID.

        Returns:
            None: 不正payloadをdropするか,更新commandを実行して値を返さずに完了する.
        """
        enabled = _parse_friend_only_dms(payload)
        if enabled is None:
            return
        _ = await self._update_friend_only_dm.execute(
            UpdateFriendOnlyDmCommand(user_id=user_id, enabled=enabled)
        )


def _parse_friend_user_id(payload: bytes, packet_name: str) -> int | None:
    """friend対象user IDのpayloadを安全にparseする.

    Args:
        payload (bytes): int32のuser IDを含むpacket payload.
        packet_name (str): warning logへ記録するC2S packet名.

    Returns:
        int | None: parseしたtarget user ID. payloadが不正な場合はNone.
    """
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
    """friend-only DM設定のpayloadを安全にparseする.

    Args:
        payload (bytes): boolean設定値を含むCHANGE_FRIENDONLY_DMS payload.

    Returns:
        bool | None: parseした有効状態. payloadが不正な場合はNone.
    """
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
