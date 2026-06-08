"""Application service registration."""

from __future__ import annotations

from datetime import timedelta
from typing import TYPE_CHECKING

from glide import GlideClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
from taskiq import AsyncBroker

from osu_server.domain.beatmap import (
    BeatmapFileProvider,
    BeatmapFreshnessPolicy,
    BeatmapMetadataProvider,
)
from osu_server.domain.system_user import BANCHO_BOT_USER_ID, create_bancho_bot_identity
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
from osu_server.infrastructure.storage import create_blob_storage_backend
from osu_server.infrastructure.storage.interfaces import BlobStorageBackend
from osu_server.jobs import register_all_jobs
from osu_server.repositories.beatmaps.file_sources import CompositeBeatmapFileProvider
from osu_server.repositories.beatmaps.metadata_providers import (
    CompositeBeatmapMetadataProvider,
)
from osu_server.repositories.beatmaps.providers import (
    InMemoryBeatmapMetadataProvider,
    MirrorMetadataProvider,
    OsuApiMetadataProvider,
)
from osu_server.repositories.interfaces.beatmap_repository import (
    BeatmapFetchTarget,
    BeatmapRepository,
)
from osu_server.repositories.interfaces.blob_repository import BlobRepository
from osu_server.repositories.interfaces.channel_repository import ChannelRepository
from osu_server.repositories.interfaces.chat_repository import ChatRepository
from osu_server.repositories.interfaces.role_repository import RoleRepository
from osu_server.repositories.interfaces.session_store import SessionStore
from osu_server.repositories.interfaces.user_repository import UserRepository
from osu_server.repositories.memory.beatmap_repository import InMemoryBeatmapRepository
from osu_server.repositories.memory.blob_repository import InMemoryBlobRepository
from osu_server.repositories.memory.channel_repository import InMemoryChannelRepository
from osu_server.repositories.memory.chat_repository import InMemoryChatRepository
from osu_server.repositories.memory.role_repository import InMemoryRoleRepository
from osu_server.repositories.memory.session_store import InMemorySessionStore
from osu_server.repositories.memory.user_repository import InMemoryUserRepository
from osu_server.repositories.sqlalchemy.beatmap_repository import SQLAlchemyBeatmapRepository
from osu_server.repositories.sqlalchemy.blob_repository import SQLAlchemyBlobRepository
from osu_server.repositories.sqlalchemy.channel_repository import SQLAlchemyChannelRepository
from osu_server.repositories.sqlalchemy.chat_repository import SQLAlchemyChatRepository
from osu_server.repositories.sqlalchemy.role_repository import SQLAlchemyRoleRepository
from osu_server.repositories.sqlalchemy.user_repository import SQLAlchemyUserRepository
from osu_server.repositories.valkey.session_store import ValkeySessionStore
from osu_server.services.auth_service import AuthService
from osu_server.services.bancho_bot.command_service import CommandService
from osu_server.services.bancho_bot.commands import create_builtin_registry
from osu_server.services.beatmap_mirror_service import (
    BeatmapEligibilityService,
    BeatmapMirrorService,
)
from osu_server.services.blob_storage_service import BlobStorageService
from osu_server.services.channel_service import ChannelService
from osu_server.services.chat_service import ChatService
from osu_server.services.legacy_getscores_service import LegacyGetscoresService
from osu_server.services.legacy_web_auth_service import LegacyWebAuthService
from osu_server.services.online_users import OnlineUsersService
from osu_server.services.password_service import PasswordService
from osu_server.services.permission_service import PermissionService
from osu_server.services.private_message_service import PrivateMessageService
from osu_server.services.session_authorization_service import (
    SessionAuthorizationService,
)
from osu_server.transports.bancho.dispatch import PacketDispatcher
from osu_server.transports.bancho.endpoint import BanchoEndpoint
from osu_server.transports.bancho.handlers.chat import ChatHandlers
from osu_server.transports.bancho.handlers.lifecycle import LifecycleHandlers
from osu_server.transports.bancho.listeners import setup_listeners
from osu_server.transports.bancho.workflows.login import LoginWorkflow
from osu_server.transports.bancho.workflows.login_response_builder import LoginResponseBuilder
from osu_server.transports.bancho.workflows.polling import PollingWorkflow
from osu_server.transports.web_legacy.getscores import GetscoresHandler
from osu_server.transports.web_legacy.registration import RegistrationHandler

if TYPE_CHECKING:
    from osu_server.config import AppConfig
    from osu_server.infrastructure.di.container import Container


async def _enqueue_beatmap_fetch(broker: AsyncBroker, target: BeatmapFetchTarget) -> None:
    """Enqueue the worker job matching a beatmap fetch target."""
    if target.target_type.startswith("file:"):
        task_name = "fetch_beatmap_file"
    else:
        task_name = "fetch_beatmap_metadata"
    task = broker.find_task(task_name)
    if task is None:
        return

    _ = await task.kiq(target.target_type, target.target_key)


def _register_repositories(
    container: Container,
    config: AppConfig,
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """Register repository implementations for the current environment."""
    if config.environment == "test":
        container.register_singleton(BlobRepository, InMemoryBlobRepository)
        container.register_singleton(UserRepository, InMemoryUserRepository)
        container.register_singleton(RoleRepository, InMemoryRoleRepository)
        container.register_singleton(ChannelRepository, InMemoryChannelRepository)
        container.register_singleton(ChatRepository, InMemoryChatRepository)
        container.register_singleton(BeatmapRepository, InMemoryBeatmapRepository)
        return

    container.register_singleton(
        BlobRepository,
        lambda: SQLAlchemyBlobRepository(session_factory),
    )
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
    container.register_singleton(
        BeatmapRepository,
        lambda: SQLAlchemyBeatmapRepository(session_factory),
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

    # -- BlobStorage backend/service (singleton) ------------------------------
    blob_backend = create_blob_storage_backend(config)
    await blob_backend.validate_configuration()
    container.register_singleton(BlobStorageBackend, lambda: blob_backend)
    blob_repo = await container.resolve(BlobRepository)
    blob_storage_service = BlobStorageService(
        blob_repo=blob_repo,
        backend=blob_backend,
        storage_backend=config.blob_storage_backend,
    )
    container.register_singleton(BlobStorageService, lambda: blob_storage_service)

    # -- BeatmapFreshnessPolicy (singleton) ----------------------------------
    freshness_policy = BeatmapFreshnessPolicy(
        ranked_refresh_interval=timedelta(seconds=config.beatmap_ranked_refresh_interval_seconds),
        pending_refresh_interval=timedelta(
            seconds=config.beatmap_pending_refresh_interval_seconds
        ),
        graveyard_refresh_interval=timedelta(
            seconds=config.beatmap_graveyard_refresh_interval_seconds
        ),
        mirror_refresh_interval=timedelta(seconds=config.beatmap_mirror_refresh_interval_seconds),
    )
    container.register_singleton(BeatmapFreshnessPolicy, lambda: freshness_policy)

    # -- BeatmapMetadataProvider (singleton, environment-based switching) ----
    if config.environment == "test":
        official_metadata_provider = InMemoryBeatmapMetadataProvider()
        mirror_metadata_provider = InMemoryBeatmapMetadataProvider()
    else:
        official_metadata_provider = OsuApiMetadataProvider(
            client_id=config.beatmap_official_api_client_id,  # pyright: ignore[reportArgumentType]
            client_secret=config.beatmap_official_api_client_secret,  # pyright: ignore[reportArgumentType]
        )
        mirror_metadata_provider = MirrorMetadataProvider(
            base_urls=config.beatmap_metadata_mirror_base_urls,
        )

    infrastructure_metadata_provider = CompositeBeatmapMetadataProvider(
        official=official_metadata_provider,
        mirror=mirror_metadata_provider,
    )
    container.register_singleton(BeatmapMetadataProvider, lambda: infrastructure_metadata_provider)

    # -- BeatmapFileProvider (singleton) -------------------------------------
    file_provider = CompositeBeatmapFileProvider(
        osu_current_url_template=config.beatmap_osu_current_url_template,
        osu_legacy_url_template=config.beatmap_osu_legacy_url_template,
        mirror_url_templates=list(config.beatmap_community_mirror_url_templates),
    )
    container.register_singleton(BeatmapFileProvider, lambda: file_provider)

    # -- BeatmapEligibilityService (singleton) -------------------------------
    eligibility_service = BeatmapEligibilityService()
    container.register_singleton(BeatmapEligibilityService, lambda: eligibility_service)

    # -- BeatmapMirrorService (singleton) ------------------------------------
    beatmap_repo = await container.resolve(BeatmapRepository)
    mirror_trust_enabled = config.beatmap_mirror_trust_policy == "trusted"
    broker = await container.resolve(AsyncBroker)
    mirror_service = BeatmapMirrorService(
        repository=beatmap_repo,
        eligibility_service=eligibility_service,
        freshness_policy=freshness_policy,
        mirror_trust_enabled=mirror_trust_enabled,
        official_sources_available=config.beatmap_official_sources_enabled,
        enqueue_refresh=lambda target: _enqueue_beatmap_fetch(broker, target),
    )
    container.register_singleton(BeatmapMirrorService, lambda: mirror_service)

    # -- SystemUserIdentity (singleton) ---------------------------------------
    identity = create_bancho_bot_identity(config.bancho_bot_username)
    container.register_singleton(
        type(identity),
        lambda: identity,
    )

    # -- BanchoBot system user sync (startup validation) ----------------------
    user_repo = await container.resolve(UserRepository)
    try:
        await user_repo.sync_system_user(identity)
    except ValueError as exc:
        msg = f"BanchoBot system user sync failed: {exc}"
        raise RuntimeError(msg) from exc

    # -- PermissionService (singleton) ----------------------------------------
    role_repo = await container.resolve(RoleRepository)
    permission_service = PermissionService(role_repo=role_repo)
    container.register_singleton(PermissionService, lambda: permission_service)

    # -- AuthService (singleton) ----------------------------------------------
    auth_service = AuthService(
        user_repo=user_repo,
        role_repo=role_repo,
        password_service=password_service,
        permission_service=permission_service,
        session_store=session_store,
        system_user_id=BANCHO_BOT_USER_ID,
    )
    container.register_singleton(AuthService, lambda: auth_service)

    # -- SessionAuthorizationService (singleton) ---------------------------------
    session_auth_service = SessionAuthorizationService(
        permission_service=permission_service,
        session_store=session_store,
        role_repository=role_repo,
    )
    container.register_singleton(
        SessionAuthorizationService,
        lambda: session_auth_service,
    )

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
    builtin_registry = create_builtin_registry()
    command_service = CommandService(builtin_registry)
    container.register_singleton(CommandService, lambda: command_service)

    # -- Job Queue (broker registration) --------------------------------------
    broker = await container.resolve(AsyncBroker)
    register_all_jobs(broker)

    # -- BanchoEndpoint & Workflows (singletons) ------------------------------
    packet_queue = await container.resolve(PacketQueue)
    eventbus = await container.resolve(EventBus)

    login_response_builder = LoginResponseBuilder(
        channel_service=channel_service,
        bot_identity=identity,
    )
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

    # -- LegacyWebAuthService (singleton) -------------------------------------
    legacy_web_auth_service = LegacyWebAuthService(
        user_repo=user_repo,
        password_service=password_service,
        session_store=session_store,
    )
    container.register_singleton(LegacyWebAuthService, lambda: legacy_web_auth_service)

    # -- Getscores service / endpoint (singletons) ----------------------------
    getscores_service = LegacyGetscoresService(
        repository=beatmap_repo,
        mirror_resolve=mirror_service.resolve_by_checksum,
    )
    container.register_singleton(LegacyGetscoresService, lambda: getscores_service)

    getscores_handler = GetscoresHandler(
        auth_service=legacy_web_auth_service,
        getscores_service=getscores_service,
    )
    container.register_singleton(GetscoresHandler, lambda: getscores_handler)
