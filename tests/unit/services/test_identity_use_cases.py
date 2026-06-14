"""Identity command/query use-case boundary tests."""

from __future__ import annotations

from typing import final

from osu_server.domain.identity.authentication import (
    ClientInfo,
    LegacyWebAuthResult,
    LoginRequest,
    LoginResult,
    RegistrationForm,
    RegistrationResult,
)
from osu_server.domain.identity.authorization import Privileges
from osu_server.domain.identity.sessions import (
    AuthorizationRefreshStatus,
    RoleAuthorizationRefreshResult,
    SessionAuthorization,
    UserAuthorizationRefreshResult,
)
from osu_server.services.commands.identity import (
    LoginCommandInput,
    LoginCommandUseCase,
    RefreshRoleAuthorizationCommandInput,
    RefreshRoleAuthorizationCommandUseCase,
    RefreshUserAuthorizationCommandInput,
    RefreshUserAuthorizationCommandUseCase,
    RegisterUserCommandInput,
    RegisterUserCommandUseCase,
)
from osu_server.services.queries.identity import (
    ComputePermissionsQueryInput,
    ComputePermissionsQueryUseCase,
    ComputeSessionAuthorizationQueryInput,
    ComputeSessionAuthorizationQueryUseCase,
    LegacyWebAuthQueryInput,
    LegacyWebAuthQueryUseCase,
    ListOnlineUsersQueryInput,
    ListOnlineUsersQueryUseCase,
)


@final
class FakeAuthService:
    login_inputs: list[tuple[LoginRequest, str]]
    register_inputs: list[tuple[RegistrationForm, bool]]

    def __init__(self) -> None:
        self.login_inputs = []
        self.register_inputs = []

    async def login(
        self,
        login_request: LoginRequest,
        *,
        country: str,
    ) -> LoginResult:
        self.login_inputs.append((login_request, country))
        return LoginResult.AUTHENTICATION_FAILED

    async def register(
        self,
        form_data: RegistrationForm,
        check_only: bool = False,
    ) -> RegistrationResult:
        self.register_inputs.append((form_data, check_only))
        return RegistrationResult(success=check_only)


@final
class FakeSessionAuthorizationService:
    user_refresh_inputs: list[int]
    role_refresh_inputs: list[int]

    def __init__(self) -> None:
        self.user_refresh_inputs = []
        self.role_refresh_inputs = []

    async def refresh_user_authorization(
        self,
        user_id: int,
    ) -> UserAuthorizationRefreshResult:
        self.user_refresh_inputs.append(user_id)
        return UserAuthorizationRefreshResult(
            user_id=user_id,
            status=AuthorizationRefreshStatus.NO_ACTIVE_SESSION,
        )

    async def refresh_role_authorization(
        self,
        role_id: int,
    ) -> RoleAuthorizationRefreshResult:
        self.role_refresh_inputs.append(role_id)
        return RoleAuthorizationRefreshResult(role_id=role_id, user_results=())


@final
class FakePermissionService:
    permission_inputs: list[int]
    authorization_inputs: list[int]

    def __init__(self) -> None:
        self.permission_inputs = []
        self.authorization_inputs = []

    async def compute_permissions(self, user_id: int) -> Privileges:
        self.permission_inputs.append(user_id)
        return Privileges.ADMIN

    async def compute_session_authorization(self, user_id: int) -> SessionAuthorization:
        self.authorization_inputs.append(user_id)
        return SessionAuthorization(privileges=Privileges.MODERATOR, role_ids=(3,))


@final
class FakeOnlineUsersService:
    async def get_all_user_ids(self) -> list[int]:
        return [3, 1, 2]


@final
class FakeLegacyWebAuthService:
    inputs: list[tuple[str | None, str | None]]

    def __init__(self) -> None:
        self.inputs = []

    async def authenticate(
        self,
        username: str | None,
        password_md5: str | None,
    ) -> LegacyWebAuthResult:
        self.inputs.append((username, password_md5))
        return LegacyWebAuthResult(user_id=7, username="TestUser")


def _login_request() -> LoginRequest:
    return LoginRequest(
        username="TestUser",
        password_md5="md5",
        client_info=ClientInfo(
            osu_version="20231111",
            utc_offset=9,
            display_city=False,
            client_hashes="hashes",
            pm_private=False,
        ),
    )


async def test_login_command_executes_login_workflow_as_command() -> None:
    service = FakeAuthService()
    use_case = LoginCommandUseCase(auth_service=service)
    request = _login_request()

    result = await use_case.execute(LoginCommandInput(login_request=request, country="JP"))

    assert result.outcome is LoginResult.AUTHENTICATION_FAILED
    assert service.login_inputs == [(request, "JP")]


async def test_register_user_command_preserves_check_only_input() -> None:
    service = FakeAuthService()
    use_case = RegisterUserCommandUseCase(auth_service=service)
    form = RegistrationForm(
        username="TestUser",
        email="test@example.com",
        password="SecurePass1234",
    )

    result = await use_case.execute(RegisterUserCommandInput(form_data=form, check_only=True))

    assert result.outcome == RegistrationResult(success=True)
    assert service.register_inputs == [(form, True)]


async def test_refresh_user_authorization_command_wraps_mutating_refresh() -> None:
    service = FakeSessionAuthorizationService()
    use_case = RefreshUserAuthorizationCommandUseCase(session_authorization_service=service)

    result = await use_case.execute(RefreshUserAuthorizationCommandInput(user_id=42))

    assert result.outcome.user_id == 42
    assert result.outcome.status is AuthorizationRefreshStatus.NO_ACTIVE_SESSION
    assert service.user_refresh_inputs == [42]


async def test_refresh_role_authorization_command_wraps_mutating_refresh() -> None:
    service = FakeSessionAuthorizationService()
    use_case = RefreshRoleAuthorizationCommandUseCase(session_authorization_service=service)

    result = await use_case.execute(RefreshRoleAuthorizationCommandInput(role_id=5))

    assert result.outcome == RoleAuthorizationRefreshResult(role_id=5, user_results=())
    assert service.role_refresh_inputs == [5]


async def test_compute_permissions_query_reads_authorization_without_mutation() -> None:
    service = FakePermissionService()
    use_case = ComputePermissionsQueryUseCase(permission_service=service)

    result = await use_case.execute(ComputePermissionsQueryInput(user_id=9))

    assert result.privileges is Privileges.ADMIN
    assert service.permission_inputs == [9]


async def test_compute_session_authorization_query_returns_snapshot() -> None:
    service = FakePermissionService()
    use_case = ComputeSessionAuthorizationQueryUseCase(permission_service=service)

    result = await use_case.execute(ComputeSessionAuthorizationQueryInput(user_id=10))

    assert result.authorization == SessionAuthorization(
        privileges=Privileges.MODERATOR,
        role_ids=(3,),
    )
    assert service.authorization_inputs == [10]


async def test_list_online_users_query_returns_snapshot_tuple() -> None:
    use_case = ListOnlineUsersQueryUseCase(online_users_service=FakeOnlineUsersService())

    result = await use_case.execute(ListOnlineUsersQueryInput())

    assert result.user_ids == (3, 1, 2)


async def test_legacy_web_auth_query_preserves_optional_credentials() -> None:
    service = FakeLegacyWebAuthService()
    use_case = LegacyWebAuthQueryUseCase(legacy_web_auth_service=service)

    result = await use_case.execute(
        LegacyWebAuthQueryInput(username="TestUser", password_md5="md5"),
    )

    assert result.outcome == LegacyWebAuthResult(user_id=7, username="TestUser")
    assert service.inputs == [("TestUser", "md5")]
