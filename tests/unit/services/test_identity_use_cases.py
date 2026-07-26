"""identity commandとquery use caseのboundary契約を検証するtest module."""

from __future__ import annotations

from datetime import UTC, datetime
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
    SessionData,
    UserAuthorizationRefreshResult,
)
from osu_server.domain.identity.users import User
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
    ListActiveSessionsQueryInput,
    ListActiveSessionsQueryUseCase,
    SessionCredentialsQueryInput,
    SessionCredentialsQueryUseCase,
)


@final
class FakeAuthService:
    """command use caseが渡すauthentication入力を記録するfake service.

    Attributes:
        login_inputs (list[tuple[LoginRequest, str]]): login requestとcountryの呼出し履歴.
        register_inputs (list[tuple[RegistrationForm, bool]]): registration formと
            check-only指定の履歴.
    """

    login_inputs: list[tuple[LoginRequest, str]]
    register_inputs: list[tuple[RegistrationForm, bool]]

    def __init__(self) -> None:
        """空のauthentication呼出し履歴を初期化する."""
        self.login_inputs = []
        self.register_inputs = []

    async def login(
        self,
        login_request: LoginRequest,
        *,
        country: str,
    ) -> LoginResult:
        """login入力を記録してauthentication failureを返す.

        Args:
            login_request (LoginRequest): command use caseから渡されるlogin request.
            country (str): login元として記録するcountry code.

        Returns:
            LoginResult: downstream結果を検証可能にする固定のAUTHENTICATION_FAILED結果.
        """
        self.login_inputs.append((login_request, country))
        return LoginResult.AUTHENTICATION_FAILED

    async def register(
        self,
        form_data: RegistrationForm,
        check_only: bool = False,
    ) -> RegistrationResult:
        """registration入力を記録してcheck-onlyに応じた結果を返す.

        Args:
            form_data (RegistrationForm): command use caseから渡されるregistration form.
            check_only (bool): 永続化せずvalidationだけを行うrequestか.

        Returns:
            RegistrationResult: check-only指定をsuccessへ反映した固定結果.
        """
        self.register_inputs.append((form_data, check_only))
        return RegistrationResult(success=check_only)


@final
class FakeSessionAuthorizationService:
    """authorization refresh commandの入力を記録するfake service.

    Attributes:
        user_refresh_inputs (list[int]): user単位refreshを要求されたuser IDの履歴.
        role_refresh_inputs (list[int]): role単位refreshを要求されたrole IDの履歴.
    """

    user_refresh_inputs: list[int]
    role_refresh_inputs: list[int]

    def __init__(self) -> None:
        """空のuser/role refresh要求履歴を初期化する."""
        self.user_refresh_inputs = []
        self.role_refresh_inputs = []

    async def refresh_user_authorization(
        self,
        user_id: int,
    ) -> UserAuthorizationRefreshResult:
        """User refresh要求を記録してactive sessionなしの結果を返す.

        Args:
            user_id (int): refresh対象としてcommand use caseから渡されるuser ID.

        Returns:
            UserAuthorizationRefreshResult: active sessionがないことを表す固定のrefresh結果.
        """
        self.user_refresh_inputs.append(user_id)
        return UserAuthorizationRefreshResult(
            user_id=user_id,
            status=AuthorizationRefreshStatus.NO_ACTIVE_SESSION,
        )

    async def refresh_role_authorization(
        self,
        role_id: int,
    ) -> RoleAuthorizationRefreshResult:
        """Role refresh要求を記録して対象userなしの結果を返す.

        Args:
            role_id (int): refresh対象としてcommand use caseから渡されるrole ID.

        Returns:
            RoleAuthorizationRefreshResult: refresh対象userがない固定のrole refresh結果.
        """
        self.role_refresh_inputs.append(role_id)
        return RoleAuthorizationRefreshResult(role_id=role_id, user_results=())


@final
class FakePermissionService:
    """permission queryがdelegateするauthorization serviceを模倣するfake.

    Attributes:
        permission_inputs (list[int]): privilege算出を要求されたuser IDの履歴.
        authorization_inputs (list[int]): session authorization算出を要求されたuser IDの履歴.
    """

    permission_inputs: list[int]
    authorization_inputs: list[int]

    def __init__(self) -> None:
        """空のpermission/authorization query入力履歴を初期化する."""
        self.permission_inputs = []
        self.authorization_inputs = []

    async def compute_permissions(self, user_id: int) -> Privileges:
        """userのprivilege queryを記録してAdmin権限を返す.

        Args:
            user_id (int): privilege算出対象としてquery use caseから渡されるuser ID.

        Returns:
            Privileges: query delegationを検証する固定のADMIN privilege.
        """
        self.permission_inputs.append(user_id)
        return Privileges.ADMIN

    async def compute_session_authorization(self, user_id: int) -> SessionAuthorization:
        """userのsession authorization queryを記録して固定snapshotを返す.

        Args:
            user_id (int): authorization算出対象としてquery use caseから渡されるuser ID.

        Returns:
            SessionAuthorization: MODERATOR privilegeとrole ID 3を持つ固定snapshot.
        """
        self.authorization_inputs.append(user_id)
        return SessionAuthorization(privileges=Privileges.MODERATOR, role_ids=(3,))


@final
class FakeActiveSessionStore:
    """list queryのsort契約を検証するための順不同session storeを提供するfake."""

    async def list_active_sessions(self) -> list[SessionData]:
        """順不同の2件のactive sessionを返す.

        Returns:
            list[SessionData]: user IDが3、1の順で並ぶ固定のonline session一覧.
        """
        return [
            SessionData(
                user_id=3,
                username="user_3",
                privileges=0,
                country="JP",
                osu_version="20231111",
                utc_offset=9,
                display_city=False,
                client_hashes="hashes",
                pm_private=False,
            ),
            SessionData(
                user_id=1,
                username="user_1",
                privileges=1,
                country="US",
                osu_version="20231111",
                utc_offset=-5,
                display_city=False,
                client_hashes="hashes",
                pm_private=False,
            ),
        ]


@final
class FakeSessionCredentialUserRepository:
    """session credential query用の単一user repositoryを提供するfake.

    Attributes:
        inputs (list[str]): safe username lookupで受け取った値の履歴.
        user (User): username、email、IDで照合する固定の登録済みuser.
    """

    inputs: list[str]

    def __init__(self) -> None:
        """固定userと空のsafe username lookup履歴を初期化する."""
        self.inputs = []
        now = datetime(2026, 6, 15, tzinfo=UTC)
        self.user = User(
            id=7,
            username="TestUser",
            safe_username="testuser",
            email="test@example.com",
            password_hash="hashed-password",
            country="JP",
            created_at=now,
            updated_at=now,
        )

    async def get_by_safe_username(self, safe_username: str) -> User | None:
        """Safe usernameに一致する固定userを返す.

        Args:
            safe_username (str): lookup対象の正規化済みusername.

        Returns:
            User | None: 固定user. usernameが一致しない場合はNone.
        """
        self.inputs.append(safe_username)
        if safe_username != self.user.safe_username:
            return None
        return self.user

    async def get_by_id(self, user_id: int) -> User | None:
        """IDに一致する固定userを返す.

        Args:
            user_id (int): lookup対象の永続化user ID.

        Returns:
            User | None: 固定user. IDが一致しない場合はNone.
        """
        return self.user if user_id == self.user.id else None

    async def get_by_email(self, email: str) -> User | None:
        """emailに一致する固定userを返す.

        Args:
            email (str): lookup対象のemail address.

        Returns:
            User | None: 固定user. emailが一致しない場合はNone.
        """
        return self.user if email == self.user.email else None

    async def is_username_disallowed(self, safe_username: str) -> bool:
        """BanchoBotのsafe usernameだけを禁止値として返す.

        Args:
            safe_username (str): 禁止判定する正規化済みusername.

        Returns:
            bool: 値がbanchobotの場合はTrue. それ以外はFalse.
        """
        return safe_username == "banchobot"


@final
class FakePasswordVerifier:
    """session credential queryのpassword照合入力を記録するfake verifier.

    Attributes:
        inputs (list[tuple[str, str]]): hashと平文MD5を組にした照合要求履歴.
    """

    inputs: list[tuple[str, str]]

    def __init__(self) -> None:
        """空のpassword照合要求履歴を初期化する."""
        self.inputs = []

    async def verify(self, hashed: str, password: str) -> bool:
        """固定のhashとpassword組だけを成功として返す.

        Args:
            hashed (str): repositoryから取得したpassword hash.
            password (str): credential queryから渡される平文MD5.

        Returns:
            bool: hashed-passwordとmd5の組だけがTrueとなる照合結果.
        """
        self.inputs.append((hashed, password))
        return hashed == "hashed-password" and password == "md5"


@final
class FakeCredentialSessionStore:
    """session credential queryに必要なactive session portを実装するfake.

    Attributes:
        inputs (list[int]): user IDからsessionを取得した要求履歴.
    """

    inputs: list[int]

    def __init__(self) -> None:
        """空のsession lookup履歴を初期化する."""
        self.inputs = []

    async def get_by_user(self, user_id: int) -> SessionData | None:
        """固定userのactive sessionを取得し、lookup入力を記録する.

        Args:
            user_id (int): active sessionを取得するuser ID.

        Returns:
            SessionData | None: user ID 7の固定session. それ以外はNone.
        """
        self.inputs.append(user_id)
        if user_id != 7:
            return None
        return SessionData(
            user_id=user_id,
            username="TestUser",
            privileges=0,
            country="JP",
            osu_version="20231111",
            utc_offset=9,
            display_city=False,
            client_hashes="hashes",
            pm_private=False,
        )

    async def create(self, user_id: int, token: str, data: SessionData) -> None:
        """Create portを副作用なしで受け入れる.

        Args:
            user_id (int): sessionを紐付けるuser ID.
            token (str): 保存対象のsession token.
            data (SessionData): 保存対象のsession data.

        Returns:
            None: fake stateを変更せず値を返さずに完了する.
        """
        _ = (user_id, token, data)

    async def get(self, token: str) -> SessionData | None:
        """Token lookupを副作用なしでNoneとして返す.

        Args:
            token (str): session dataを取得するtoken.

        Returns:
            SessionData | None: token単位lookupを実装しないためNone.
        """
        _ = token
        return None

    async def delete(self, token: str) -> None:
        """Token deletion portを副作用なしで受け入れる.

        Args:
            token (str): 削除対象として渡されるsession token.

        Returns:
            None: fake stateを変更せず値を返さずに完了する.
        """
        _ = token

    async def exists(self, token: str) -> bool:
        """tokenが存在しない固定結果を返す.

        Args:
            token (str): 存在確認するsession token.

        Returns:
            bool: fakeがtoken単位sessionを保持しないためFalse.
        """
        _ = token
        return False

    async def refresh(self, token: str) -> bool:
        """Token refreshを行わない固定結果を返す.

        Args:
            token (str): refresh対象として渡されるsession token.

        Returns:
            bool: fakeがtoken単位sessionを保持しないためFalse.
        """
        _ = token
        return False

    async def delete_by_user(self, user_id: int) -> None:
        """user単位deletion portを副作用なしで受け入れる.

        Args:
            user_id (int): session削除対象として渡されるuser ID.

        Returns:
            None: fake stateを変更せず値を返さずに完了する.
        """
        _ = user_id

    async def update_authorization(
        self,
        user_id: int,
        authorization: SessionAuthorization,
    ) -> bool:
        """Authorization updateを行わない固定結果を返す.

        Args:
            user_id (int): authorizationを更新するuser ID.
            authorization (SessionAuthorization): 保存対象として渡されるauthorization snapshot.

        Returns:
            bool: fakeがauthorizationを保存しないためFalse.
        """
        _ = (user_id, authorization)
        return False

    async def update_pm_private(self, user_id: int, enabled: bool) -> bool:
        """PM privacy updateを行わない固定結果を返す.

        Args:
            user_id (int): PM privacyを更新するuser ID.
            enabled (bool): 保存対象として渡されるPM privacy設定.

        Returns:
            bool: fakeがPM privacyを保存しないためFalse.
        """
        _ = (user_id, enabled)
        return False

    async def list_active_sessions(self) -> list[SessionData]:
        """固定userのactive sessionだけをlist形式で返す.

        Returns:
            list[SessionData]: user ID 7のsession. 取得できない場合は空list.
        """
        session = await self.get_by_user(7)
        return [] if session is None else [session]


def _login_request() -> LoginRequest:
    """Login command testで使う固定のlegacy login requestを作成する.

    Returns:
        LoginRequest: TestUser、MD5、client metadataを持つ固定request.
    """
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
    """Login commandがrequestとcountryをauthentication serviceへdelegateする契約を検証する.

    固定login requestでcommandを実行し、serviceのfailure結果と記録済み入力がそのまま返ることを
    確認する.

    Returns:
        None: command outcomeとfake service入力履歴を検証して完了する.
    """
    service = FakeAuthService()
    use_case = LoginCommandUseCase(auth_service=service)
    request = _login_request()

    result = await use_case.execute(LoginCommandInput(login_request=request, country="JP"))

    assert result.outcome is LoginResult.AUTHENTICATION_FAILED
    assert service.login_inputs == [(request, "JP")]


async def test_register_user_command_preserves_check_only_input() -> None:
    """Registration commandがcheck-only指定をauthentication serviceへ保持する契約を検証する.

    check-only registration formを実行し成功結果とserviceへ記録されたTrueを確認する.

    Returns:
        None: registration outcomeとfake service入力履歴を検証して完了する.
    """
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
    """User authorization refresh commandがmutating serviceを呼ぶ契約を検証する.

    user IDを指定してcommandを実行しNO_ACTIVE_SESSION結果とdelegate先の入力履歴を確認する.

    Returns:
        None: refresh outcomeとfake service入力履歴を検証して完了する.
    """
    service = FakeSessionAuthorizationService()
    use_case = RefreshUserAuthorizationCommandUseCase(session_authorization_service=service)

    result = await use_case.execute(RefreshUserAuthorizationCommandInput(user_id=42))

    assert result.outcome.user_id == 42
    assert result.outcome.status is AuthorizationRefreshStatus.NO_ACTIVE_SESSION
    assert service.user_refresh_inputs == [42]


async def test_refresh_role_authorization_command_wraps_mutating_refresh() -> None:
    """Role authorization refresh commandがmutating serviceを呼ぶ契約を検証する.

    role IDを指定してcommandを実行し空のuser結果とdelegate先の入力履歴を確認する.

    Returns:
        None: refresh outcomeとfake service入力履歴を検証して完了する.
    """
    service = FakeSessionAuthorizationService()
    use_case = RefreshRoleAuthorizationCommandUseCase(session_authorization_service=service)

    result = await use_case.execute(RefreshRoleAuthorizationCommandInput(role_id=5))

    assert result.outcome == RoleAuthorizationRefreshResult(role_id=5, user_results=())
    assert service.role_refresh_inputs == [5]


async def test_compute_permissions_query_reads_authorization_without_mutation() -> None:
    """Permission queryがauthorizationをread-onlyでdelegateする契約を検証する.

    user IDを指定してqueryを実行し固定ADMIN privilegeとserviceへの1回の入力を確認する.

    Returns:
        None: query resultとfake service入力履歴を検証して完了する.
    """
    service = FakePermissionService()
    use_case = ComputePermissionsQueryUseCase(permission_service=service)

    result = await use_case.execute(ComputePermissionsQueryInput(user_id=9))

    assert result.privileges is Privileges.ADMIN
    assert service.permission_inputs == [9]


async def test_compute_session_authorization_query_returns_snapshot() -> None:
    """Session authorization queryがservice snapshotを返す契約を検証する.

    user IDを指定してqueryを実行しMODERATOR privilegeとrole ID 3のsnapshotを確認する.

    Returns:
        None: query resultとfake service入力履歴を検証して完了する.
    """
    service = FakePermissionService()
    use_case = ComputeSessionAuthorizationQueryUseCase(permission_service=service)

    result = await use_case.execute(ComputeSessionAuthorizationQueryInput(user_id=10))

    assert result.authorization == SessionAuthorization(
        privileges=Privileges.MODERATOR,
        role_ids=(3,),
    )
    assert service.authorization_inputs == [10]


async def test_list_active_sessions_query_returns_snapshot_tuple() -> None:
    """Active session list queryがuser IDでsortしたsnapshot tupleを返す契約を検証する.

    順不同のfake storeでqueryを実行し結果のsession IDが1、3の昇順になることを確認する.

    Returns:
        None: sort済みsession snapshot tupleを検証して完了する.
    """
    use_case = ListActiveSessionsQueryUseCase(session_store=FakeActiveSessionStore())

    result = await use_case.execute(ListActiveSessionsQueryInput())

    assert tuple(session.user_id for session in result.sessions) == (1, 3)


async def test_session_credentials_query_reads_credentials_and_active_session() -> None:
    """Session credential queryがuser、password、session portを順に読む契約を検証する.

    固定usernameとMD5でqueryを実行しlegacy auth結果と各portの正規化済み入力を確認する.

    Returns:
        None: credential query outcomeと各fake port入力履歴を検証して完了する.
    """
    user_repository = FakeSessionCredentialUserRepository()
    password_service = FakePasswordVerifier()
    session_store = FakeCredentialSessionStore()
    use_case = SessionCredentialsQueryUseCase(
        user_repository=user_repository,
        password_service=password_service,
        session_store=session_store,
    )

    result = await use_case.execute(
        SessionCredentialsQueryInput(username="TestUser", password_md5="md5"),
    )

    assert result.outcome == LegacyWebAuthResult(user_id=7, username="TestUser")
    assert user_repository.inputs == ["testuser"]
    assert password_service.inputs == [("hashed-password", "md5")]
    assert session_store.inputs == [7]
