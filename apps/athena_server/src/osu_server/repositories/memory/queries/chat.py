"""Committed in-memory state から chat history を読む query adapter を提供する."""

from __future__ import annotations

from typing import TYPE_CHECKING

from osu_server.repositories.interfaces.queries import ChatHistoryMessage

if TYPE_CHECKING:
    from osu_server.repositories.memory.commands.state import (
        InMemoryChannelMessageRecord,
        InMemoryPrivateMessageRecord,
    )
    from osu_server.repositories.memory.unit_of_work import InMemoryUnitOfWorkFactory


class InMemoryChatHistoryQueryRepository:
    """Committed in-memory state を読む read-only chat history repository.

    Attributes:
        _factory (InMemoryUnitOfWorkFactory): query ごとの committed snapshot を生成する factory.

    Notes:
        各 query は snapshot だけを読み, channel/private message state を変更しない.
    """

    def __init__(self, uow_factory: InMemoryUnitOfWorkFactory) -> None:
        """Committed snapshot を取得する factory を保持する.

        Args:
            uow_factory (InMemoryUnitOfWorkFactory): read に使用する committed state factory.
        """
        self._factory: InMemoryUnitOfWorkFactory = uow_factory

    async def list_channel_messages(
        self,
        channel_name: str,
        *,
        limit: int,
        before_message_id: int | None = None,
    ) -> list[ChatHistoryMessage]:
        """Channel の message history を新しい順で取得する.

        Args:
            channel_name (str): 検索する Channel name.
            limit (int): 返す最大 message 件数.
            before_message_id (int | None): この ID より小さい message だけを読む cursor.
                None の場合は cursor filter を適用しない.

        Returns:
            list[ChatHistoryMessage]: created_at, ID の降順で最大 limit 件の Channel message
                read model.

        Notes:
            limit が 0 以下の場合は空の list を返す. channel_name の正規化は行わない.
        """
        state = self._factory.snapshot()
        records = [
            record
            for record in state.channel_messages_by_id.values()
            if record.channel_name == channel_name
            and (before_message_id is None or record.id < before_message_id)
        ]
        return [_channel_message_to_read_model(record) for record in _latest_first(records, limit)]

    async def list_private_messages(
        self,
        user_id: int,
        peer_user_id: int,
        *,
        limit: int,
        before_message_id: int | None = None,
    ) -> list[ChatHistoryMessage]:
        """二つの User 間の private message history を新しい順で取得する.

        Args:
            user_id (int): 会話の一方の User ID.
            peer_user_id (int): 会話のもう一方の User ID.
            limit (int): 返す最大 message 件数.
            before_message_id (int | None): この ID より小さい message だけを読む cursor.
                None の場合は cursor filter を適用しない.

        Returns:
            list[ChatHistoryMessage]: 双方向の message を created_at, ID の降順で最大 limit 件に
                した read model.

        Notes:
            user_id と peer_user_id の順序は結果に影響しない. limit が 0 以下の場合は空の list を
            返す.
        """
        state = self._factory.snapshot()
        records = [
            record
            for record in state.private_messages_by_id.values()
            if _is_private_pair(record, user_id, peer_user_id)
            and (before_message_id is None or record.id < before_message_id)
        ]
        return [_private_message_to_read_model(record) for record in _latest_first(records, limit)]


def _latest_first[T: InMemoryChannelMessageRecord | InMemoryPrivateMessageRecord](
    records: list[T], limit: int
) -> list[T]:
    """Record を作成日時と ID の降順に並べて件数を制限する.

    Args:
        records (list[T]): 並べ替えと制限を行う message record 群.
        limit (int): 返す最大 record 件数.

    Returns:
        list[T]: created_at, ID の降順で最大 limit 件の新しい list. limit が 0 以下なら空の list.

    Notes:
        引数 records の順序と内容は変更しない.
    """
    if limit <= 0:
        return []
    return sorted(records, key=lambda record: (record.created_at, record.id), reverse=True)[:limit]


def _is_private_pair(
    record: InMemoryPrivateMessageRecord,
    user_id: int,
    peer_user_id: int,
) -> bool:
    """Private message が指定された二者間のいずれかの向きかを判定する.

    Args:
        record (InMemoryPrivateMessageRecord): 判定する private message record.
        user_id (int): 会話の一方の User ID.
        peer_user_id (int): 会話のもう一方の User ID.

    Returns:
        bool: sender/target が指定された二者のいずれかの順序に一致すれば True, それ以外は False.
    """
    return (record.sender_id == user_id and record.target_id == peer_user_id) or (
        record.sender_id == peer_user_id and record.target_id == user_id
    )


def _channel_message_to_read_model(
    record: InMemoryChannelMessageRecord,
) -> ChatHistoryMessage:
    """Channel message record を共通 history read model に変換する.

    Args:
        record (InMemoryChannelMessageRecord): 変換する Channel message record.

    Returns:
        ChatHistoryMessage: ID, sender ID, content, created_at を転記した read model.
    """
    return ChatHistoryMessage(
        id=record.id,
        sender_id=record.sender_id,
        content=record.content,
        created_at=record.created_at,
    )


def _private_message_to_read_model(record: InMemoryPrivateMessageRecord) -> ChatHistoryMessage:
    """Private message record を共通 history read model に変換する.

    Args:
        record (InMemoryPrivateMessageRecord): 変換する private message record.

    Returns:
        ChatHistoryMessage: ID, sender ID, content, created_at を転記した read model.
    """
    return ChatHistoryMessage(
        id=record.id,
        sender_id=record.sender_id,
        content=record.content,
        created_at=record.created_at,
    )
