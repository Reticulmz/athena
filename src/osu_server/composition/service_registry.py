"""Application service registration."""

from __future__ import annotations

from datetime import timedelta
from typing import TYPE_CHECKING

from glide import GlideClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
from taskiq import AsyncBroker

from osu_server.domain.beatmaps import (
    BeatmapFileProvider,
    BeatmapFreshnessPolicy,
    BeatmapMetadataProvider,
)
from osu_server.domain.system_user import BANCHO_BOT_USER_ID, create_bancho_bot_identity
from osu_server.infrastructure.country.interfaces import CountryResolver
from osu_server.infrastructure.crypto import ScoreCryptoService
from osu_server.infrastructure.messaging.interfaces import EventBus
from osu_server.infrastructure.parsers.multipart_parser import MultipartLimits
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
from osu_server.repositories.beatmaps.metadata_providers import (
    CompositeBeatmapMetadataProvider,
)
from osu_server.repositories.interfaces.beatmap_repository import (
    BeatmapFetchTarget,
    BeatmapRepository,
)
from osu_server.repositories.interfaces.blob_repository import BlobRepository
from osu_server.repositories.interfaces.channel_repository import ChannelRepository
from osu_server.repositories.interfaces.queries.beatmap_score_listing import (
    BeatmapScoreListingQueryRepository,
)
from osu_server.repositories.interfaces.queries.beatmaps import BeatmapQueryRepository
from osu_server.repositories.interfaces.queries.channels import ChannelQueryRepository
from osu_server.repositories.interfaces.queries.chat import ChatHistoryQueryRepository
from osu_server.repositories.interfaces.queries.roles import RoleQueryRepository
from osu_server.repositories.interfaces.queries.users import UserQueryRepository
from osu_server.repositories.interfaces.replay_repository import ReplayRepository
from osu_server.repositories.interfaces.role_repository import RoleRepository
from osu_server.repositories.interfaces.score_repository import ScoreRepository
from osu_server.repositories.interfaces.session_store import SessionStore
from osu_server.repositories.interfaces.submission_repository import ScoreSubmissionRepository
from osu_server.repositories.interfaces.unit_of_work import UnitOfWorkFactory
from osu_server.repositories.interfaces.user_repository import UserRepository
from osu_server.repositories.memory.beatmap_repository import InMemoryBeatmapRepository
from osu_server.repositories.memory.blob_repository import InMemoryBlobRepository
from osu_server.repositories.memory.channel_repository import InMemoryChannelRepository
from osu_server.repositories.memory.commands.state import InMemoryCommandRepositoryState
from osu_server.repositories.memory.queries.beatmap_score_listing import (
    InMemoryBeatmapScoreListingQueryRepository,
)
from osu_server.repositories.memory.queries.beatmaps import InMemoryBeatmapQueryRepository
from osu_server.repositories.memory.queries.channels import InMemoryChannelQueryRepository
from osu_server.repositories.memory.queries.chat import InMemoryChatHistoryQueryRepository
from osu_server.repositories.memory.queries.roles import InMemoryRoleQueryRepository
from osu_server.repositories.memory.queries.users import InMemoryUserQueryRepository
from osu_server.repositories.memory.replay_repository import InMemoryReplayRepository
from osu_server.repositories.memory.role_repository import InMemoryRoleRepository
from osu_server.repositories.memory.score_repository import InMemoryScoreRepository
from osu_server.repositories.memory.session_store import InMemorySessionStore
from osu_server.repositories.memory.submission_repository import InMemoryScoreSubmissionRepository
from osu_server.repositories.memory.unit_of_work import InMemoryUnitOfWorkFactory
from osu_server.repositories.memory.user_repository import InMemoryUserRepository
from osu_server.repositories.sqlalchemy.beatmap_repository import SQLAlchemyBeatmapRepository
from osu_server.repositories.sqlalchemy.blob_repository import SQLAlchemyBlobRepository
from osu_server.repositories.sqlalchemy.channel_repository import SQLAlchemyChannelRepository
from osu_server.repositories.sqlalchemy.queries.beatmap_score_listing import (
    SQLAlchemyBeatmapScoreListingQueryRepository,
)
from osu_server.repositories.sqlalchemy.queries.beatmaps import SQLAlchemyBeatmapQueryRepository
from osu_server.repositories.sqlalchemy.queries.channels import SQLAlchemyChannelQueryRepository
from osu_server.repositories.sqlalchemy.queries.chat import SQLAlchemyChatHistoryQueryRepository
from osu_server.repositories.sqlalchemy.queries.roles import SQLAlchemyRoleQueryRepository
from osu_server.repositories.sqlalchemy.queries.users import SQLAlchemyUserQueryRepository
from osu_server.repositories.sqlalchemy.replay_repository import SQLAlchemyReplayRepository
from osu_server.repositories.sqlalchemy.role_repository import SQLAlchemyRoleRepository
from osu_server.repositories.sqlalchemy.score_repository import SQLAlchemyScoreRepository
from osu_server.repositories.sqlalchemy.submission_repository import (
    SQLAlchemyScoreSubmissionRepository,
)
from osu_server.repositories.sqlalchemy.unit_of_work import SQLAlchemyUnitOfWork
from osu_server.repositories.sqlalchemy.user_repository import SQLAlchemyUserRepository
from osu_server.repositories.valkey.session_store import ValkeySessionStore
from osu_server.services.auth_service import AuthService
from osu_server.services.bancho_bot.command_service import CommandService
from osu_server.services.bancho_bot.commands import create_builtin_registry
from osu_server.services.beatmap_mirror import (
    BeatmapEligibilityService,
    BeatmapFileProviderService,
    BeatmapMirrorService,
    InMemoryBeatmapMetadataProvider,
    MirrorMetadataProviderService,
    OsuApiMetadataProviderService,
)
from osu_server.services.blob_storage_service import BlobStorageService
from osu_server.services.channel_service import ChannelService
from osu_server.services.commands.chat import (
    JoinChannelUseCase,
    LeaveChannelUseCase,
    PersistChannelMessageUseCase,
    PersistPrivateMessageUseCase,
    SendChannelMessageUseCase,
    SendPrivateMessageUseCase,
)
from osu_server.services.commands.identity import (
    LoginCommandUseCase,
    RefreshRoleAuthorizationCommandUseCase,
    RefreshUserAuthorizationCommandUseCase,
    RegisterUserCommandUseCase,
)
from osu_server.services.commands.scores import ProcessScoreSubmissionUseCase, SubmitScoreUseCase
from osu_server.services.online_users import OnlineUsersService
from osu_server.services.password_service import PasswordService
from osu_server.services.permission_service import PermissionService
from osu_server.services.private_message_service import PrivateMessageService
from osu_server.services.queries.beatmaps import (
    ResolveBeatmapByChecksumQuery,
    ResolveBeatmapByIdQuery,
)
from osu_server.services.queries.chat import (
    ListAutojoinChannelsQuery,
    ListChannelMessagesQuery,
    ListPrivateMessagesQuery,
    ListVisibleChannelsQuery,
    ResolveChannelMessageDeliveryQuery,
    ResolvePrivateMessageTargetQuery,
)
from osu_server.services.queries.identity import (
    ComputePermissionsQueryUseCase,
    ComputeSessionAuthorizationQueryUseCase,
    ListOnlineUsersQueryUseCase,
    SessionCredentialsQueryUseCase,
)
from osu_server.services.queries.scores import BeatmapScoreListingQuery
from osu_server.services.score_authorization_service import ScoreAuthorizationService
from osu_server.services.session_authorization_service import (
    SessionAuthorizationService,
)
from osu_server.transports.stable.bancho.dispatch import PacketDispatcher
from osu_server.transports.stable.bancho.endpoint import BanchoEndpoint
from osu_server.transports.stable.bancho.handlers.chat import ChatHandlers
from osu_server.transports.stable.bancho.handlers.lifecycle import LifecycleHandlers
from osu_server.transports.stable.bancho.listeners import setup_listeners
from osu_server.transports.stable.bancho.workflows.login import LoginWorkflow
from osu_server.transports.stable.bancho.workflows.login_response_builder import (
    LoginResponseBuilder,
)
from osu_server.transports.stable.bancho.workflows.polling import PollingWorkflow
from osu_server.transports.stable.web_legacy.getscores import GetscoresHandler
from osu_server.transports.stable.web_legacy.mappers import (
    GetscoresQueryParser,
    GetscoresStatusMapper,
)
from osu_server.transports.stable.web_legacy.registration import RegistrationHandler
from osu_server.transports.stable.web_legacy.score_submit import ScoreSubmitHandler

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
    memory_state: InMemoryCommandRepositoryState | None = None,
) -> None:
    """Register repository implementations for the current environment."""
    if config.environment == "test":
        state = memory_state or InMemoryCommandRepositoryState()
        container.register_singleton(BlobRepository, InMemoryBlobRepository)
        container.register_singleton(UserRepository, lambda: InMemoryUserRepository(state=state))
        container.register_singleton(RoleRepository, lambda: InMemoryRoleRepository(state=state))
        container.register_singleton(
            ChannelRepository,
            lambda: InMemoryChannelRepository(state=state),
        )
        container.register_singleton(BeatmapRepository, InMemoryBeatmapRepository)
        container.register_singleton(ScoreRepository, InMemoryScoreRepository)
        container.register_singleton(ReplayRepository, InMemoryReplayRepository)
        container.register_singleton(ScoreSubmissionRepository, InMemoryScoreSubmissionRepository)
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
        BeatmapRepository,
        lambda: SQLAlchemyBeatmapRepository(session_factory),
    )
    container.register_singleton(
        ScoreRepository,
        lambda: SQLAlchemyScoreRepository(session_factory),
    )
    container.register_singleton(
        ReplayRepository,
        lambda: SQLAlchemyReplayRepository(session_factory),
    )
    container.register_singleton(
        ScoreSubmissionRepository,
        lambda: SQLAlchemyScoreSubmissionRepository(session_factory),
    )


def _register_unit_of_work_factory(
    container: Container,
    session_factory: async_sessionmaker[AsyncSession],
    memory_state: InMemoryCommandRepositoryState | None,
) -> None:
    """Register command UoW factory for the active persistence backend."""
    if memory_state is not None:
        in_memory_uow_factory = InMemoryUnitOfWorkFactory(memory_state)
        container.register_singleton(UnitOfWorkFactory, lambda: in_memory_uow_factory)
        return

    def create_uow() -> SQLAlchemyUnitOfWork:
        return SQLAlchemyUnitOfWork(session_factory)

    container.register_singleton(UnitOfWorkFactory, lambda: create_uow)


async def _register_query_repositories(
    container: Container,
    session_factory: async_sessionmaker[AsyncSession],
    memory_state: InMemoryCommandRepositoryState | None,
) -> tuple[
    UserQueryRepository,
    RoleQueryRepository,
    ChannelQueryRepository,
    ChatHistoryQueryRepository,
    BeatmapQueryRepository,
    BeatmapScoreListingQueryRepository,
]:
    """Register query repositories for the active persistence backend."""
    if memory_state is not None:
        shared_uow_factory = InMemoryUnitOfWorkFactory(memory_state)
        user_query_repo = InMemoryUserQueryRepository(shared_uow_factory)
        role_query_repo = InMemoryRoleQueryRepository(shared_uow_factory)
        channel_query_repo = InMemoryChannelQueryRepository(shared_uow_factory)
        chat_history_query_repo = InMemoryChatHistoryQueryRepository(shared_uow_factory)
        beatmap_repo = await container.resolve(BeatmapRepository)
        beatmap_query_repo = InMemoryBeatmapQueryRepository(beatmap_repo)
        beatmap_score_listing_query_repo = InMemoryBeatmapScoreListingQueryRepository(
            beatmap_query_repo,
        )
    else:
        user_query_repo = SQLAlchemyUserQueryRepository(session_factory)
        role_query_repo = SQLAlchemyRoleQueryRepository(session_factory)
        channel_query_repo = SQLAlchemyChannelQueryRepository(session_factory)
        chat_history_query_repo = SQLAlchemyChatHistoryQueryRepository(session_factory)
        beatmap_query_repo = SQLAlchemyBeatmapQueryRepository(session_factory)
        beatmap_score_listing_query_repo = SQLAlchemyBeatmapScoreListingQueryRepository(
            session_factory,
        )

    container.register_singleton(UserQueryRepository, lambda: user_query_repo)
    container.register_singleton(RoleQueryRepository, lambda: role_query_repo)
    container.register_singleton(ChannelQueryRepository, lambda: channel_query_repo)
    container.register_singleton(ChatHistoryQueryRepository, lambda: chat_history_query_repo)
    container.register_singleton(BeatmapQueryRepository, lambda: beatmap_query_repo)
    container.register_singleton(
        BeatmapScoreListingQueryRepository,
        lambda: beatmap_score_listing_query_repo,
    )
    return (
        user_query_repo,
        role_query_repo,
        channel_query_repo,
        chat_history_query_repo,
        beatmap_query_repo,
        beatmap_score_listing_query_repo,
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

    memory_command_state = (
        InMemoryCommandRepositoryState() if config.environment == "test" else None
    )

    # -- Repositories (singleton, environment-based switching) ----------------
    _register_repositories(container, config, session_factory, memory_command_state)

    # -- UnitOfWorkFactory (singleton) ----------------------------------------
    _register_unit_of_work_factory(container, session_factory, memory_command_state)

    # -- Query Repositories (singleton) ---------------------------------------
    (
        user_query_repo,
        role_query_repo,
        channel_query_repo,
        chat_history_query_repo,
        beatmap_query_repo,
        beatmap_score_listing_query_repo,
    ) = await _register_query_repositories(
        container,
        session_factory,
        memory_command_state,
    )

    resolve_beatmap_by_id_query = ResolveBeatmapByIdQuery(beatmap_query_repo)
    container.register_singleton(
        ResolveBeatmapByIdQuery,
        lambda: resolve_beatmap_by_id_query,
    )
    resolve_beatmap_by_checksum_query = ResolveBeatmapByChecksumQuery(beatmap_query_repo)
    container.register_singleton(
        ResolveBeatmapByChecksumQuery,
        lambda: resolve_beatmap_by_checksum_query,
    )
    beatmap_score_listing_query = BeatmapScoreListingQuery(beatmap_score_listing_query_repo)
    container.register_singleton(BeatmapScoreListingQuery, lambda: beatmap_score_listing_query)

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
        official_metadata_provider = OsuApiMetadataProviderService(
            client_id=config.beatmap_official_api_client_id,  # pyright: ignore[reportArgumentType]
            client_secret=config.beatmap_official_api_client_secret,  # pyright: ignore[reportArgumentType]
        )
        mirror_metadata_provider = MirrorMetadataProviderService(
            base_urls=config.beatmap_metadata_mirror_base_urls,
        )

    infrastructure_metadata_provider = CompositeBeatmapMetadataProvider(
        official=official_metadata_provider,
        mirror=mirror_metadata_provider,
    )
    container.register_singleton(BeatmapMetadataProvider, lambda: infrastructure_metadata_provider)

    # -- BeatmapFileProvider (singleton) -------------------------------------
    file_provider = BeatmapFileProviderService(
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
    permission_service = PermissionService(role_repo=role_query_repo)
    container.register_singleton(PermissionService, lambda: permission_service)
    compute_permissions_query = ComputePermissionsQueryUseCase(
        permission_service=permission_service,
    )
    container.register_singleton(
        ComputePermissionsQueryUseCase,
        lambda: compute_permissions_query,
    )
    compute_session_authorization_query = ComputeSessionAuthorizationQueryUseCase(
        permission_service=permission_service,
    )
    container.register_singleton(
        ComputeSessionAuthorizationQueryUseCase,
        lambda: compute_session_authorization_query,
    )

    # -- AuthService (singleton) ----------------------------------------------
    uow_factory = await container.resolve(UnitOfWorkFactory)
    auth_service = AuthService(
        uow_factory=uow_factory,
        user_query_repo=user_query_repo,
        role_query_repo=role_query_repo,
        password_service=password_service,
        permission_service=permission_service,
        session_store=session_store,
        system_user_id=BANCHO_BOT_USER_ID,
    )
    container.register_singleton(AuthService, lambda: auth_service)
    login_command = LoginCommandUseCase(auth_service=auth_service)
    container.register_singleton(LoginCommandUseCase, lambda: login_command)
    register_user_command = RegisterUserCommandUseCase(auth_service=auth_service)
    container.register_singleton(RegisterUserCommandUseCase, lambda: register_user_command)

    # -- SessionAuthorizationService (singleton) ---------------------------------
    session_auth_service = SessionAuthorizationService(
        permission_service=permission_service,
        session_store=session_store,
        role_repository=role_query_repo,
    )
    container.register_singleton(
        SessionAuthorizationService,
        lambda: session_auth_service,
    )
    refresh_user_authorization_command = RefreshUserAuthorizationCommandUseCase(
        session_authorization_service=session_auth_service,
    )
    container.register_singleton(
        RefreshUserAuthorizationCommandUseCase,
        lambda: refresh_user_authorization_command,
    )
    refresh_role_authorization_command = RefreshRoleAuthorizationCommandUseCase(
        session_authorization_service=session_auth_service,
    )
    container.register_singleton(
        RefreshRoleAuthorizationCommandUseCase,
        lambda: refresh_role_authorization_command,
    )

    # -- OnlineUsersService (singleton) -----------------------------------------
    online_users = OnlineUsersService(session_store=session_store)
    container.register_singleton(OnlineUsersService, lambda: online_users)
    online_users_query = ListOnlineUsersQueryUseCase(online_users_service=online_users)
    container.register_singleton(ListOnlineUsersQueryUseCase, lambda: online_users_query)

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

    # -- Chat query use-cases (singletons) ------------------------------------
    visible_channels_query = ListVisibleChannelsQuery(
        channel_repository=channel_query_repo,
        channel_state=channel_state,
    )
    autojoin_channels_query = ListAutojoinChannelsQuery(
        channel_repository=channel_query_repo,
        channel_state=channel_state,
    )
    channel_delivery_query = ResolveChannelMessageDeliveryQuery(
        channel_repository=channel_query_repo,
        channel_state=channel_state,
    )
    private_message_target_query = ResolvePrivateMessageTargetQuery(
        user_repository=user_query_repo,
        session_store=session_store,
    )
    list_channel_messages_query = ListChannelMessagesQuery(chat_history_query_repo)
    list_private_messages_query = ListPrivateMessagesQuery(chat_history_query_repo)
    container.register_singleton(ListVisibleChannelsQuery, lambda: visible_channels_query)
    container.register_singleton(ListAutojoinChannelsQuery, lambda: autojoin_channels_query)
    container.register_singleton(
        ResolveChannelMessageDeliveryQuery,
        lambda: channel_delivery_query,
    )
    container.register_singleton(
        ResolvePrivateMessageTargetQuery,
        lambda: private_message_target_query,
    )
    container.register_singleton(
        ListChannelMessagesQuery,
        lambda: list_channel_messages_query,
    )
    container.register_singleton(
        ListPrivateMessagesQuery,
        lambda: list_private_messages_query,
    )

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
    rate_limiter = await container.resolve(RateLimiter)

    # -- Chat command use-cases (singletons) ----------------------------------
    send_channel_message_use_case = SendChannelMessageUseCase(
        channel_delivery_query=channel_delivery_query,
        command_service=command_service,
        session_store=session_store,
        event_bus=eventbus,
        rate_limiter=rate_limiter,
        config=config,
    )
    send_private_message_use_case = SendPrivateMessageUseCase(
        target_query=private_message_target_query,
        command_service=command_service,
        session_store=session_store,
        event_bus=eventbus,
        rate_limiter=rate_limiter,
        config=config,
    )
    join_channel_use_case = JoinChannelUseCase(
        channel_repository=channel_query_repo,
        channel_state=channel_state,
    )
    leave_channel_use_case = LeaveChannelUseCase(channel_state=channel_state)
    persist_channel_message_use_case = PersistChannelMessageUseCase(
        uow_factory=uow_factory,
    )
    persist_private_message_use_case = PersistPrivateMessageUseCase(
        uow_factory=uow_factory,
    )
    container.register_singleton(
        SendChannelMessageUseCase,
        lambda: send_channel_message_use_case,
    )
    container.register_singleton(
        SendPrivateMessageUseCase,
        lambda: send_private_message_use_case,
    )
    container.register_singleton(JoinChannelUseCase, lambda: join_channel_use_case)
    container.register_singleton(LeaveChannelUseCase, lambda: leave_channel_use_case)
    container.register_singleton(
        PersistChannelMessageUseCase,
        lambda: persist_channel_message_use_case,
    )
    container.register_singleton(
        PersistPrivateMessageUseCase,
        lambda: persist_private_message_use_case,
    )

    login_response_builder = LoginResponseBuilder(
        visible_channels_query=visible_channels_query,
        autojoin_channels_query=autojoin_channels_query,
        bot_identity=identity,
    )
    container.register_singleton(LoginResponseBuilder, lambda: login_response_builder)

    login_workflow = LoginWorkflow(
        login_command=login_command,
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

    # -- Handlers → PacketDispatcher ------------------------------------------
    lifecycle_handlers = LifecycleHandlers(
        session_store=session_store,
        event_bus=eventbus,
    )
    chat_handlers = ChatHandlers(
        send_channel_message=send_channel_message_use_case,
        send_private_message=send_private_message_use_case,
        join_channel=join_channel_use_case,
        leave_channel=leave_channel_use_case,
        session_store=session_store,
        packet_queue=packet_queue,
    )
    lifecycle_handlers.register_all(packet_dispatcher)
    chat_handlers.register_all(packet_dispatcher)

    # -- Listeners → EventBus --------------------------------------------------
    setup_listeners(eventbus, packet_queue, online_users_query, broker, channel_state)

    # -- RegistrationHandler (singleton) --------------------------------------
    registration_handler = RegistrationHandler(register_user_command=register_user_command)
    container.register_singleton(RegistrationHandler, lambda: registration_handler)

    # -- SessionCredentialsQueryUseCase (singleton) ---------------------------
    session_credentials_query = SessionCredentialsQueryUseCase(
        user_repository=user_query_repo,
        password_service=password_service,
        session_store=session_store,
    )
    container.register_singleton(SessionCredentialsQueryUseCase, lambda: session_credentials_query)

    # -- Getscores service / endpoint (singletons) ----------------------------
    getscores_parser = GetscoresQueryParser()
    container.register_singleton(GetscoresQueryParser, lambda: getscores_parser)
    getscores_status_mapper = GetscoresStatusMapper()
    container.register_singleton(GetscoresStatusMapper, lambda: getscores_status_mapper)

    getscores_handler = GetscoresHandler(
        auth_query=session_credentials_query,
        getscores_parser=getscores_parser,
        getscores_query=beatmap_score_listing_query,
        status_mapper=getscores_status_mapper,
    )
    container.register_singleton(GetscoresHandler, lambda: getscores_handler)

    # -- ProcessScoreSubmissionUseCase (singleton) -----------------------------------
    score_auth_service = ScoreAuthorizationService(
        user_repo=user_repo,
        password_service=password_service,
        session_store=session_store,
    )
    container.register_singleton(ScoreAuthorizationService, lambda: score_auth_service)
    score_crypto_service = ScoreCryptoService()
    container.register_singleton(ScoreCryptoService, lambda: score_crypto_service)
    submit_score_command = SubmitScoreUseCase(unit_of_work_factory=uow_factory)
    container.register_singleton(SubmitScoreUseCase, lambda: submit_score_command)

    process_score_submission = ProcessScoreSubmissionUseCase(
        submit_score_use_case=submit_score_command,
        replay_blob_storage=blob_storage_service,
        payload_decryptor=score_crypto_service,
        auth_service=score_auth_service,
        beatmap_resolver=mirror_service,  # Pass the entire service, not just the method
    )
    container.register_singleton(
        ProcessScoreSubmissionUseCase,
        lambda: process_score_submission,
    )

    # -- ScoreSubmitHandler (singleton) ---------------------------------------
    score_submit_handler = ScoreSubmitHandler(
        submit_score_command=process_score_submission,
        limits=MultipartLimits(
            total_body_size=config.max_request_body_size,
            replay_size=config.score_submit_max_replay_size,
            text_field_size=config.score_submit_max_text_field_size,
        ),
    )
    container.register_singleton(ScoreSubmitHandler, lambda: score_submit_handler)
