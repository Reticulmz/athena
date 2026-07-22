"""In-memory command 側 chat history repository を実装する module."""

from __future__ import annotations

from typing import TYPE_CHECKING

from osu_server.domain.chat import (
    ChatPersistenceFailureReason,
    ChatPersistenceResult,
)
from osu_server.repositories.memory.commands.state import (
    InMemoryChannelMessageRecord,
    InMemoryPrivateMessageRecord,
    now_utc,
)

if TYPE_CHECKING:
    from osu_server.repositories.memory.commands.state import InMemoryCommandRepositoryState


class InMemoryChatCommandRepository:
    """Channel message と private message の command-side 履歴を保存する.

    Attributes:
        _state (InMemoryCommandRepositoryState): 所有 Unit of Work の可変 state snapshot.

    Notes:
        この repository は lock 又は thread synchronization を提供しない. 同じ state を
        複数 task 又は thread から同時に変更してはならない.
    """

    def __init__(self, state: InMemoryCommandRepositoryState) -> None:
        """Active Unit of Work の state snapshot を保持する.

        Args:
            state (InMemoryCommandRepositoryState): repository が直接読み書きする state.

        Returns:
            None: state への参照を保持したことを示す.
        """
        self._state: InMemoryCommandRepositoryState = state

    async def save_channel_message(
        self,
        *,
        sender_id: int,
        channel_name: str,
        content: str,
    ) -> ChatPersistenceResult:
        """存在する public channel の message 履歴を保存する.

        Args:
            sender_id (int): message を送信した user の識別子.
            channel_name (str): 宛先 channel の完全一致 name.
            content (str): 保存する message 本文.

        Returns:
            ChatPersistenceResult:
                channel があれば success_result. なければ CHANNEL_NOT_FOUND failure.

        Notes:
            成功時だけ next_channel_message_id を増やし, message record を現在 UTC 時刻で保存する.
            failure 時は state を変更しない.
        """
        channel_id = self._state.channel_id_by_name.get(channel_name)
        if channel_id is None:
            return ChatPersistenceResult.failure(ChatPersistenceFailureReason.CHANNEL_NOT_FOUND)

        record_id = self._state.next_channel_message_id
        self._state.next_channel_message_id += 1
        self._state.channel_messages_by_id[record_id] = InMemoryChannelMessageRecord(
            id=record_id,
            sender_id=sender_id,
            channel_id=channel_id,
            channel_name=channel_name,
            content=content,
            created_at=now_utc(),
        )
        return ChatPersistenceResult.success_result()

    async def save_private_message(
        self,
        *,
        sender_id: int,
        target_id: int,
        content: str,
    ) -> ChatPersistenceResult:
        """Private message 履歴を保存する.

        Args:
            sender_id (int): message を送信した user の識別子.
            target_id (int): message の宛先 user の識別子.
            content (str): 保存する message 本文.

        Returns:
            ChatPersistenceResult: 常に success_result.

        Notes:
            target user の存在は検証しない. next_private_message_id を増やし, message record を
            現在 UTC 時刻で保存する.
        """
        record_id = self._state.next_private_message_id
        self._state.next_private_message_id += 1
        self._state.private_messages_by_id[record_id] = InMemoryPrivateMessageRecord(
            id=record_id,
            sender_id=sender_id,
            target_id=target_id,
            content=content,
            created_at=now_utc(),
        )
        return ChatPersistenceResult.success_result()
