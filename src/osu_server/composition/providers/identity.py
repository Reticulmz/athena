"""App-only identity providers."""

from __future__ import annotations

from typing import final

from dishka import Provider, Scope

from osu_server.composition.providers._dishka import provide
from osu_server.config import AppConfig
from osu_server.domain.identity.system_users import (
    BANCHO_BOT_USER_ID,
    SystemUserIdentity,
    create_bancho_bot_identity,
)
from osu_server.infrastructure.security.hibp import HIBPClient
from osu_server.repositories.interfaces.queries.roles import RoleQueryRepository
from osu_server.repositories.interfaces.queries.users import UserQueryRepository
from osu_server.repositories.interfaces.session_store import SessionStore
from osu_server.repositories.interfaces.unit_of_work import UnitOfWorkFactory
from osu_server.services.commands.identity import (
    ChangeUserPasswordCommandUseCase,
    LoginCommandUseCase,
    RefreshRoleAuthorizationCommandUseCase,
    RefreshUserAuthorizationCommandUseCase,
    RegisterUserCommandUseCase,
)
from osu_server.services.commands.identity.auth_service import AuthService
from osu_server.services.commands.identity.session_authorization_service import (
    SessionAuthorizationService,
)
from osu_server.services.queries.identity import (
    ComputePermissionsQueryUseCase,
    ComputeSessionAuthorizationQueryUseCase,
    ListOnlineUsersQueryUseCase,
    SessionCredentialsQueryUseCase,
)
from osu_server.services.queries.identity.online_users_service import OnlineUsersService
from osu_server.services.queries.identity.password_service import PasswordService
from osu_server.services.queries.identity.permission_service import PermissionService

_DISHKA_RUNTIME_HINTS = (
    AppConfig,
    HIBPClient,
    RoleQueryRepository,
    SessionStore,
    UnitOfWorkFactory,
    UserQueryRepository,
)


@final
class IdentityProviderSet(Provider):
    """Providers for app identity, authentication, and authorization workflows."""

    scope = Scope.APP

    @provide
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

    @provide
    def password_service(
        self,
        hibp_client: HIBPClient,
        config: AppConfig,
    ) -> PasswordService:
        return PasswordService(
            hibp_client=hibp_client,
            banned_passwords=config.banned_passwords,
        )

    @provide
    def permission_service(self, role_repo: RoleQueryRepository) -> PermissionService:
        return PermissionService(role_repo=role_repo)

    @provide
    def compute_permissions_query(
        self,
        permission_service: PermissionService,
    ) -> ComputePermissionsQueryUseCase:
        return ComputePermissionsQueryUseCase(permission_service=permission_service)

    @provide
    def compute_session_authorization_query(
        self,
        permission_service: PermissionService,
    ) -> ComputeSessionAuthorizationQueryUseCase:
        return ComputeSessionAuthorizationQueryUseCase(
            permission_service=permission_service,
        )

    @provide
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

    @provide
    def login_command(self, auth_service: AuthService) -> LoginCommandUseCase:
        return LoginCommandUseCase(auth_service=auth_service)

    @provide
    def register_user_command(self, auth_service: AuthService) -> RegisterUserCommandUseCase:
        return RegisterUserCommandUseCase(auth_service=auth_service)

    @provide
    def change_user_password_command(
        self,
        uow_factory: UnitOfWorkFactory,
        user_query_repo: UserQueryRepository,
        password_service: PasswordService,
    ) -> ChangeUserPasswordCommandUseCase:
        return ChangeUserPasswordCommandUseCase(
            uow_factory=uow_factory,
            user_query_repository=user_query_repo,
            password_service=password_service,
            system_user_id=BANCHO_BOT_USER_ID,
        )

    @provide
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

    @provide
    def refresh_user_authorization_command(
        self,
        session_authorization_service: SessionAuthorizationService,
    ) -> RefreshUserAuthorizationCommandUseCase:
        return RefreshUserAuthorizationCommandUseCase(
            session_authorization_service=session_authorization_service,
        )

    @provide
    def refresh_role_authorization_command(
        self,
        session_authorization_service: SessionAuthorizationService,
    ) -> RefreshRoleAuthorizationCommandUseCase:
        return RefreshRoleAuthorizationCommandUseCase(
            session_authorization_service=session_authorization_service,
        )

    @provide
    def online_users_service(self, session_store: SessionStore) -> OnlineUsersService:
        return OnlineUsersService(session_store=session_store)

    @provide
    def online_users_query(
        self,
        online_users_service: OnlineUsersService,
    ) -> ListOnlineUsersQueryUseCase:
        return ListOnlineUsersQueryUseCase(online_users_service=online_users_service)

    @provide
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
