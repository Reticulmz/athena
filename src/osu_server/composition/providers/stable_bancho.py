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
from osu_server.repositories.interfaces.session_store import SessionStore
from osu_server.services.commands.beatmaps import RequestBeatmapFileWarmupUseCase
from osu_server.services.commands.chat import (
    JoinChannelUseCase,
    LeaveChannelUseCase,
    SendChannelMessageUseCase,
    SendPrivateMessageUseCase,
)
from osu_server.services.commands.identity import LoginCommandUseCase
from osu_server.services.queries.chat import (
    ListAutojoinChannelsQuery,
    ListVisibleChannelsQuery,
)
from osu_server.services.queries.identity import ListOnlineUsersQueryUseCase
from osu_server.transports.stable.bancho.dispatch import PacketDispatcher
from osu_server.transports.stable.bancho.endpoint import BanchoEndpoint
from osu_server.transports.stable.bancho.handlers.chat import ChatHandlers
from osu_server.transports.stable.bancho.handlers.lifecycle import LifecycleHandlers
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
    ListAutojoinChannelsQuery,
    ListOnlineUsersQueryUseCase,
    ListVisibleChannelsQuery,
    LoginCommandUseCase,
    PacketQueue,
    RequestBeatmapFileWarmupUseCase,
    SendChannelMessageUseCase,
    SendPrivateMessageUseCase,
    SessionStore,
    SystemUserIdentity,
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
        bot_identity: SystemUserIdentity,
    ) -> LoginResponseBuilder:
        return LoginResponseBuilder(
            visible_channels_query=visible_channels_query,
            autojoin_channels_query=autojoin_channels_query,
            bot_identity=bot_identity,
        )

    @provide
    def login_workflow(
        self,
        login_command: LoginCommandUseCase,
        country_resolver: CountryResolver,
        response_builder: LoginResponseBuilder,
    ) -> LoginWorkflow:
        return LoginWorkflow(
            login_command=login_command,
            country_resolver=country_resolver,
            response_builder=response_builder,
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
    def status_change_handlers(
        self,
        beatmap_file_warmup: RequestBeatmapFileWarmupUseCase,
    ) -> StatusChangeHandlers:
        return StatusChangeHandlers(
            beatmap_file_warmup=beatmap_file_warmup,
        )

    @provide
    def app_event_listeners(
        self,
        event_bus: LocalEventBus,
        packet_queue: PacketQueue,
        online_users_query: ListOnlineUsersQueryUseCase,
        channel_state: ChannelStateStore,
    ) -> AppEventListeners:
        setup_listeners(event_bus, packet_queue, online_users_query, channel_state)
        return AppEventListeners()

    @provide
    def packet_dispatcher(
        self,
        lifecycle_handlers: LifecycleHandlers,
        chat_handlers: ChatHandlers,
        status_change_handlers: StatusChangeHandlers,
        listeners: AppEventListeners,
    ) -> PacketDispatcher:
        _ = listeners
        dispatcher = PacketDispatcher()
        lifecycle_handlers.register_all(dispatcher)
        chat_handlers.register_all(dispatcher)
        status_change_handlers.register_all(dispatcher)
        return dispatcher

    @provide
    def polling_workflow(
        self,
        session_store: SessionStore,
        packet_queue: PacketQueue,
        packet_dispatcher: PacketDispatcher,
        config: AppConfig,
    ) -> PollingWorkflow:
        return PollingWorkflow(
            session_store=session_store,
            packet_queue=packet_queue,
            packet_dispatcher=packet_dispatcher,
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
