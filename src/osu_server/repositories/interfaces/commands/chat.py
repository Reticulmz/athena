"""Accepted chat history persistence の command-side repository 契約."""

from __future__ import annotations

from typing import TYPE_CHECKING, Protocol, runtime_checkable

if TYPE_CHECKING:
    from osu_server.domain.chat import ChatPersistenceResult


@runtime_checkable
class ChatCommandRepository(Protocol):
    """Accepted chat history persistence の mutation port.

    Notes:
        Runtime 実装は command Unit of Work から取得する.各操作は同じ Unit of Work が
        所有する transaction に参加し,この repository 自身は commit または rollback を
        実行しない.
    """

    async def save_channel_message(
        self,
        *,
        sender_id: int,
        channel_name: str,
        content: str,
    ) -> ChatPersistenceResult:
        """受理済み public channel chat history を永続化する.

        Args:
            sender_id (int): 送信者 User ID.
            channel_name (str): 送信先 Channel name.
            content (str): 永続化する message content.

        Returns:
            ChatPersistenceResult: 永続化結果と message identity を表す結果.
        """
        ...

    async def save_private_message(
        self,
        *,
        sender_id: int,
        target_id: int,
        content: str,
    ) -> ChatPersistenceResult:
        """受理済み private chat history を永続化する.

        Args:
            sender_id (int): 送信者 User ID.
            target_id (int): 宛先 User ID.
            content (str): 永続化する message content.

        Returns:
            ChatPersistenceResult: 永続化結果と message identity を表す結果.
        """
        ...


__all__ = ["ChatCommandRepository"]
