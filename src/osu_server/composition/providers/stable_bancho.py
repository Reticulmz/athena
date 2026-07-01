"""Stable bancho transport providers."""

from __future__ import annotations

from dataclasses import dataclass
from typing import final

from dishka import Provider, Scope

from osu_server.composition.providers._dishka import provide
from osu_server.config import AppConfig
from osu_server.domain.identity.system_users import SystemUserIdentity
from osu_server.infrastructure.country.interfaces import CountryResolver
from osu_server.infrastructure.messaging.local import LocalEventBus
from osu_server.infrastructure.state.interfaces.channel_state_store import ChannelStateStore
from osu_server.infrastructure.state.interfaces.packet_queue import PacketQueue
from osu_server.infrastructure.state.interfaces.stable_user_status_store import (
    StableUserStatusStore,
)
from osu_server.repositories.interfaces.session_store import SessionStore
from osu_server.services.commands.beatmaps import RequestBeatmapFileWarmupUseCase
from osu_server.services.commands.chat import (
    JoinChannelUseCase,
    LeaveChannelUseCase,
    SendChannelMessageUseCase,
    SendPrivateMessageUseCase,
)
from osu_server.services.commands.identity import (
    AddFriendUseCase,
    LoginCommandUseCase,
    RemoveFriendUseCase,
    UpdateFriendOnlyDmUseCase,
)
from osu_server.services.queries.chat import (
    ListAutojoinChannelsQuery,
    ListVisibleChannelsQuery,
)
from osu_server.services.queries.identity import (
    GetActiveSessionsByUserIdsQueryUseCase,
    ListActiveSessionsQueryUseCase,
    ListFriendIdsQuery,
)
from osu_server.services.queries.scores import CurrentUserStatsQuery
from osu_server.transports.stable.bancho.dispatch import PacketDispatcher
from osu_server.transports.stable.bancho.endpoint import BanchoEndpoint
from osu_server.transports.stable.bancho.handlers.chat import ChatHandlers
from osu_server.transports.stable.bancho.handlers.friends import FriendHandlers
from osu_server.transports.stable.bancho.handlers.lifecycle import LifecycleHandlers
from osu_server.transports.stable.bancho.handlers.presence import PresenceHandlers
from osu_server.transports.stable.bancho.handlers.stats import StatsRequestHandler
from osu_server.transports.stable.bancho.handlers.status import StatusChangeHandlers
from osu_server.transports.stable.bancho.listeners import setup_listeners
from osu_server.transports.stable.bancho.workflows.login import LoginWorkflow
from osu_server.transports.stable.bancho.workflows.login_response_builder import (
    LoginResponseBuilder,
)
from osu_server.transports.stable.bancho.workflows.polling import PollingWorkflow

_DISHKA_RUNTIME_HINTS = (
    AppConfig,
    ChannelStateStore,
    CountryResolver,
    LocalEventBus,
    JoinChannelUseCase,
    LeaveChannelUseCase,
    AddFriendUseCase,
    GetActiveSessionsByUserIdsQueryUseCase,
    ListActiveSessionsQueryUseCase,
    ListAutojoinChannelsQuery,
    ListFriendIdsQuery,
    ListVisibleChannelsQuery,
    LoginCommandUseCase,
    CurrentUserStatsQuery,
    PacketQueue,
    RequestBeatmapFileWarmupUseCase,
    RemoveFriendUseCase,
    SendChannelMessageUseCase,
    SendPrivateMessageUseCase,
    SessionStore,
    StableUserStatusStore,
    StatsRequestHandler,
    SystemUserIdentity,
    UpdateFriendOnlyDmUseCase,
)


@dataclass(frozen=True, slots=True)
class AppEventListeners:
    """Marker proving app event listeners were registered."""

    registered: bool = True


@final
class StableBanchoProviderSet(Provider):
    """Providers for stable bancho login, polling, handlers, and listeners."""

    scope = Scope.APP

    @provide
    def login_response_builder(
        self,
        visible_channels_query: ListVisibleChannelsQuery,
        autojoin_channels_query: ListAutojoinChannelsQuery,
        friend_ids_query: ListFriendIdsQuery,
        active_sessions_query: ListActiveSessionsQueryUseCase,
        current_user_stats_query: CurrentUserStatsQuery,
        stable_user_status_store: StableUserStatusStore,
        bot_identity: SystemUserIdentity,
    ) -> LoginResponseBuilder:
        return LoginResponseBuilder(
            visible_channels_query=visible_channels_query,
            autojoin_channels_query=autojoin_channels_query,
            friend_ids_query=friend_ids_query,
            active_sessions_query=active_sessions_query,
            current_user_stats_query=current_user_stats_query,
            stable_user_status_store=stable_user_status_store,
            bot_identity=bot_identity,
        )

    @provide
    def login_workflow(
        self,
        login_command: LoginCommandUseCase,
        country_resolver: CountryResolver,
        response_builder: LoginResponseBuilder,
        event_bus: LocalEventBus,
    ) -> LoginWorkflow:
        return LoginWorkflow(
            login_command=login_command,
            country_resolver=country_resolver,
            response_builder=response_builder,
            event_bus=event_bus,
        )

    @provide
    def lifecycle_handlers(
        self,
        session_store: SessionStore,
        event_bus: LocalEventBus,
    ) -> LifecycleHandlers:
        return LifecycleHandlers(session_store=session_store, event_bus=event_bus)

    @provide
    def chat_handlers(
        self,
        send_channel_message: SendChannelMessageUseCase,
        send_private_message: SendPrivateMessageUseCase,
        join_channel: JoinChannelUseCase,
        leave_channel: LeaveChannelUseCase,
        session_store: SessionStore,
        packet_queue: PacketQueue,
    ) -> ChatHandlers:
        return ChatHandlers(
            send_channel_message=send_channel_message,
            send_private_message=send_private_message,
            join_channel=join_channel,
            leave_channel=leave_channel,
            session_store=session_store,
            packet_queue=packet_queue,
        )

    @provide
    def friend_handlers(
        self,
        add_friend: AddFriendUseCase,
        remove_friend: RemoveFriendUseCase,
        update_friend_only_dm: UpdateFriendOnlyDmUseCase,
    ) -> FriendHandlers:
        return FriendHandlers(
            add_friend=add_friend,
            remove_friend=remove_friend,
            update_friend_only_dm=update_friend_only_dm,
        )

    @provide
    def status_change_handlers(
        self,
        beatmap_file_warmup: RequestBeatmapFileWarmupUseCase,
        current_user_stats_query: CurrentUserStatsQuery,
        active_sessions_query: ListActiveSessionsQueryUseCase,
        packet_queue: PacketQueue,
        stable_user_status_store: StableUserStatusStore,
    ) -> StatusChangeHandlers:
        return StatusChangeHandlers(
            beatmap_file_warmup=beatmap_file_warmup,
            stable_user_status_store=stable_user_status_store,
            current_user_stats_query=current_user_stats_query,
            packet_queue=packet_queue,
            active_sessions_query=active_sessions_query,
        )

    @provide
    def presence_handlers(
        self,
        active_sessions_query: ListActiveSessionsQueryUseCase,
        active_sessions_by_user_ids_query: GetActiveSessionsByUserIdsQueryUseCase,
        packet_queue: PacketQueue,
        bot_identity: SystemUserIdentity,
        stable_user_status_store: StableUserStatusStore,
    ) -> PresenceHandlers:
        return PresenceHandlers(
            active_sessions_query=active_sessions_query,
            active_sessions_by_user_ids_query=active_sessions_by_user_ids_query,
            packet_queue=packet_queue,
            bot_identity=bot_identity,
            stable_user_status_store=stable_user_status_store,
        )

    @provide
    def stats_request_handler(
        self,
        current_user_stats_query: CurrentUserStatsQuery,
        active_sessions_by_user_ids_query: GetActiveSessionsByUserIdsQueryUseCase,
        packet_queue: PacketQueue,
        stable_user_status_store: StableUserStatusStore,
        bot_identity: SystemUserIdentity,
    ) -> StatsRequestHandler:
        return StatsRequestHandler(
            current_user_stats_query=current_user_stats_query,
            packet_queue=packet_queue,
            stable_user_status_store=stable_user_status_store,
            active_sessions_by_user_ids_query=active_sessions_by_user_ids_query,
            bot_identity=bot_identity,
        )

    @provide
    def app_event_listeners(
        self,
        event_bus: LocalEventBus,
        packet_queue: PacketQueue,
        active_sessions_query: ListActiveSessionsQueryUseCase,
        current_user_stats_query: CurrentUserStatsQuery,
        channel_state: ChannelStateStore,
        stable_user_status_store: StableUserStatusStore,
    ) -> AppEventListeners:
        setup_listeners(
            event_bus,
            packet_queue,
            active_sessions_query,
            channel_state,
            current_user_stats_query,
            stable_user_status_store,
        )
        return AppEventListeners()

    @provide
    def packet_dispatcher(
        self,
        lifecycle_handlers: LifecycleHandlers,
        chat_handlers: ChatHandlers,
        friend_handlers: FriendHandlers,
        status_change_handlers: StatusChangeHandlers,
        presence_handlers: PresenceHandlers,
        stats_request_handler: StatsRequestHandler,
        listeners: AppEventListeners,
    ) -> PacketDispatcher:
        _ = listeners
        dispatcher = PacketDispatcher()
        lifecycle_handlers.register_all(dispatcher)
        chat_handlers.register_all(dispatcher)
        friend_handlers.register_all(dispatcher)
        status_change_handlers.register_all(dispatcher)
        presence_handlers.register_all(dispatcher)
        stats_request_handler.register_all(dispatcher)
        return dispatcher

    @provide
    def polling_workflow(
        self,
        session_store: SessionStore,
        packet_queue: PacketQueue,
        packet_dispatcher: PacketDispatcher,
        stable_user_status_store: StableUserStatusStore,
        config: AppConfig,
    ) -> PollingWorkflow:
        return PollingWorkflow(
            session_store=session_store,
            packet_queue=packet_queue,
            packet_dispatcher=packet_dispatcher,
            stable_user_status_store=stable_user_status_store,
            session_ttl=config.session_ttl,
            max_request_body_size=config.max_request_body_size,
        )

    @provide
    def bancho_endpoint(
        self,
        login_workflow: LoginWorkflow,
        polling_workflow: PollingWorkflow,
    ) -> BanchoEndpoint:
        return BanchoEndpoint(
            login_workflow=login_workflow,
            polling_workflow=polling_workflow,
        )
