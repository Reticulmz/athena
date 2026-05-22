"""AuthService.register() のユニットテスト。

TDD RED -> GREEN -> REFACTOR で実装。
InMemoryUserRepository / InMemoryRoleRepository を使用し、
PasswordService は実インスタンス(is_password_banned のみ mock する場合あり)。
"""

from __future__ import annotations

import hashlib
from unittest.mock import AsyncMock

from osu_server.domain.auth import RegistrationForm, RegistrationResult
from osu_server.domain.role import Privileges, Role
from osu_server.repositories.memory.role_repository import InMemoryRoleRepository
from osu_server.repositories.memory.user_repository import InMemoryUserRepository
from osu_server.services.auth_service import AuthService
from osu_server.services.password_service import PasswordService

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
