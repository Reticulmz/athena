from __future__ import annotations

from typing import TYPE_CHECKING

from osu_server.services.commands.chat import (
    PersistChannelMessageCommand,
    PersistPrivateMessageCommand,
    SendChannelMessageCommand,
    SendPrivateMessageCommand,
)

if TYPE_CHECKING:
    from osu_server.domain.chat import (
        ChannelMessageResult,
        ChatPersistenceResult,
        PrivateMessageResult,
        SendChannelMessageInput,
        SendPrivateMessageInput,
    )
    from osu_server.services.commands.chat import (
        PersistChannelMessageUseCase,
        PersistPrivateMessageUseCase,
        SendChannelMessageUseCase,
        SendPrivateMessageUseCase,
    )


class ChatService:
    """
    DEPRECATED: Facade for chat use-cases. Use command/query use-cases directly.

    This service will be removed after all call sites migrate to use-cases.
    """

    def __init__(
        self,
        *,
        send_channel_message_use_case: SendChannelMessageUseCase,
        send_private_message_use_case: SendPrivateMessageUseCase,
        persist_channel_message_use_case: PersistChannelMessageUseCase,
        persist_private_message_use_case: PersistPrivateMessageUseCase,
    ) -> None:
        self._send_channel_msg: SendChannelMessageUseCase = send_channel_message_use_case
        self._send_private_msg: SendPrivateMessageUseCase = send_private_message_use_case
        self._persist_channel_msg: PersistChannelMessageUseCase = persist_channel_message_use_case
        self._persist_private_msg: PersistPrivateMessageUseCase = persist_private_message_use_case

    async def send_channel_message(
        self,
        message: SendChannelMessageInput,
    ) -> ChannelMessageResult | None:
        """Send a channel message. Delegates to SendChannelMessageUseCase."""
        result = await self._send_channel_msg.execute(SendChannelMessageCommand(message=message))
        return result.result

    async def send_private_message(
        self,
        message: SendPrivateMessageInput,
    ) -> PrivateMessageResult | None:
        """Send a private message. Delegates to SendPrivateMessageUseCase."""
        result = await self._send_private_msg.execute(SendPrivateMessageCommand(message=message))
        return result.result

    async def persist_channel_message(
        self,
        *,
        sender_id: int,
        channel_name: str,
        content: str,
    ) -> ChatPersistenceResult:
        """Persist a channel message. Delegates to PersistChannelMessageUseCase."""
        return await self._persist_channel_msg.execute(
            PersistChannelMessageCommand(
                sender_id=sender_id,
                channel_name=channel_name,
                content=content,
            )
        )

    async def persist_private_message(
        self,
        *,
        sender_id: int,
        target_id: int,
        content: str,
    ) -> ChatPersistenceResult:
        """Persist a private message. Delegates to PersistPrivateMessageUseCase."""
        return await self._persist_private_msg.execute(
            PersistPrivateMessageCommand(
                sender_id=sender_id,
                target_id=target_id,
                content=content,
            )
        )
