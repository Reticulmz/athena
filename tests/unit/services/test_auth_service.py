"""AuthService.register() / login() のユニットテスト。

TDD RED -> GREEN -> REFACTOR で実装。
InMemoryUserRepository / InMemoryRoleRepository / InMemorySessionStore を使用し、
PasswordService は実インスタンス(is_password_banned のみ mock する場合あり)。
"""

from __future__ import annotations

import hashlib
from unittest.mock import AsyncMock, MagicMock

from structlog.testing import capture_logs

from osu_server.domain.auth import (
    ClientInfo,
    LoginRequest,
    LoginResponse,
    LoginResult,
    RegistrationForm,
    RegistrationResult,
)
from osu_server.domain.role import Privileges, Role
from osu_server.domain.session import SessionData
from osu_server.infrastructure.state.memory.session_store import InMemorySessionStore
from osu_server.repositories.memory.role_repository import InMemoryRoleRepository
from osu_server.repositories.memory.user_repository import InMemoryUserRepository
from osu_server.services.auth_service import AuthService
from osu_server.services.password_service import PasswordService
from osu_server.services.permission_service import PermissionService

# ── Seed data ────────────────────────────────────────────────────────


def _md5_hex(s: str) -> str:
    return hashlib.md5(s.encode()).hexdigest()


ROLE_DEFAULT = Role(
    id=1,
    name="Default",
    permissions=Privileges.NORMAL | Privileges.VERIFIED | Privileges.UNRESTRICTED,
    position=0,
)


def _make_service(
    *,
    banned_passwords: list[str] | None = None,
) -> tuple[AuthService, InMemoryUserRepository, InMemoryRoleRepository]:
    """テスト用の AuthService + リポジトリを構築する。"""
    user_repo = InMemoryUserRepository()
    role_repo = InMemoryRoleRepository(seed_roles=[ROLE_DEFAULT])
    password_service = PasswordService(
        hibp_client=None,
        banned_passwords=banned_passwords or [],
    )
    svc = AuthService(
        user_repo=user_repo,
        role_repo=role_repo,
        password_service=password_service,
    )
    return svc, user_repo, role_repo


def _valid_form(
    *,
    username: str = "TestUser",
    email: str = "test@example.com",
    password: str = "SecurePass1234",
) -> RegistrationForm:
    """デフォルト有効値の RegistrationForm を生成する。"""
    return RegistrationForm(username=username, email=email, password=password)


# ── Username validation (Req 3.1, 3.2) ──────────────────────────────


class TestUsernameValidation:
    """ユーザー名バリデーション: 2-15文字、[a-zA-Z0-9_ -]+、スペース+アンダースコア共存不可。"""

    async def test_too_short(self) -> None:
        svc, *_ = _make_service()
        result = await svc.register(_valid_form(username="A"))
        assert result.success is False
        assert "username" in result.errors

    async def test_too_long(self) -> None:
        svc, *_ = _make_service()
        result = await svc.register(_valid_form(username="A" * 16))
        assert result.success is False
        assert "username" in result.errors

    async def test_min_length_boundary(self) -> None:
        svc, *_ = _make_service()
        result = await svc.register(_valid_form(username="Ab"))
        assert result.success is True

    async def test_max_length_boundary(self) -> None:
        svc, *_ = _make_service()
        result = await svc.register(_valid_form(username="A" * 15))
        assert result.success is True

    async def test_invalid_characters(self) -> None:
        svc, *_ = _make_service()
        result = await svc.register(_valid_form(username="Test@User!"))
        assert result.success is False
        assert "username" in result.errors

    async def test_space_and_underscore_coexist(self) -> None:
        svc, *_ = _make_service()
        result = await svc.register(_valid_form(username="Test _User"))
        assert result.success is False
        assert "username" in result.errors

    async def test_space_only_allowed(self) -> None:
        svc, *_ = _make_service()
        result = await svc.register(_valid_form(username="Test User"))
        assert result.success is True

    async def test_underscore_only_allowed(self) -> None:
        svc, *_ = _make_service()
        result = await svc.register(_valid_form(username="Test_User"))
        assert result.success is True

    async def test_hyphen_allowed(self) -> None:
        svc, *_ = _make_service()
        result = await svc.register(_valid_form(username="Test-User"))
        assert result.success is True

    async def test_alphanumeric_only(self) -> None:
        svc, *_ = _make_service()
        result = await svc.register(_valid_form(username="User123"))
        assert result.success is True

    async def test_empty_username(self) -> None:
        svc, *_ = _make_service()
        result = await svc.register(_valid_form(username=""))
        assert result.success is False
        assert "username" in result.errors


# ── Password validation (Req 3.3, 3.4) ──────────────────────────────


class TestPasswordValidation:
    """パスワードバリデーション: 8-32文字、ユニーク文字数4以上。"""

    async def test_too_short(self) -> None:
        svc, *_ = _make_service()
        result = await svc.register(_valid_form(password="Ab1cdef"))
        assert result.success is False
        assert "password" in result.errors

    async def test_too_long(self) -> None:
        svc, *_ = _make_service()
        result = await svc.register(_valid_form(password="A" * 33))
        assert result.success is False
        assert "password" in result.errors

    async def test_min_length_boundary(self) -> None:
        svc, *_ = _make_service()
        result = await svc.register(_valid_form(password="Abcd1234"))
        assert result.success is True

    async def test_max_length_boundary(self) -> None:
        svc, *_ = _make_service()
        result = await svc.register(_valid_form(password="Abcd" + "x" * 28))
        assert result.success is True

    async def test_insufficient_unique_chars(self) -> None:
        svc, *_ = _make_service()
        # 'aaa' repeated = only 1 unique char
        result = await svc.register(_valid_form(password="aaaaaaaa"))
        assert result.success is False
        assert "password" in result.errors

    async def test_three_unique_chars_insufficient(self) -> None:
        svc, *_ = _make_service()
        result = await svc.register(_valid_form(password="aabbccaa"))
        assert result.success is False
        assert "password" in result.errors

    async def test_four_unique_chars_sufficient(self) -> None:
        svc, *_ = _make_service()
        result = await svc.register(_valid_form(password="aabbccdd"))
        assert result.success is True

    async def test_length_and_unique_both_fail(self) -> None:
        """短すぎ + ユニーク不足の場合、両方のエラーが蓄積される。"""
        svc, *_ = _make_service()
        result = await svc.register(_valid_form(password="aaa"))
        assert result.success is False
        assert "password" in result.errors
        min_expected_errors = 2
        assert len(result.errors["password"]) >= min_expected_errors


# ── Email validation (Req 3.5) ───────────────────────────────────────


class TestEmailValidation:
    """メールアドレスの形式バリデーション。"""

    async def test_valid_email(self) -> None:
        svc, *_ = _make_service()
        result = await svc.register(_valid_form(email="user@example.com"))
        assert result.success is True

    async def test_missing_at_sign(self) -> None:
        svc, *_ = _make_service()
        result = await svc.register(_valid_form(email="userexample.com"))
        assert result.success is False
        assert "email" in result.errors

    async def test_missing_domain(self) -> None:
        svc, *_ = _make_service()
        result = await svc.register(_valid_form(email="user@"))
        assert result.success is False
        assert "email" in result.errors

    async def test_missing_tld(self) -> None:
        svc, *_ = _make_service()
        result = await svc.register(_valid_form(email="user@example"))
        assert result.success is False
        assert "email" in result.errors

    async def test_empty_email(self) -> None:
        svc, *_ = _make_service()
        result = await svc.register(_valid_form(email=""))
        assert result.success is False
        assert "email" in result.errors

    async def test_spaces_in_email(self) -> None:
        svc, *_ = _make_service()
        result = await svc.register(_valid_form(email="user @example.com"))
        assert result.success is False
        assert "email" in result.errors


# ── Duplicate checks (Req 1.5, 1.6) ─────────────────────────────────


class TestDuplicateChecks:
    """重複ユーザー名・メール検出。"""

    async def test_duplicate_username(self) -> None:
        svc, *_ = _make_service()
        _ = await svc.register(_valid_form(username="ExistingUser", email="first@example.com"))
        result = await svc.register(
            _valid_form(username="ExistingUser", email="second@example.com")
        )
        assert result.success is False
        assert "username" in result.errors

    async def test_duplicate_username_normalized(self) -> None:
        """'Test User' と 'test_user' は正規化後に一致。"""
        svc, *_ = _make_service()
        _ = await svc.register(_valid_form(username="Test User", email="first@example.com"))
        result = await svc.register(_valid_form(username="test_user", email="second@example.com"))
        assert result.success is False
        assert "username" in result.errors

    async def test_duplicate_email(self) -> None:
        svc, *_ = _make_service()
        _ = await svc.register(_valid_form(username="User1", email="same@example.com"))
        result = await svc.register(_valid_form(username="User2", email="same@example.com"))
        assert result.success is False
        assert "email" in result.errors

    async def test_duplicate_email_case_insensitive(self) -> None:
        svc, *_ = _make_service()
        _ = await svc.register(_valid_form(username="User1", email="Test@Example.COM"))
        result = await svc.register(_valid_form(username="User2", email="test@example.com"))
        assert result.success is False
        assert "email" in result.errors


# ── Disallowed username (Req 1.7) ────────────────────────────────────


class TestDisallowedUsername:
    """禁止ユーザー名チェック。"""

    async def test_disallowed_username(self) -> None:
        svc, user_repo, _ = _make_service()
        await user_repo.add_disallowed_username("banned_user")
        result = await svc.register(_valid_form(username="Banned User", email="new@example.com"))
        assert result.success is False
        assert "username" in result.errors

    async def test_allowed_username_passes(self) -> None:
        svc, user_repo, _ = _make_service()
        await user_repo.add_disallowed_username("other_name")
        result = await svc.register(_valid_form(username="AllowedUser", email="new@example.com"))
        assert result.success is True


# ── Password banned (Req 4.4, 4.5) ──────────────────────────────────


class TestPasswordBanned:
    """is_password_banned 統合チェック。"""

    async def test_password_in_custom_banned_list(self) -> None:
        svc, *_ = _make_service(banned_passwords=["SecurePass1234"])
        result = await svc.register(_valid_form(password="SecurePass1234"))
        assert result.success is False
        assert "password" in result.errors

    async def test_password_banned_by_hibp(self) -> None:
        user_repo = InMemoryUserRepository()
        role_repo = InMemoryRoleRepository(seed_roles=[ROLE_DEFAULT])
        pw_svc = PasswordService()
        pw_svc.is_password_banned = AsyncMock(return_value=True)  # type: ignore[method-assign]
        svc = AuthService(
            user_repo=user_repo,
            role_repo=role_repo,
            password_service=pw_svc,
        )
        result = await svc.register(_valid_form())
        assert result.success is False
        assert "password" in result.errors

    async def test_safe_password_passes(self) -> None:
        svc, *_ = _make_service(banned_passwords=["other_password"])
        result = await svc.register(_valid_form(password="SafePass1234"))
        assert result.success is True


# ── Error accumulation ───────────────────────────────────────────────


class TestErrorAccumulation:
    """バリデーションエラーは蓄積される(最初で止まらない)。"""

    async def test_multiple_field_errors_accumulated(self) -> None:
        svc, *_ = _make_service()
        result = await svc.register(_valid_form(username="!", email="bad", password="aaa"))
        assert result.success is False
        assert "username" in result.errors
        assert "email" in result.errors
        assert "password" in result.errors

    async def test_result_type_is_registration_result(self) -> None:
        svc, *_ = _make_service()
        result = await svc.register(_valid_form())
        assert isinstance(result, RegistrationResult)


# ── check_only mode (Req 2.1, 2.2) ──────────────────────────────────


class TestCheckOnlyMode:
    """check_only=True ではバリデーションのみ、アカウント作成しない。"""

    async def test_check_only_valid_no_user_created(self) -> None:
        svc, user_repo, _ = _make_service()
        result = await svc.register(_valid_form(), check_only=True)
        assert result.success is True
        assert result.errors == {}
        # ユーザーは作成されていない
        user = await user_repo.get_by_safe_username("testuser")
        assert user is None

    async def test_check_only_invalid_returns_errors(self) -> None:
        svc, *_ = _make_service()
        result = await svc.register(_valid_form(username="!"), check_only=True)
        assert result.success is False
        assert "username" in result.errors

    async def test_check_only_duplicate_detected(self) -> None:
        svc, *_ = _make_service()
        _ = await svc.register(_valid_form(username="Taken", email="taken@example.com"))
        result = await svc.register(
            _valid_form(username="Taken", email="other@example.com"),
            check_only=True,
        )
        assert result.success is False
        assert "username" in result.errors


# ── Successful registration (Req 1.1, 1.2, 1.3, 4.1, 8.7) ──────────


class TestSuccessfulRegistration:
    """成功ケース: ユーザー作成 + デフォルトロール付与。"""

    async def test_user_created_in_repository(self) -> None:
        svc, user_repo, _ = _make_service()
        result = await svc.register(_valid_form(username="NewUser", email="new@example.com"))
        assert result.success is True
        assert result.errors == {}
        user = await user_repo.get_by_safe_username("newuser")
        assert user is not None
        assert user.username == "NewUser"
        assert user.email == "new@example.com"

    async def test_safe_username_normalized(self) -> None:
        """safe_username は小文字化 + スペース→アンダースコア変換 (Req 1.3)。"""
        svc, user_repo, _ = _make_service()
        _ = await svc.register(_valid_form(username="My User", email="u@example.com"))
        user = await user_repo.get_by_safe_username("my_user")
        assert user is not None
        assert user.safe_username == "my_user"

    async def test_password_stored_as_argon2id(self) -> None:
        """パスワードは MD5 → argon2id で保存 (Req 4.1)。"""
        svc, user_repo, _ = _make_service()
        _ = await svc.register(_valid_form(username="HashUser", email="h@example.com"))
        user = await user_repo.get_by_safe_username("hashuser")
        assert user is not None
        assert user.password_hash.startswith("$argon2id$")

    async def test_default_role_assigned(self) -> None:
        """デフォルトロールが付与される (Req 1.2)。"""
        svc, user_repo, role_repo = _make_service()
        _ = await svc.register(_valid_form(username="RoleUser", email="r@example.com"))
        user = await user_repo.get_by_safe_username("roleuser")
        assert user is not None
        roles = await role_repo.get_roles_for_user(user.id)
        assert len(roles) == 1
        assert roles[0].name == "Default"

    async def test_verified_flag_via_default_role(self) -> None:
        """デフォルトロールに VERIFIED が含まれ、即アクティブ (Req 8.7)。"""
        svc, user_repo, role_repo = _make_service()
        _ = await svc.register(_valid_form(username="VerUser", email="v@example.com"))
        user = await user_repo.get_by_safe_username("veruser")
        assert user is not None
        roles = await role_repo.get_roles_for_user(user.id)
        combined = Privileges.NONE
        for role in roles:
            combined |= role.permissions
        assert Privileges.VERIFIED in combined

    async def test_success_result_structure(self) -> None:
        svc, *_ = _make_service()
        result = await svc.register(_valid_form())
        assert result.success is True
        assert result.errors == {}

    async def test_plaintext_password_not_stored(self) -> None:
        """平文パスワードが DB に保存されていないことを確認 (Req 4.3)。"""
        svc, user_repo, _ = _make_service()
        password = "SecurePass1234"
        _ = await svc.register(
            _valid_form(username="PlainUser", email="p@example.com", password=password)
        )
        user = await user_repo.get_by_safe_username("plainuser")
        assert user is not None
        assert user.password_hash != password
        # MD5 が直接保存されていないことも確認
        md5_hex = _md5_hex(password)
        assert user.password_hash != md5_hex


# ═══════════════════════════════════════════════════════════════════════
# AuthService.login() テスト (Req 5.1, 5.2, 5.3, 5.4, 5.5, 5.7, 5.8, 10.1, 10.3)
# ═══════════════════════════════════════════════════════════════════════

_LOGIN_PASSWORD = "SecurePass1234"
_LOGIN_PASSWORD_MD5 = _md5_hex(_LOGIN_PASSWORD)
_LOGIN_UTC_OFFSET = 9


class _StubCountryResolver:
    """テスト用の CountryResolver — 常に固定国コードを返す。"""

    _country: str

    def __init__(self, country: str = "JP") -> None:
        self._country = country

    def resolve(self, request: object) -> str:  # noqa: ARG002  # pyright: ignore[reportUnusedParameter]
        return self._country


def _fake_request() -> MagicMock:
    """ログインテスト用の Request モック。"""
    req = MagicMock()
    req.headers = {"X-Forwarded-For": "127.0.0.1"}
    return req


def _login_request(
    *,
    username: str = "TestUser",
    password_md5: str = _LOGIN_PASSWORD_MD5,
) -> LoginRequest:
    return LoginRequest(
        username=username,
        password_md5=password_md5,
        client_info=ClientInfo(
            osu_version="20231111",
            utc_offset=_LOGIN_UTC_OFFSET,
            display_city=True,
            client_hashes="hash1:hash2:hash3",
            pm_private=False,
        ),
    )


async def _make_login_service(
    *,
    country: str = "JP",
) -> tuple[
    AuthService,
    InMemoryUserRepository,
    InMemoryRoleRepository,
    InMemorySessionStore,
    PermissionService,
]:
    """login テスト用の AuthService + 依存を構築し、テストユーザーを登録する。"""
    user_repo = InMemoryUserRepository()
    role_repo = InMemoryRoleRepository(seed_roles=[ROLE_DEFAULT])
    session_store = InMemorySessionStore()
    password_service = PasswordService(hibp_client=None, banned_passwords=[])
    permission_service = PermissionService(role_repo=role_repo)
    country_resolver = _StubCountryResolver(country=country)

    svc = AuthService(
        user_repo=user_repo,
        role_repo=role_repo,
        password_service=password_service,
        permission_service=permission_service,
        session_store=session_store,
        country_resolver=country_resolver,
    )

    # テストユーザーを register() で作成
    result = await svc.register(
        RegistrationForm(
            username="TestUser",
            email="test@example.com",
            password=_LOGIN_PASSWORD,
        ),
    )
    assert result.success is True

    return svc, user_repo, role_repo, session_store, permission_service


# ── Login success (Req 5.1, 5.4, 5.5, 10.1) ──────────────────────────


class TestLoginSuccess:
    """ログイン成功ケース: LoginResponse の全フィールドを検証。"""

    async def test_returns_login_response(self) -> None:
        svc, *_ = await _make_login_service()
        result = await svc.login(_fake_request(), _login_request())
        assert isinstance(result, LoginResponse)

    async def test_token_is_nonempty_string(self) -> None:
        svc, *_ = await _make_login_service()
        result = await svc.login(_fake_request(), _login_request())
        assert isinstance(result, LoginResponse)
        assert isinstance(result.token, str)
        assert len(result.token) > 0

    async def test_user_field_matches(self) -> None:
        svc, user_repo, *_ = await _make_login_service()
        result = await svc.login(_fake_request(), _login_request())
        assert isinstance(result, LoginResponse)
        user = await user_repo.get_by_safe_username("testuser")
        assert user is not None
        assert result.user.id == user.id
        assert result.user.username == "TestUser"

    async def test_privileges_computed(self) -> None:
        """デフォルトロールの権限が正しく計算される。"""
        svc, *_ = await _make_login_service()
        result = await svc.login(_fake_request(), _login_request())
        assert isinstance(result, LoginResponse)
        expected = Privileges.NORMAL | Privileges.VERIFIED | Privileges.UNRESTRICTED
        assert result.privileges == expected

    async def test_country_resolved(self) -> None:
        svc, *_ = await _make_login_service(country="JP")
        result = await svc.login(_fake_request(), _login_request())
        assert isinstance(result, LoginResponse)
        assert result.country == "JP"

    async def test_session_data_populated(self) -> None:
        svc, user_repo, *_ = await _make_login_service()
        result = await svc.login(_fake_request(), _login_request())
        assert isinstance(result, LoginResponse)
        assert isinstance(result.session_data, SessionData)
        user = await user_repo.get_by_safe_username("testuser")
        assert user is not None
        assert result.session_data.user_id == user.id
        assert result.session_data.username == "TestUser"
        assert result.session_data.country == "JP"
        assert result.session_data.osu_version == "20231111"
        assert result.session_data.utc_offset == _LOGIN_UTC_OFFSET
        assert result.session_data.display_city is True
        assert result.session_data.client_hashes == "hash1:hash2:hash3"
        assert result.session_data.pm_private is False

    async def test_session_stored_in_session_store(self) -> None:
        svc, user_repo, _, session_store, _ = await _make_login_service()
        result = await svc.login(_fake_request(), _login_request())
        assert isinstance(result, LoginResponse)
        user = await user_repo.get_by_safe_username("testuser")
        assert user is not None
        stored = await session_store.get_by_user(user.id)
        assert stored is not None

    async def test_session_retrievable_by_token(self) -> None:
        svc, _, _, session_store, _ = await _make_login_service()
        result = await svc.login(_fake_request(), _login_request())
        assert isinstance(result, LoginResponse)
        stored = await session_store.get(result.token)
        assert stored is not None


# ── Login failure: user not found (Req 5.2) ───────────────────────────


class TestLoginUserNotFound:
    """存在しないユーザー名でのログイン失敗。"""

    async def test_returns_authentication_failed(self) -> None:
        svc, *_ = await _make_login_service()
        result = await svc.login(
            _fake_request(),
            _login_request(username="NonExistent"),
        )
        assert result is LoginResult.AUTHENTICATION_FAILED

    async def test_no_information_leak(self) -> None:
        """ユーザー不在もパスワード不一致も同じ AUTHENTICATION_FAILED を返す (Req 5.3)。"""
        svc, *_ = await _make_login_service()
        not_found = await svc.login(
            _fake_request(),
            _login_request(username="NoSuchUser"),
        )
        wrong_pass = await svc.login(
            _fake_request(),
            _login_request(password_md5="0" * 32),
        )
        assert not_found == wrong_pass == LoginResult.AUTHENTICATION_FAILED


# ── Login failure: password mismatch (Req 5.2, 5.3) ──────────────────


class TestLoginPasswordMismatch:
    """正しいユーザー名 + 誤ったパスワードでのログイン失敗。"""

    async def test_returns_authentication_failed(self) -> None:
        svc, *_ = await _make_login_service()
        result = await svc.login(
            _fake_request(),
            _login_request(password_md5="0" * 32),
        )
        assert result is LoginResult.AUTHENTICATION_FAILED

    async def test_no_session_created(self) -> None:
        svc, user_repo, _, session_store, _ = await _make_login_service()
        _ = await svc.login(
            _fake_request(),
            _login_request(password_md5="0" * 32),
        )
        user = await user_repo.get_by_safe_username("testuser")
        assert user is not None
        stored = await session_store.get_by_user(user.id)
        assert stored is None


# ── Re-login: old session replaced (Req 5.7, 5.8) ────────────────────


class TestLoginSessionReplacement:
    """再ログインで旧セッションが破棄され新セッションが作成される。"""

    async def test_old_session_replaced_by_new(self) -> None:
        svc, _, _, session_store, _ = await _make_login_service()
        first = await svc.login(_fake_request(), _login_request())
        assert isinstance(first, LoginResponse)
        first_token = first.token

        second = await svc.login(_fake_request(), _login_request())
        assert isinstance(second, LoginResponse)
        second_token = second.token

        # トークンが異なること
        assert first_token != second_token

        # 旧トークンは無効化されている
        assert await session_store.exists(first_token) is False

        # 新トークンは有効
        assert await session_store.exists(second_token) is True

    async def test_only_one_session_per_user(self) -> None:
        """同一ユーザーのセッションは常に1つだけ (Req 5.8)。"""
        svc, user_repo, _, session_store, _ = await _make_login_service()

        # 3回ログイン
        last_result: LoginResponse | LoginResult | None = None
        for _ in range(3):
            last_result = await svc.login(_fake_request(), _login_request())
            assert isinstance(last_result, LoginResponse)

        # セッションは1つだけ
        user = await user_repo.get_by_safe_username("testuser")
        assert user is not None
        stored = await session_store.get_by_user(user.id)
        assert stored is not None

        # 最後のトークンのみ有効
        assert isinstance(last_result, LoginResponse)
        assert await session_store.exists(last_result.token) is True


# ── Server error handling (Req 10.3) ──────────────────────────────────


class TestLoginServerError:
    """予期しない例外で SERVER_ERROR を返す。"""

    async def test_unexpected_exception_returns_server_error(self) -> None:
        user_repo = InMemoryUserRepository()
        role_repo = InMemoryRoleRepository(seed_roles=[ROLE_DEFAULT])
        session_store = InMemorySessionStore()
        password_service = PasswordService(hibp_client=None, banned_passwords=[])
        permission_service = PermissionService(role_repo=role_repo)
        country_resolver = _StubCountryResolver()

        svc = AuthService(
            user_repo=user_repo,
            role_repo=role_repo,
            password_service=password_service,
            permission_service=permission_service,
            session_store=session_store,
            country_resolver=country_resolver,
        )

        # register a user first
        result = await svc.register(
            RegistrationForm(
                username="ErrorUser",
                email="error@example.com",
                password=_LOGIN_PASSWORD,
            ),
        )
        assert result.success is True

        # user_repo.get_by_safe_username を例外に差し替え
        user_repo.get_by_safe_username = AsyncMock(  # type: ignore[method-assign]
            side_effect=RuntimeError("DB connection lost"),
        )

        login_result = await svc.login(
            _fake_request(),
            _login_request(username="ErrorUser"),
        )
        assert login_result is LoginResult.SERVER_ERROR


# ═══════════════════════════════════════════════════════════════════════
# Structured logging テスト (Req 8.1, 8.2, 8.3)
# ═══════════════════════════════════════════════════════════════════════


class TestRegistrationLogging:
    """register() の structlog イベント検証。"""

    async def test_registration_success_emits_log(self) -> None:
        """成功時に registration_success イベントが出力される。"""
        svc, *_ = _make_service()
        with capture_logs() as cap_logs:
            result = await svc.register(_valid_form(username="LogUser", email="log@example.com"))
        assert result.success is True
        events = [e for e in cap_logs if e["event"] == "registration_success"]
        assert len(events) == 1
        assert events[0]["username"] == "LogUser"
        assert "user_id" in events[0]
        assert events[0]["log_level"] == "info"

    async def test_registration_failed_emits_log(self) -> None:
        """バリデーション失敗時に registration_failed イベントが出力される。"""
        svc, *_ = _make_service()
        with capture_logs() as cap_logs:
            result = await svc.register(_valid_form(username="!", email="bad", password="aaa"))
        assert result.success is False
        events = [e for e in cap_logs if e["event"] == "registration_failed"]
        assert len(events) == 1
        assert events[0]["username"] == "!"
        assert "reason" in events[0]
        assert events[0]["log_level"] == "warning"

    async def test_registration_check_only_no_success_log(self) -> None:
        """check_only=True では registration_success は出力されない。"""
        svc, *_ = _make_service()
        with capture_logs() as cap_logs:
            result = await svc.register(_valid_form(), check_only=True)
        assert result.success is True
        events = [e for e in cap_logs if e["event"] == "registration_success"]
        assert len(events) == 0


class TestLoginLogging:
    """login() の structlog イベント検証。"""

    async def test_login_success_emits_log(self) -> None:
        """成功時に login_success イベントが出力される。"""
        svc, *_ = await _make_login_service()
        with capture_logs() as cap_logs:
            result = await svc.login(_fake_request(), _login_request())
        assert isinstance(result, LoginResponse)
        events = [e for e in cap_logs if e["event"] == "login_success"]
        assert len(events) == 1
        assert events[0]["username"] == "TestUser"
        assert events[0]["user_id"] == result.user.id
        assert events[0]["log_level"] == "info"

    async def test_login_failed_user_not_found_emits_log(self) -> None:
        """ユーザー不在時に login_failed イベントが出力される。"""
        svc, *_ = await _make_login_service()
        with capture_logs() as cap_logs:
            result = await svc.login(
                _fake_request(),
                _login_request(username="Ghost"),
            )
        assert result is LoginResult.AUTHENTICATION_FAILED
        events = [e for e in cap_logs if e["event"] == "login_failed"]
        assert len(events) == 1
        assert events[0]["username"] == "Ghost"
        assert events[0]["reason"] == "authentication_failed"
        assert events[0]["log_level"] == "warning"

    async def test_login_failed_wrong_password_emits_log(self) -> None:
        """パスワード不一致時に login_failed イベントが出力される。"""
        svc, *_ = await _make_login_service()
        with capture_logs() as cap_logs:
            result = await svc.login(
                _fake_request(),
                _login_request(password_md5="0" * 32),
            )
        assert result is LoginResult.AUTHENTICATION_FAILED
        events = [e for e in cap_logs if e["event"] == "login_failed"]
        assert len(events) == 1
        assert events[0]["username"] == "TestUser"
        assert events[0]["reason"] == "authentication_failed"

    async def test_login_server_error_emits_structured_log(self) -> None:
        """予期しない例外時に login_error イベントが structlog 形式で出力される。"""
        user_repo = InMemoryUserRepository()
        role_repo = InMemoryRoleRepository(seed_roles=[ROLE_DEFAULT])
        session_store = InMemorySessionStore()
        password_service = PasswordService(hibp_client=None, banned_passwords=[])
        permission_service = PermissionService(role_repo=role_repo)
        country_resolver = _StubCountryResolver()

        svc = AuthService(
            user_repo=user_repo,
            role_repo=role_repo,
            password_service=password_service,
            permission_service=permission_service,
            session_store=session_store,
            country_resolver=country_resolver,
        )

        result = await svc.register(
            RegistrationForm(
                username="ErrLogUser",
                email="errlog@example.com",
                password=_LOGIN_PASSWORD,
            ),
        )
        assert result.success is True

        user_repo.get_by_safe_username = AsyncMock(  # type: ignore[method-assign]
            side_effect=RuntimeError("DB connection lost"),
        )

        with capture_logs() as cap_logs:
            login_result = await svc.login(
                _fake_request(),
                _login_request(username="ErrLogUser"),
            )
        assert login_result is LoginResult.SERVER_ERROR
        events = [e for e in cap_logs if e["event"] == "login_error"]
        assert len(events) == 1
        assert events[0]["username"] == "ErrLogUser"
        assert events[0]["log_level"] == "error"
