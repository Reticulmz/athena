"""appとworkerで共有するchat providerを構成する."""

from __future__ import annotations

from typing import final

from dishka import Provider, Scope

from osu_server.composition.providers._dishka import provide
from osu_server.infrastructure.state.interfaces.channel_state_store import ChannelStateStore
from osu_server.repositories.interfaces.queries.channels import ChannelQueryRepository
from osu_server.repositories.interfaces.queries.chat import ChatHistoryQueryRepository
from osu_server.repositories.interfaces.unit_of_work import UnitOfWorkFactory
from osu_server.services.commands.chat import (
    JoinChannelUseCase,
    LeaveChannelUseCase,
    PersistChannelMessageUseCase,
    PersistPrivateMessageUseCase,
)
from osu_server.services.queries.chat import (
    ListAutojoinChannelsQuery,
    ListChannelMessagesQuery,
    ListPrivateMessagesQuery,
    ListVisibleChannelsQuery,
    ResolveChannelMessageDeliveryQuery,
)

_DISHKA_RUNTIME_HINTS = (
    ChannelQueryRepository,
    ChannelStateStore,
    ChatHistoryQueryRepository,
    UnitOfWorkFactory,
)


@final
class ChatProviderSet(Provider):
    """共有channel queryと軽量chat commandをAPP scopeで登録する.

    Attributes:
        scope (Scope): appとworker container内で共有するDishkaのAPP scope.
    """

    scope = Scope.APP

    @provide
    def list_visible_channels_query(
        self,
        channel_repository: ChannelQueryRepository,
        channel_state: ChannelStateStore,
    ) -> ListVisibleChannelsQuery:
        """利用者に公開するchannel一覧queryを構成する.

        Args:
            channel_repository (ChannelQueryRepository): channel定義を読むread repository.
            channel_state (ChannelStateStore): 現在のchannel参加状態を読むvolatile store.

        Returns:
            ListVisibleChannelsQuery: 権限とstateに応じた公開channelを列挙するquery.
        """
        return ListVisibleChannelsQuery(
            channel_repository=channel_repository,
            channel_state=channel_state,
        )

    @provide
    def list_autojoin_channels_query(
        self,
        channel_repository: ChannelQueryRepository,
        channel_state: ChannelStateStore,
    ) -> ListAutojoinChannelsQuery:
        """login時に自動参加するchannel一覧queryを構成する.

        Args:
            channel_repository (ChannelQueryRepository): channel定義を読むread repository.
            channel_state (ChannelStateStore): 現在のchannel参加状態を読むvolatile store.

        Returns:
            ListAutojoinChannelsQuery: autojoin対象channelを列挙するquery.
        """
        return ListAutojoinChannelsQuery(
            channel_repository=channel_repository,
            channel_state=channel_state,
        )

    @provide
    def resolve_channel_message_delivery_query(
        self,
        channel_repository: ChannelQueryRepository,
        channel_state: ChannelStateStore,
    ) -> ResolveChannelMessageDeliveryQuery:
        """Channel messageの配送対象を解決するqueryを構成する.

        Args:
            channel_repository (ChannelQueryRepository): channel定義と可視性を読むread repository.
            channel_state (ChannelStateStore): channel参加者を読むvolatile store.

        Returns:
            ResolveChannelMessageDeliveryQuery: messageを配送するsessionを決めるquery.
        """
        return ResolveChannelMessageDeliveryQuery(
            channel_repository=channel_repository,
            channel_state=channel_state,
        )

    @provide
    def list_channel_messages_query(
        self,
        repository: ChatHistoryQueryRepository,
    ) -> ListChannelMessagesQuery:
        """Channel historyを取得するqueryを構成する.

        Args:
            repository (ChatHistoryQueryRepository):
                channelとprivate messageの履歴を読むrepository.

        Returns:
            ListChannelMessagesQuery: channel message履歴をページング取得するquery.
        """
        return ListChannelMessagesQuery(repository)

    @provide
    def list_private_messages_query(
        self,
        repository: ChatHistoryQueryRepository,
    ) -> ListPrivateMessagesQuery:
        """Private message historyを取得するqueryを構成する.

        Args:
            repository (ChatHistoryQueryRepository):
                channelとprivate messageの履歴を読むrepository.

        Returns:
            ListPrivateMessagesQuery: private message履歴をページング取得するquery.
        """
        return ListPrivateMessagesQuery(repository)

    @provide
    def join_channel_use_case(
        self,
        channel_repository: ChannelQueryRepository,
        channel_state: ChannelStateStore,
    ) -> JoinChannelUseCase:
        """channel参加commandをchannel read modelとstate storeで構成する.

        Args:
            channel_repository (ChannelQueryRepository): 参加対象channelを検証するread repository.
            channel_state (ChannelStateStore): 参加状態を書き込むvolatile store.

        Returns:
            JoinChannelUseCase: channel参加可否を判定してstateを更新するcommand.
        """
        return JoinChannelUseCase(
            channel_repository=channel_repository,
            channel_state=channel_state,
        )

    @provide
    def leave_channel_use_case(self, channel_state: ChannelStateStore) -> LeaveChannelUseCase:
        """channel退出commandをstate storeで構成する.

        Args:
            channel_state (ChannelStateStore): 退出対象の参加状態を削除するvolatile store.

        Returns:
            LeaveChannelUseCase: channel退出時のstate更新を行うcommand.
        """
        return LeaveChannelUseCase(channel_state=channel_state)

    @provide
    def persist_channel_message_use_case(
        self,
        uow_factory: UnitOfWorkFactory,
    ) -> PersistChannelMessageUseCase:
        """Channel messageを永続化するcommandを構成する.

        Args:
            uow_factory (UnitOfWorkFactory):
                message保存をtransactionで実行するUnit of Work factory.

        Returns:
            PersistChannelMessageUseCase: channel message履歴を保存するcommand.
        """
        return PersistChannelMessageUseCase(uow_factory=uow_factory)

    @provide
    def persist_private_message_use_case(
        self,
        uow_factory: UnitOfWorkFactory,
    ) -> PersistPrivateMessageUseCase:
        """Private messageを永続化するcommandを構成する.

        Args:
            uow_factory (UnitOfWorkFactory):
                message保存をtransactionで実行するUnit of Work factory.

        Returns:
            PersistPrivateMessageUseCase: private message履歴を保存するcommand.
        """
        return PersistPrivateMessageUseCase(uow_factory=uow_factory)
