"""channelとprivate messageの永続化済みhistoryを読むquery use-caseを定義する."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from osu_server.repositories.interfaces.queries import (
        ChatHistoryMessage,
        ChatHistoryQueryRepository,
    )


@dataclass(frozen=True, slots=True)
class ListChannelMessagesQueryInput:
    """channel historyを読むためのcursor入力を表す.

    Attributes:
        channel_name (str): historyを読むchannel名.
        limit (int): 返すmessage数の上限.
        before_message_id (int | None): このIDより前へ遡るoptional cursor.
    """

    channel_name: str
    limit: int
    before_message_id: int | None = None


@dataclass(frozen=True, slots=True)
class ListPrivateMessagesQueryInput:
    """private message historyを読むためのcursor入力を表す.

    Attributes:
        user_id (int): historyの一方のuser ID.
        peer_user_id (int): historyの相手user ID.
        limit (int): 返すmessage数の上限.
        before_message_id (int | None): このIDより前へ遡るoptional cursor.
    """

    user_id: int
    peer_user_id: int
    limit: int
    before_message_id: int | None = None


@dataclass(frozen=True, slots=True)
class ChatHistoryQueryResult:
    """channelまたはprivate message historyのread-only結果を表す.

    Attributes:
        messages (tuple[ChatHistoryMessage, ...]): cursorとlimitを適用した永続化済みmessage列.
    """

    messages: tuple[ChatHistoryMessage, ...]


class ListChannelMessagesQuery:
    """永続化済みchannel message historyをread-onlyに取得する.

    Attributes:
        _repository (ChatHistoryQueryRepository): channelとprivate historyを読むrepository.
    """

    def __init__(self, repository: ChatHistoryQueryRepository) -> None:
        """History queryに使うread-only repositoryを保持する.

        Args:
            repository (ChatHistoryQueryRepository): 永続化済みchat historyを読むrepository.
        """
        self._repository: ChatHistoryQueryRepository = repository

    async def execute(
        self,
        input_data: ListChannelMessagesQueryInput,
    ) -> ChatHistoryQueryResult:
        """cursorとlimitを適用したchannel message historyを取得する.

        Args:
            input_data (ListChannelMessagesQueryInput): channel名とcursorとlimitを持つ入力.

        Returns:
            ChatHistoryQueryResult: 永続化済みchannel messageをtuple化した結果.
        """
        messages = await self._repository.list_channel_messages(
            input_data.channel_name,
            limit=input_data.limit,
            before_message_id=input_data.before_message_id,
        )
        return ChatHistoryQueryResult(messages=tuple(messages))


class ListPrivateMessagesQuery:
    """永続化済みprivate message historyをread-onlyに取得する.

    Attributes:
        _repository (ChatHistoryQueryRepository): channelとprivate historyを読むrepository.
    """

    def __init__(self, repository: ChatHistoryQueryRepository) -> None:
        """History queryに使うread-only repositoryを保持する.

        Args:
            repository (ChatHistoryQueryRepository): 永続化済みchat historyを読むrepository.
        """
        self._repository: ChatHistoryQueryRepository = repository

    async def execute(
        self,
        input_data: ListPrivateMessagesQueryInput,
    ) -> ChatHistoryQueryResult:
        """cursorとlimitを適用したprivate message historyを取得する.

        Args:
            input_data (ListPrivateMessagesQueryInput): user pairとcursorとlimitを持つ入力.

        Returns:
            ChatHistoryQueryResult: 永続化済みprivate messageをtuple化した結果.
        """
        messages = await self._repository.list_private_messages(
            input_data.user_id,
            input_data.peer_user_id,
            limit=input_data.limit,
            before_message_id=input_data.before_message_id,
        )
        return ChatHistoryQueryResult(messages=tuple(messages))
