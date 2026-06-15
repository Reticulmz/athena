"""Shared chat providers for app and worker dependency graphs."""

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
    """Providers for shared channel queries and lightweight chat commands."""

    scope = Scope.APP

    @provide
    def list_visible_channels_query(
        self,
        channel_repository: ChannelQueryRepository,
        channel_state: ChannelStateStore,
    ) -> ListVisibleChannelsQuery:
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
        return ResolveChannelMessageDeliveryQuery(
            channel_repository=channel_repository,
            channel_state=channel_state,
        )

    @provide
    def list_channel_messages_query(
        self,
        repository: ChatHistoryQueryRepository,
    ) -> ListChannelMessagesQuery:
        return ListChannelMessagesQuery(repository)

    @provide
    def list_private_messages_query(
        self,
        repository: ChatHistoryQueryRepository,
    ) -> ListPrivateMessagesQuery:
        return ListPrivateMessagesQuery(repository)

    @provide
    def join_channel_use_case(
        self,
        channel_repository: ChannelQueryRepository,
        channel_state: ChannelStateStore,
    ) -> JoinChannelUseCase:
        return JoinChannelUseCase(
            channel_repository=channel_repository,
            channel_state=channel_state,
        )

    @provide
    def leave_channel_use_case(self, channel_state: ChannelStateStore) -> LeaveChannelUseCase:
        return LeaveChannelUseCase(channel_state=channel_state)

    @provide
    def persist_channel_message_use_case(
        self,
        uow_factory: UnitOfWorkFactory,
    ) -> PersistChannelMessageUseCase:
        return PersistChannelMessageUseCase(uow_factory=uow_factory)

    @provide
    def persist_private_message_use_case(
        self,
        uow_factory: UnitOfWorkFactory,
    ) -> PersistPrivateMessageUseCase:
        return PersistPrivateMessageUseCase(uow_factory=uow_factory)
