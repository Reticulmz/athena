"""Application service registration."""

from __future__ import annotations

from typing import TYPE_CHECKING

from glide import GlideClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
from taskiq import AsyncBroker

from osu_server.infrastructure.country.interfaces import CountryResolver
from osu_server.infrastructure.messaging.interfaces import EventBus
from osu_server.infrastructure.security.hibp import HIBPClient
from osu_server.infrastructure.state.interfaces.channel_state_store import ChannelStateStore
from osu_server.infrastructure.state.interfaces.packet_queue import PacketQueue
from osu_server.infrastructure.state.interfaces.rate_limiter import RateLimiter
from osu_server.infrastructure.state.memory.channel_state_store import InMemoryChannelStateStore
from osu_server.infrastructure.state.memory.rate_limiter import InMemoryRateLimiter
from osu_server.infrastructure.state.valkey.channel_state_store import ValkeyChannelStateStore
from osu_server.infrastructure.state.valkey.rate_limiter import ValkeyRateLimiter
from osu_server.jobs import register_all_jobs
from osu_server.repositories.interfaces.channel_repository import ChannelRepository
from osu_server.repositories.interfaces.chat_repository import ChatRepository
from osu_server.repositories.interfaces.role_repository import RoleRepository
from osu_server.repositories.interfaces.session_store import SessionStore
from osu_server.repositories.interfaces.user_repository import UserRepository
from osu_server.repositories.memory.channel_repository import InMemoryChannelRepository
from osu_server.repositories.memory.chat_repository import InMemoryChatRepository
from osu_server.repositories.memory.role_repository import InMemoryRoleRepository
from osu_server.repositories.memory.session_store import InMemorySessionStore
from osu_server.repositories.memory.user_repository import InMemoryUserRepository
from osu_server.repositories.sqlalchemy.channel_repository import SQLAlchemyChannelRepository
from osu_server.repositories.sqlalchemy.chat_repository import SQLAlchemyChatRepository
from osu_server.repositories.sqlalchemy.role_repository import SQLAlchemyRoleRepository
from osu_server.repositories.sqlalchemy.user_repository import SQLAlchemyUserRepository
from osu_server.repositories.valkey.session_store import ValkeySessionStore
from osu_server.services.auth_service import AuthService
from osu_server.services.channel_service import ChannelService
from osu_server.services.chat_service import ChatService
from osu_server.services.command_service import CommandService
from osu_server.services.online_users import OnlineUsersService
from osu_server.services.password_service import PasswordService
from osu_server.services.permission_service import PermissionService
from osu_server.services.private_message_service import PrivateMessageService
from osu_server.transports.bancho.dispatch import PacketDispatcher
from osu_server.transports.bancho.endpoint import BanchoEndpoint
from osu_server.transports.bancho.handlers.chat import ChatHandlers
from osu_server.transports.bancho.handlers.lifecycle import LifecycleHandlers
from osu_server.transports.bancho.listeners import setup_listeners
from osu_server.transports.bancho.workflows.login import LoginWorkflow
from osu_server.transports.bancho.workflows.login_response_builder import LoginResponseBuilder
from osu_server.transports.bancho.workflows.polling import PollingWorkflow
from osu_server.transports.web_legacy.registration import RegistrationHandler

if TYPE_CHECKING:
    from osu_server.config import AppConfig
    from osu_server.infrastructure.di.container import Container


def _register_repositories(
    container: Container,
    config: AppConfig,
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """Register repository implementations for the current environment."""
    if config.environment == "test":
        container.register_singleton(UserRepository, InMemoryUserRepository)
        container.register_singleton(RoleRepository, InMemoryRoleRepository)
        container.register_singleton(ChannelRepository, InMemoryChannelRepository)
        container.register_singleton(ChatRepository, InMemoryChatRepository)
        return

    container.register_singleton(
        UserRepository,
        lambda: SQLAlchemyUserRepository(session_factory),
    )
    container.register_singleton(
        RoleRepository,
        lambda: SQLAlchemyRoleRepository(session_factory),
    )
    container.register_singleton(
        ChannelRepository,
        lambda: SQLAlchemyChannelRepository(session_factory),
    )
    container.register_singleton(
        ChatRepository,
        lambda: SQLAlchemyChatRepository(session_factory),
    )


async def register_services(container: Container, config: AppConfig) -> None:  # noqa: PLR0915
    """Register repository, service, and transport-layer components.

    Called from the composition root (lifespan) after infrastructure-layer
    registrations are complete.  Kept separate from ``build_container`` to
    respect the import-linter layer contracts (infrastructure must not import
    from repositories / services / transports).

    Also resolves ``EventBus`` and ``PacketQueue`` to wire domain event
    listeners via ``setup_listeners()``.
    """
    session_factory = await container.resolve(async_sessionmaker[AsyncSession])
    hibp_client = await container.resolve(HIBPClient)
    country_resolver = await container.resolve(CountryResolver)
    valkey = await container.resolve(GlideClient)

    # -- SessionStore (singleton, environment-based switching) -----------------
    if config.environment == "test":
        container.register_singleton(SessionStore, InMemorySessionStore)
    else:
        container.register_singleton(
            SessionStore,
            lambda: ValkeySessionStore(valkey, ttl=config.session_ttl),
        )

    session_store = await container.resolve(SessionStore)

    # -- PasswordService (singleton) ------------------------------------------
    password_service = PasswordService(
        hibp_client=hibp_client,
        banned_passwords=config.banned_passwords,
    )
    container.register_singleton(PasswordService, lambda: password_service)

    # -- Repositories (singleton, environment-based switching) ----------------
    _register_repositories(container, config, session_factory)

    # -- PermissionService (singleton) ----------------------------------------
    role_repo = await container.resolve(RoleRepository)
    permission_service = PermissionService(role_repo=role_repo)
    container.register_singleton(PermissionService, lambda: permission_service)

    # -- AuthService (singleton) ----------------------------------------------
    user_repo = await container.resolve(UserRepository)
    auth_service = AuthService(
        user_repo=user_repo,
        role_repo=role_repo,
        password_service=password_service,
        permission_service=permission_service,
        session_store=session_store,
    )
    container.register_singleton(AuthService, lambda: auth_service)

    # -- OnlineUsersService (singleton) -----------------------------------------
    online_users = OnlineUsersService(session_store=session_store)
    container.register_singleton(OnlineUsersService, lambda: online_users)

    # -- ChannelStateStore (singleton, environment-based switching) -----------
    if config.environment == "test":
        container.register_singleton(ChannelStateStore, InMemoryChannelStateStore)
    else:
        container.register_singleton(
            ChannelStateStore,
            lambda: ValkeyChannelStateStore(valkey),
        )

    # -- RateLimiter (singleton, environment-based switching) ----------------
    if config.environment == "test":
        container.register_singleton(RateLimiter, InMemoryRateLimiter)
    else:
        container.register_singleton(
            RateLimiter,
            lambda: ValkeyRateLimiter(valkey),
        )

    # -- ChannelService (singleton) --------------------------------------------
    channel_repo = await container.resolve(ChannelRepository)
    channel_state = await container.resolve(ChannelStateStore)
    channel_service = ChannelService(
        channel_repo=channel_repo,
        channel_state=channel_state,
    )
    container.register_singleton(ChannelService, lambda: channel_service)

    # -- PrivateMessageService (singleton) -------------------------------------
    pm_service = PrivateMessageService(
        user_repo=user_repo,
        session_store=session_store,
    )
    container.register_singleton(PrivateMessageService, lambda: pm_service)

    # -- CommandService (singleton) -------------------------------------------
    command_service = CommandService()
    container.register_singleton(CommandService, lambda: command_service)

    # -- BanchoEndpoint & Workflows (singletons) ------------------------------
    packet_queue = await container.resolve(PacketQueue)
    eventbus = await container.resolve(EventBus)
    broker = await container.resolve(AsyncBroker)
    register_all_jobs(broker)

    login_response_builder = LoginResponseBuilder(channel_service=channel_service)
    container.register_singleton(LoginResponseBuilder, lambda: login_response_builder)

    login_workflow = LoginWorkflow(
        auth_service=auth_service,
        country_resolver=country_resolver,
        response_builder=login_response_builder,
    )
    container.register_singleton(LoginWorkflow, lambda: login_workflow)

    packet_dispatcher = PacketDispatcher()
    container.register_singleton(PacketDispatcher, lambda: packet_dispatcher)

    polling_workflow = PollingWorkflow(
        session_store=session_store,
        packet_queue=packet_queue,
        packet_dispatcher=packet_dispatcher,
        session_ttl=config.session_ttl,
        max_request_body_size=config.max_request_body_size,
    )
    container.register_singleton(PollingWorkflow, lambda: polling_workflow)

    bancho_endpoint = BanchoEndpoint(
        login_workflow=login_workflow,
        polling_workflow=polling_workflow,
    )
    container.register_singleton(BanchoEndpoint, lambda: bancho_endpoint)

    # -- ChatService (singleton, requires EventBus) ---------------------------
    rate_limiter = await container.resolve(RateLimiter)
    chat_repo = await container.resolve(ChatRepository)
    chat_service = ChatService(
        channel_service=channel_service,
        private_message_service=pm_service,
        command_service=command_service,
        session_store=session_store,
        event_bus=eventbus,
        rate_limiter=rate_limiter,
        config=config,
        chat_repository=chat_repo,
    )
    container.register_singleton(ChatService, lambda: chat_service)

    # -- Handlers → PacketDispatcher ------------------------------------------
    lifecycle_handlers = LifecycleHandlers(
        session_store=session_store,
        event_bus=eventbus,
    )
    chat_handlers = ChatHandlers(
        chat_service=chat_service,
        channel_service=channel_service,
        session_store=session_store,
        packet_queue=packet_queue,
    )
    lifecycle_handlers.register_all(packet_dispatcher)
    chat_handlers.register_all(packet_dispatcher)

    # -- Listeners → EventBus --------------------------------------------------
    setup_listeners(eventbus, packet_queue, online_users, broker, channel_state)

    # -- RegistrationHandler (singleton) --------------------------------------
    registration_handler = RegistrationHandler(auth_service=auth_service)
    container.register_singleton(RegistrationHandler, lambda: registration_handler)
