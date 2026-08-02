"""app graph専用のidentity providerを定義する.

このmoduleは認証, 認可, friend関係のuse caseをDishkaへ配線する.
worker graphには含めず, 永続化とsession stateの具体的な実装は注入されたportへ委譲する.
"""

from __future__ import annotations

from typing import final

from dishka import Provider, Scope

from osu_server.composition.providers._dishka import provide
from osu_server.config import AppConfig
from osu_server.domain.identity.friends import FriendableSystemUserCatalog
from osu_server.domain.identity.system_users import (
    BANCHO_BOT_USER_ID,
    SystemUserIdentity,
    create_bancho_bot_identity,
)
from osu_server.infrastructure.security.hibp import HIBPClient
from osu_server.repositories.interfaces.queries.friends import (
    FriendRelationshipQueryRepository,
)
from osu_server.repositories.interfaces.queries.roles import RoleQueryRepository
from osu_server.repositories.interfaces.queries.users import UserQueryRepository
from osu_server.repositories.interfaces.session_store import SessionStore
from osu_server.repositories.interfaces.unit_of_work import UnitOfWorkFactory
from osu_server.services.commands.identity import (
    AddFriendUseCase,
    ChangeUserPasswordCommandUseCase,
    ChangeUserRoleCommandUseCase,
    LoginCommandUseCase,
    RefreshRoleAuthorizationCommandUseCase,
    RefreshUserAuthorizationCommandUseCase,
    RegisterUserCommandUseCase,
    RemoveFriendUseCase,
    UpdateFriendOnlyDmUseCase,
)
from osu_server.services.commands.identity.auth_service import AuthService
from osu_server.services.commands.identity.session_authorization_service import (
    SessionAuthorizationService,
)
from osu_server.services.queries.identity import (
    CheckFriendRelationshipQuery,
    ComputePermissionsQueryUseCase,
    ComputeSessionAuthorizationQueryUseCase,
    GetActiveSessionsByUserIdsQueryUseCase,
    GetFriendEligibleUserIdsQuery,
    ListActiveSessionsQueryUseCase,
    ListFriendIdsQuery,
    SessionCredentialsQueryUseCase,
)
from osu_server.services.queries.identity.password_service import PasswordService
from osu_server.services.queries.identity.permission_service import PermissionService
from osu_server.shared.ports import (
    BeatmapLeaderboardRebuildWorkerWake,
)

_DISHKA_RUNTIME_HINTS = (
    AppConfig,
    FriendRelationshipQueryRepository,
    HIBPClient,
    BeatmapLeaderboardRebuildWorkerWake,
    RoleQueryRepository,
    SessionStore,
    UnitOfWorkFactory,
    UserQueryRepository,
)


@final
class IdentityProviderSet(Provider):
    """app graphのidentity認証/認可依存を提供する.

    Attributes:
        scope (Scope): app processの生存期間と一致するDishka scope.
    """

    scope = Scope.APP

    @provide
    async def system_user_identity(
        self,
        config: AppConfig,
        uow_factory: UnitOfWorkFactory,
    ) -> SystemUserIdentity:
        """BanchoBotのsystem identityを永続化層と同期して提供する.

        Args:
            config (AppConfig): BanchoBotの表示名を含むruntime設定.
            uow_factory (UnitOfWorkFactory): system user同期とcommitに使うtransaction factory.

        Returns:
            SystemUserIdentity: 設定されたBanchoBotのcanonical identity.

        Raises:
            RuntimeError: system user同期がValueErrorで失敗した場合.
        """
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
        """漏洩password照会と禁止password集合を使うserviceを提供する.

        Args:
            hibp_client (HIBPClient): password漏洩確認を行うHTTP adapter.
            config (AppConfig): server固有の禁止passwordを持つruntime設定.

        Returns:
            PasswordService: 登録とpassword変更で共有するpassword検証service.
        """
        return PasswordService(
            hibp_client=hibp_client,
            banned_passwords=config.banned_passwords,
        )

    @provide
    def friendable_system_user_catalog(
        self,
        system_user_identity: SystemUserIdentity,
    ) -> FriendableSystemUserCatalog:
        """friend操作で特別扱いするsystem user catalogを提供する.

        Args:
            system_user_identity (SystemUserIdentity): 同期済みBanchoBot identity.

        Returns:
            FriendableSystemUserCatalog: BanchoBotをfriend候補として扱うcatalog.
        """
        return FriendableSystemUserCatalog.with_bancho_bot(system_user_identity)

    @provide
    def permission_service(self, role_repo: RoleQueryRepository) -> PermissionService:
        """role読み取りportを使うpermission計算serviceを提供する.

        Args:
            role_repo (RoleQueryRepository): roleとprivilegeを読み取るquery repository.

        Returns:
            PermissionService: roleからserver-side permissionを導出するservice.
        """
        return PermissionService(role_repo=role_repo)

    @provide
    def compute_permissions_query(
        self,
        permission_service: PermissionService,
    ) -> ComputePermissionsQueryUseCase:
        """permission計算query use caseを提供する.

        Args:
            permission_service (PermissionService): roleのpermissionを計算するservice.

        Returns:
            ComputePermissionsQueryUseCase: userのpermission snapshotを返すread use case.
        """
        return ComputePermissionsQueryUseCase(permission_service=permission_service)

    @provide
    def compute_session_authorization_query(
        self,
        permission_service: PermissionService,
    ) -> ComputeSessionAuthorizationQueryUseCase:
        """Session authorization snapshot計算query use caseを提供する.

        Args:
            permission_service (PermissionService): roleのpermissionを計算するservice.

        Returns:
            ComputeSessionAuthorizationQueryUseCase: session用authorization snapshotを返すuse case.
        """
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
        """Identity mutationに必要な認証serviceを提供する.

        Args:
            uow_factory (UnitOfWorkFactory): identity mutationをcommitするfactory.
            user_query_repo (UserQueryRepository): user credentialを読み取るquery repository.
            role_query_repo (RoleQueryRepository): user roleを読み取るquery repository.
            password_service (PasswordService): password検証とhash処理を行うservice.
            permission_service (PermissionService): roleからsession permissionを導出するservice.
            session_store (SessionStore): active sessionを保持するstate port.

        Returns:
            AuthService: login, registration, password変更で共有する認証service.
        """
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
        """Login command use caseを提供する.

        Args:
            auth_service (AuthService): credentialとsessionを扱う認証service.

        Returns:
            LoginCommandUseCase: login mutationを実行するuse case.
        """
        return LoginCommandUseCase(auth_service=auth_service)

    @provide
    def register_user_command(self, auth_service: AuthService) -> RegisterUserCommandUseCase:
        """user登録command use caseを提供する.

        Args:
            auth_service (AuthService): credentialとsessionを扱う認証service.

        Returns:
            RegisterUserCommandUseCase: user registration mutationを実行するuse case.
        """
        return RegisterUserCommandUseCase(auth_service=auth_service)

    @provide
    def add_friend_command(
        self,
        uow_factory: UnitOfWorkFactory,
        system_user_catalog: FriendableSystemUserCatalog,
    ) -> AddFriendUseCase:
        """friend関係追加command use caseを提供する.

        Args:
            uow_factory (UnitOfWorkFactory): friend関係mutationをcommitするtransaction factory.
            system_user_catalog (FriendableSystemUserCatalog): special system userの許可を
                判定するcatalog.

        Returns:
            AddFriendUseCase: friend関係を追加するuse case.
        """
        return AddFriendUseCase(
            uow_factory=uow_factory,
            system_user_catalog=system_user_catalog,
        )

    @provide
    def remove_friend_command(self, uow_factory: UnitOfWorkFactory) -> RemoveFriendUseCase:
        """friend関係削除command use caseを提供する.

        Args:
            uow_factory (UnitOfWorkFactory): friend関係mutationをcommitするtransaction factory.

        Returns:
            RemoveFriendUseCase: friend関係を削除するuse case.
        """
        return RemoveFriendUseCase(uow_factory=uow_factory)

    @provide
    def update_friend_only_dm_command(
        self,
        session_store: SessionStore,
    ) -> UpdateFriendOnlyDmUseCase:
        """friend-only DM設定更新use caseを提供する.

        Args:
            session_store (SessionStore): 更新対象のsession authorizationを保持するstate port.

        Returns:
            UpdateFriendOnlyDmUseCase: DM受信制限を更新するuse case.
        """
        return UpdateFriendOnlyDmUseCase(session_store=session_store)

    @provide
    def change_user_password_command(
        self,
        uow_factory: UnitOfWorkFactory,
        user_query_repo: UserQueryRepository,
        password_service: PasswordService,
    ) -> ChangeUserPasswordCommandUseCase:
        """User password変更command use caseを提供する.

        Args:
            uow_factory (UnitOfWorkFactory): password mutationをcommitするtransaction factory.
            user_query_repo (UserQueryRepository): 対象userを読み取るquery repository.
            password_service (PasswordService): new passwordを検証してhash化するservice.

        Returns:
            ChangeUserPasswordCommandUseCase: BanchoBot以外のpasswordを変更するuse case.
        """
        return ChangeUserPasswordCommandUseCase(
            uow_factory=uow_factory,
            user_query_repository=user_query_repo,
            password_service=password_service,
            system_user_id=BANCHO_BOT_USER_ID,
        )

    @provide
    def change_user_role_command(
        self,
        uow_factory: UnitOfWorkFactory,
        session_authorization_service: SessionAuthorizationService,
        leaderboard_rebuild_wake: BeatmapLeaderboardRebuildWorkerWake,
    ) -> ChangeUserRoleCommandUseCase:
        """User role変更command use caseを提供する.

        Args:
            uow_factory (UnitOfWorkFactory): role mutationをcommitするtransaction factory.
            session_authorization_service (SessionAuthorizationService): active session
                authorizationを更新するservice.
            leaderboard_rebuild_wake (BeatmapLeaderboardRebuildWorkerWake): leaderboard
                再構築jobを起動するport.

        Returns:
            ChangeUserRoleCommandUseCase: role変更後のauthorization refreshを実行するuse case.
        """
        return ChangeUserRoleCommandUseCase(
            uow_factory=uow_factory,
            session_authorization_service=session_authorization_service,
            leaderboard_rebuild_wake=leaderboard_rebuild_wake,
            system_user_id=BANCHO_BOT_USER_ID,
        )

    @provide
    def session_authorization_service(
        self,
        permission_service: PermissionService,
        session_store: SessionStore,
        role_repository: RoleQueryRepository,
    ) -> SessionAuthorizationService:
        """Active sessionのauthorizationを更新するserviceを提供する.

        Args:
            permission_service (PermissionService): roleのpermissionを計算するservice.
            session_store (SessionStore): refresh対象のsessionを保持するstate port.
            role_repository (RoleQueryRepository): roleの最新定義を読み取るquery repository.

        Returns:
            SessionAuthorizationService: userまたはrole単位のauthorization refreshを行うservice.
        """
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
        """user単位のsession authorization refresh commandを提供する.

        Args:
            session_authorization_service (SessionAuthorizationService): active user sessionを
                更新するservice.

        Returns:
            RefreshUserAuthorizationCommandUseCase: userの全active sessionをrefreshするuse case.
        """
        return RefreshUserAuthorizationCommandUseCase(
            session_authorization_service=session_authorization_service,
        )

    @provide
    def refresh_role_authorization_command(
        self,
        session_authorization_service: SessionAuthorizationService,
    ) -> RefreshRoleAuthorizationCommandUseCase:
        """role単位のsession authorization refresh commandを提供する.

        Args:
            session_authorization_service (SessionAuthorizationService): active role sessionを
                更新するservice.

        Returns:
            RefreshRoleAuthorizationCommandUseCase: roleのactive sessionをrefreshするuse case.
        """
        return RefreshRoleAuthorizationCommandUseCase(
            session_authorization_service=session_authorization_service,
        )

    @provide
    def active_sessions_query(
        self,
        session_store: SessionStore,
    ) -> ListActiveSessionsQueryUseCase:
        """Active session一覧query use caseを提供する.

        Args:
            session_store (SessionStore): active sessionを読み取るstate port.

        Returns:
            ListActiveSessionsQueryUseCase: active session一覧を返すread use case.
        """
        return ListActiveSessionsQueryUseCase(session_store=session_store)

    @provide
    def active_sessions_by_user_ids_query(
        self,
        session_store: SessionStore,
    ) -> GetActiveSessionsByUserIdsQueryUseCase:
        """指定user群のactive session取得query use caseを提供する.

        Args:
            session_store (SessionStore): active sessionを読み取るstate port.

        Returns:
            GetActiveSessionsByUserIdsQueryUseCase: user ID群に対応するsessionを返すread use case.
        """
        return GetActiveSessionsByUserIdsQueryUseCase(session_store=session_store)

    @provide
    def list_friend_ids_query(
        self,
        friend_repository: FriendRelationshipQueryRepository,
    ) -> ListFriendIdsQuery:
        """Friend ID一覧query use caseを提供する.

        Args:
            friend_repository (FriendRelationshipQueryRepository): friend関係を読むquery
                repository.

        Returns:
            ListFriendIdsQuery: userのfriend IDを返すread use case.
        """
        return ListFriendIdsQuery(repository=friend_repository)

    @provide
    def check_friend_relationship_query(
        self,
        friend_repository: FriendRelationshipQueryRepository,
    ) -> CheckFriendRelationshipQuery:
        """friend関係確認query use caseを提供する.

        Args:
            friend_repository (FriendRelationshipQueryRepository): friend関係を読むquery
                repository.

        Returns:
            CheckFriendRelationshipQuery: 2 user間のfriend関係を確認するread use case.
        """
        return CheckFriendRelationshipQuery(repository=friend_repository)

    @provide
    def friend_eligible_user_ids_query(
        self,
        friend_repository: FriendRelationshipQueryRepository,
    ) -> GetFriendEligibleUserIdsQuery:
        """Friends leaderboard表示対象のuser ID query use caseを提供する.

        Args:
            friend_repository (FriendRelationshipQueryRepository): friend関係を読むquery
                repository.

        Returns:
            GetFriendEligibleUserIdsQuery: viewer本人のIDと既存friendのIDを返すread use case.
        """
        return GetFriendEligibleUserIdsQuery(repository=friend_repository)

    @provide
    def session_credentials_query(
        self,
        user_repository: UserQueryRepository,
        password_service: PasswordService,
        session_store: SessionStore,
    ) -> SessionCredentialsQueryUseCase:
        """Stable client用session credential query use caseを提供する.

        Args:
            user_repository (UserQueryRepository): credential確認用userを読み取るquery repository.
            password_service (PasswordService): password credentialを検証するservice.
            session_store (SessionStore): session credentialを読み取るstate port.

        Returns:
            SessionCredentialsQueryUseCase: stable sessionのcredential情報を返すread use case.
        """
        return SessionCredentialsQueryUseCase(
            user_repository=user_repository,
            password_service=password_service,
            session_store=session_store,
        )
