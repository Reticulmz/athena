"""Persisted chat history 用 read-only query repository contract を定義する."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Protocol

if TYPE_CHECKING:
    from datetime import datetime


@dataclass(frozen=True, slots=True)
class ChatHistoryMessage:
    """Persisted chat history の read model を表す.

    Attributes:
        id (int): Message の識別子.
        sender_id (int): Message sender の User ID.
        content (str): 保存済み message content.
        created_at (datetime): Message の作成日時.
    """

    id: int
    sender_id: int
    content: str
    created_at: datetime


class ChatHistoryQueryRepository(Protocol):
    """Persisted chat history への read-only access を定義する.

    Notes:
        この Protocol は history read model を返すだけで message を作成または変更しない.
        Command Unit of Work を開始せず transaction の commit/rollback も所有しない.
    """

    async def list_channel_messages(
        self,
        channel_name: str,
        *,
        limit: int,
        before_message_id: int | None = None,
    ) -> list[ChatHistoryMessage]:
        """Channel history を新しい順に返す.

        Args:
            channel_name (str): History を取得する channel name.
            limit (int): 返却する最大 message 数.
            before_message_id (int | None): 先行 page を指定する message ID. 初回取得時は `None`.

        Returns:
            list[ChatHistoryMessage]: 新しい順の channel history. 対象がない場合は空の list.
        """
        ...

    async def list_private_messages(
        self,
        user_id: int,
        peer_user_id: int,
        *,
        limit: int,
        before_message_id: int | None = None,
    ) -> list[ChatHistoryMessage]:
        """二人の User 間の private message history を新しい順に返す.

        Args:
            user_id (int): History の一方を表す User ID.
            peer_user_id (int): History の相手を表す User ID.
            limit (int): 返却する最大 message 数.
            before_message_id (int | None): 先行 page を指定する message ID. 初回取得時は `None`.

        Returns:
            list[ChatHistoryMessage]: 新しい順の private message history.
            対象がない場合は空の list.
        """
        ...
