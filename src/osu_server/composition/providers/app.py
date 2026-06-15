"""App process provider set."""

from __future__ import annotations

from dataclasses import dataclass
from typing import final

from dishka import Provider, Scope
from taskiq import AsyncBroker

from osu_server.config import AppConfig
from osu_server.domain.beatmaps import BeatmapFetchTarget, BeatmapFreshnessPolicy
from osu_server.domain.identity.system_users import (
    BANCHO_BOT_USER_ID,
    SystemUserIdentity,
    create_bancho_bot_identity,
)
from osu_server.infrastructure.country.interfaces import CountryResolver
from osu_server.infrastructure.crypto import ScoreCryptoService
from osu_server.infrastructure.messaging.interfaces import EventBus
from osu_server.infrastructure.security.hibp import HIBPClient
from osu_server.infrastructure.state.interfaces.channel_state_store import ChannelStateStore
from osu_server.infrastructure.state.interfaces.packet_queue import PacketQueue
from osu_server.infrastructure.state.interfaces.rate_limiter import RateLimiter
from osu_server.repositories.interfaces.queries.beatmaps import BeatmapQueryRepository
from osu_server.repositories.interfaces.queries.roles import RoleQueryRepository
from osu_server.repositories.interfaces.queries.users import UserQueryRepository
from osu_server.repositories.interfaces.session_store import SessionStore
from osu_server.repositories.interfaces.unit_of_work import UnitOfWorkFactory
from osu_server.services.commands.chat import (
    JoinChannelUseCase,
    LeaveChannelUseCase,
    SendChannelMessageUseCase,
    SendPrivateMessageUseCase,
)
from osu_server.services.commands.chat.bancho_bot.command_service import CommandService
from osu_server.services.commands.chat.bancho_bot.commands import create_builtin_registry
from osu_server.services.commands.identity import (
    LoginCommandUseCase,
    RefreshRoleAuthorizationCommandUseCase,
    RefreshUserAuthorizationCommandUseCase,
    RegisterUserCommandUseCase,
)
from osu_server.services.commands.identity.auth_service import AuthService
from osu_server.services.commands.identity.session_authorization_service import (
    SessionAuthorizationService,
)
from osu_server.services.commands.scores import ProcessScoreSubmissionUseCase, SubmitScoreUseCase
from osu_server.services.commands.scores.authorization import ScoreAuthorizationService
from osu_server.services.commands.storage.blob_storage import BlobStorageService
from osu_server.services.queries.beatmaps.mirror import (
    BeatmapEligibilityService,
    BeatmapMirrorService,
)
from osu_server.services.queries.chat import (
    ListAutojoinChannelsQuery,
    ListVisibleChannelsQuery,
    ResolveChannelMessageDeliveryQuery,
    ResolvePrivateMessageTargetQuery,
)
from osu_server.services.queries.chat.private_message_service import PrivateMessageService
from osu_server.services.queries.identity import (
    ComputePermissionsQueryUseCase,
    ComputeSessionAuthorizationQueryUseCase,
    ListOnlineUsersQueryUseCase,
    SessionCredentialsQueryUseCase,
)
from osu_server.services.queries.identity.online_users_service import OnlineUsersService
from osu_server.services.queries.identity.password_service import PasswordService
from osu_server.services.queries.identity.permission_service import PermissionService
from osu_server.services.queries.scores import BeatmapScoreListingQuery
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
    StableScorePayloadParser,
    StableScoreSubmitMapper,
)
from osu_server.transports.stable.web_legacy.registration import RegistrationHandler
from osu_server.transports.stable.web_legacy.score_submit import ScoreSubmitHandler

# Dishka evaluates provider parameter annotations at runtime.
_DISHKA_RUNTIME_HINTS = (
    AppConfig,
    AsyncBroker,
    BeatmapFetchTarget,
    BeatmapFreshnessPolicy,
    BeatmapQueryRepository,
    BlobStorageService,
    ChannelStateStore,
    CountryResolver,
    EventBus,
    HIBPClient,
    PacketQueue,
    RateLimiter,
    RoleQueryRepository,
    ScoreCryptoService,
    SessionStore,
    UnitOfWorkFactory,
    UserQueryRepository,
    BeatmapScoreListingQuery,
)


@dataclass(frozen=True, slots=True)
class AppProviderGraph:
    """Marker resolved from the app dependency graph."""

    name: str = "app"


@dataclass(frozen=True, slots=True)
class AppEventListeners:
    """Marker proving app event listeners were registered."""

    registered: bool = True


@final
class AppProviderSet(Provider):
    """Providers owned by the app process graph."""

    def __init__(self) -> None:
        super().__init__(scope=Scope.APP)
        for source, provides in (
            (self.app_provider_graph, AppProviderGraph),
            (self.system_user_identity, SystemUserIdentity),
            (self.password_service, PasswordService),
            (self.permission_service, PermissionService),
            (self.compute_permissions_query, ComputePermissionsQueryUseCase),
            (self.compute_session_authorization_query, ComputeSessionAuthorizationQueryUseCase),
            (self.auth_service, AuthService),
            (self.login_command, LoginCommandUseCase),
            (self.register_user_command, RegisterUserCommandUseCase),
            (self.session_authorization_service, SessionAuthorizationService),
            (self.refresh_user_authorization_command, RefreshUserAuthorizationCommandUseCase),
            (self.refresh_role_authorization_command, RefreshRoleAuthorizationCommandUseCase),
            (self.online_users_service, OnlineUsersService),
            (self.online_users_query, ListOnlineUsersQueryUseCase),
            (self.private_message_target_query, ResolvePrivateMessageTargetQuery),
            (self.private_message_service, PrivateMessageService),
            (self.command_service, CommandService),
            (self.send_channel_message_use_case, SendChannelMessageUseCase),
            (self.send_private_message_use_case, SendPrivateMessageUseCase),
            (self.beatmap_mirror_service, BeatmapMirrorService),
            (self.login_response_builder, LoginResponseBuilder),
            (self.login_workflow, LoginWorkflow),
            (self.lifecycle_handlers, LifecycleHandlers),
            (self.chat_handlers, ChatHandlers),
            (self.app_event_listeners, AppEventListeners),
            (self.packet_dispatcher, PacketDispatcher),
            (self.polling_workflow, PollingWorkflow),
            (self.bancho_endpoint, BanchoEndpoint),
            (self.registration_handler, RegistrationHandler),
            (self.session_credentials_query, SessionCredentialsQueryUseCase),
            (self.getscores_parser, GetscoresQueryParser),
            (self.getscores_status_mapper, GetscoresStatusMapper),
            (self.getscores_handler, GetscoresHandler),
            (self.score_authorization_service, ScoreAuthorizationService),
            (self.submit_score_use_case, SubmitScoreUseCase),
            (self.stable_score_payload_parser, StableScorePayloadParser),
            (self.process_score_submission_use_case, ProcessScoreSubmissionUseCase),
            (self.score_submit_handler, ScoreSubmitHandler),
        ):
            _ = self.provide(source, provides=provides, scope=Scope.APP)

    def app_provider_graph(self) -> AppProviderGraph:
        return AppProviderGraph()

    async def system_user_identity(
        self,
        config: AppConfig,
        uow_factory: UnitOfWorkFactory,
    ) -> SystemUserIdentity:
        identity = create_bancho_bot_identity(config.bancho_bot_username)
        try:
            async with uow_factory() as uow:
                await uow.users.sync_system_user(identity)
                await uow.commit()
        except ValueError as exc:
            msg = f"BanchoBot system user sync failed: {exc}"
            raise RuntimeError(msg) from exc
        return identity

    def password_service(
        self,
        hibp_client: HIBPClient,
        config: AppConfig,
    ) -> PasswordService:
        return PasswordService(
            hibp_client=hibp_client,
            banned_passwords=config.banned_passwords,
        )

    def permission_service(self, role_repo: RoleQueryRepository) -> PermissionService:
        return PermissionService(role_repo=role_repo)

    def compute_permissions_query(
        self,
        permission_service: PermissionService,
    ) -> ComputePermissionsQueryUseCase:
        return ComputePermissionsQueryUseCase(permission_service=permission_service)

    def compute_session_authorization_query(
        self,
        permission_service: PermissionService,
    ) -> ComputeSessionAuthorizationQueryUseCase:
        return ComputeSessionAuthorizationQueryUseCase(
            permission_service=permission_service,
        )

    def auth_service(
        self,
        uow_factory: UnitOfWorkFactory,
        user_query_repo: UserQueryRepository,
        role_query_repo: RoleQueryRepository,
        password_service: PasswordService,
        permission_service: PermissionService,
        session_store: SessionStore,
    ) -> AuthService:
        return AuthService(
            uow_factory=uow_factory,
            user_query_repo=user_query_repo,
            role_query_repo=role_query_repo,
            password_service=password_service,
            permission_service=permission_service,
            session_store=session_store,
            system_user_id=BANCHO_BOT_USER_ID,
        )

    def login_command(self, auth_service: AuthService) -> LoginCommandUseCase:
        return LoginCommandUseCase(auth_service=auth_service)

    def register_user_command(self, auth_service: AuthService) -> RegisterUserCommandUseCase:
        return RegisterUserCommandUseCase(auth_service=auth_service)

    def session_authorization_service(
        self,
        permission_service: PermissionService,
        session_store: SessionStore,
        role_repository: RoleQueryRepository,
    ) -> SessionAuthorizationService:
        return SessionAuthorizationService(
            permission_service=permission_service,
            session_store=session_store,
            role_repository=role_repository,
        )

    def refresh_user_authorization_command(
        self,
        session_authorization_service: SessionAuthorizationService,
    ) -> RefreshUserAuthorizationCommandUseCase:
        return RefreshUserAuthorizationCommandUseCase(
            session_authorization_service=session_authorization_service,
        )

    def refresh_role_authorization_command(
        self,
        session_authorization_service: SessionAuthorizationService,
    ) -> RefreshRoleAuthorizationCommandUseCase:
        return RefreshRoleAuthorizationCommandUseCase(
            session_authorization_service=session_authorization_service,
        )

    def online_users_service(self, session_store: SessionStore) -> OnlineUsersService:
        return OnlineUsersService(session_store=session_store)

    def online_users_query(
        self,
        online_users_service: OnlineUsersService,
    ) -> ListOnlineUsersQueryUseCase:
        return ListOnlineUsersQueryUseCase(online_users_service=online_users_service)

    def private_message_target_query(
        self,
        user_repository: UserQueryRepository,
        session_store: SessionStore,
    ) -> ResolvePrivateMessageTargetQuery:
        return ResolvePrivateMessageTargetQuery(
            user_repository=user_repository,
            session_store=session_store,
        )

    def private_message_service(
        self,
        user_repo: UserQueryRepository,
        session_store: SessionStore,
    ) -> PrivateMessageService:
        return PrivateMessageService(user_repo=user_repo, session_store=session_store)

    def command_service(self) -> CommandService:
        return CommandService(create_builtin_registry())

    def send_channel_message_use_case(
        self,
        channel_delivery_query: ResolveChannelMessageDeliveryQuery,
        command_service: CommandService,
        session_store: SessionStore,
        event_bus: EventBus,
        rate_limiter: RateLimiter,
        config: AppConfig,
    ) -> SendChannelMessageUseCase:
        return SendChannelMessageUseCase(
            channel_delivery_query=channel_delivery_query,
            command_service=command_service,
            session_store=session_store,
            event_bus=event_bus,
            rate_limiter=rate_limiter,
            config=config,
        )

    def send_private_message_use_case(
        self,
        target_query: ResolvePrivateMessageTargetQuery,
        command_service: CommandService,
        session_store: SessionStore,
        event_bus: EventBus,
        rate_limiter: RateLimiter,
        config: AppConfig,
    ) -> SendPrivateMessageUseCase:
        return SendPrivateMessageUseCase(
            target_query=target_query,
            command_service=command_service,
            session_store=session_store,
            event_bus=event_bus,
            rate_limiter=rate_limiter,
            config=config,
        )

    def beatmap_mirror_service(
        self,
        repository: BeatmapQueryRepository,
        eligibility_service: BeatmapEligibilityService,
        freshness_policy: BeatmapFreshnessPolicy,
        broker: AsyncBroker,
        config: AppConfig,
    ) -> BeatmapMirrorService:
        return BeatmapMirrorService(
            repository=repository,
            eligibility_service=eligibility_service,
            freshness_policy=freshness_policy,
            mirror_trust_enabled=config.beatmap_mirror_trust_policy == "trusted",
            official_sources_available=config.beatmap_official_sources_enabled,
            enqueue_refresh=lambda target: enqueue_beatmap_fetch(broker, target),
        )

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

    def lifecycle_handlers(
        self,
        session_store: SessionStore,
        event_bus: EventBus,
    ) -> LifecycleHandlers:
        return LifecycleHandlers(session_store=session_store, event_bus=event_bus)

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

    def app_event_listeners(
        self,
        event_bus: EventBus,
        packet_queue: PacketQueue,
        online_users_query: ListOnlineUsersQueryUseCase,
        broker: AsyncBroker,
        channel_state: ChannelStateStore,
    ) -> AppEventListeners:
        setup_listeners(event_bus, packet_queue, online_users_query, broker, channel_state)
        return AppEventListeners()

    def packet_dispatcher(
        self,
        lifecycle_handlers: LifecycleHandlers,
        chat_handlers: ChatHandlers,
        listeners: AppEventListeners,
    ) -> PacketDispatcher:
        _ = listeners
        dispatcher = PacketDispatcher()
        lifecycle_handlers.register_all(dispatcher)
        chat_handlers.register_all(dispatcher)
        return dispatcher

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

    def bancho_endpoint(
        self,
        login_workflow: LoginWorkflow,
        polling_workflow: PollingWorkflow,
    ) -> BanchoEndpoint:
        return BanchoEndpoint(
            login_workflow=login_workflow,
            polling_workflow=polling_workflow,
        )

    def registration_handler(
        self,
        register_user_command: RegisterUserCommandUseCase,
    ) -> RegistrationHandler:
        return RegistrationHandler(register_user_command=register_user_command)

    def session_credentials_query(
        self,
        user_repository: UserQueryRepository,
        password_service: PasswordService,
        session_store: SessionStore,
    ) -> SessionCredentialsQueryUseCase:
        return SessionCredentialsQueryUseCase(
            user_repository=user_repository,
            password_service=password_service,
            session_store=session_store,
        )

    def getscores_parser(self) -> GetscoresQueryParser:
        return GetscoresQueryParser()

    def getscores_status_mapper(self) -> GetscoresStatusMapper:
        return GetscoresStatusMapper()

    def getscores_handler(
        self,
        auth_query: SessionCredentialsQueryUseCase,
        getscores_parser: GetscoresQueryParser,
        getscores_query: BeatmapScoreListingQuery,
        status_mapper: GetscoresStatusMapper,
    ) -> GetscoresHandler:
        return GetscoresHandler(
            auth_query=auth_query,
            getscores_parser=getscores_parser,
            getscores_query=getscores_query,
            status_mapper=status_mapper,
        )

    def score_authorization_service(
        self,
        user_repo: UserQueryRepository,
        password_service: PasswordService,
        session_store: SessionStore,
    ) -> ScoreAuthorizationService:
        return ScoreAuthorizationService(
            user_repo=user_repo,
            password_service=password_service,
            session_store=session_store,
        )

    def submit_score_use_case(self, uow_factory: UnitOfWorkFactory) -> SubmitScoreUseCase:
        return SubmitScoreUseCase(unit_of_work_factory=uow_factory)

    def stable_score_payload_parser(self) -> StableScorePayloadParser:
        return StableScorePayloadParser()

    def process_score_submission_use_case(
        self,
        submit_score_use_case: SubmitScoreUseCase,
        replay_blob_storage: BlobStorageService,
        payload_decryptor: ScoreCryptoService,
        payload_parser: StableScorePayloadParser,
        auth_service: ScoreAuthorizationService,
        beatmap_resolver: BeatmapMirrorService,
    ) -> ProcessScoreSubmissionUseCase:
        return ProcessScoreSubmissionUseCase(
            submit_score_use_case=submit_score_use_case,
            replay_blob_storage=replay_blob_storage,
            payload_decryptor=payload_decryptor,
            payload_parser=payload_parser,
            auth_service=auth_service,
            beatmap_resolver=beatmap_resolver,
        )

    def score_submit_handler(
        self,
        submit_score_command: ProcessScoreSubmissionUseCase,
        mapper: StableScoreSubmitMapper,
    ) -> ScoreSubmitHandler:
        return ScoreSubmitHandler(
            submit_score_command=submit_score_command,
            mapper=mapper,
        )


async def enqueue_beatmap_fetch(broker: AsyncBroker, target: BeatmapFetchTarget) -> None:
    """Enqueue the worker job matching a beatmap fetch target."""
    if target.target_type.startswith("file:"):
        task_name = "fetch_beatmap_file"
    else:
        task_name = "fetch_beatmap_metadata"
    task = broker.find_task(task_name)
    if task is None:
        return

    _ = await task.kiq(target.target_type, target.target_key)
