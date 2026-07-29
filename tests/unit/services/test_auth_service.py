"""AuthService の登録とログイン契約を検証するユニットテスト.

in-memory repository と session store を利用し PasswordService は実インスタンスで検証する.
"""

from __future__ import annotations

import hashlib
from datetime import UTC, datetime
from typing import final

from structlog.testing import capture_logs

from osu_server.domain.identity.authentication import (
    ClientInfo,
    LoginRequest,
    LoginResponse,
    LoginResult,
    RegistrationForm,
    RegistrationResult,
)
from osu_server.domain.identity.authorization import Privileges
from osu_server.domain.identity.roles import Role
from osu_server.domain.identity.sessions import SessionData
from osu_server.domain.identity.users import User
from osu_server.repositories.memory.queries import (
    InMemoryRoleQueryRepository,
    InMemoryUserQueryRepository,
)
from osu_server.repositories.memory.session_store import InMemorySessionStore
from osu_server.repositories.memory.unit_of_work import InMemoryUnitOfWorkFactory
from osu_server.services.commands.identity.auth_service import AuthService
from osu_server.services.queries.identity.password_service import PasswordService
from osu_server.services.queries.identity.permission_service import PermissionService
from tests.support.fakes import ErrorRaisingUserRepository, FakeHIBPClient

# ── Default country for login tests ──────────────────────────────────

_DEFAULT_COUNTRY = "JP"

# ── Seed data ────────────────────────────────────────────────────────


def _md5_hex(s: str) -> str:
    """テスト入力の文字列から MD5 の16進値を生成する.

    Args:
        s (str): MD5へ変換する平文の入力値.

    Returns:
        str: security用途ではない MD5 の16進表現.

    Notes:
        既存の認証clientが送信する MD5 値をfixtureとして再現するためだけに使用する.
    """
    return hashlib.md5(s.encode(), usedforsecurity=False).hexdigest()


ROLE_DEFAULT = Role(
    id=1,
    name="Default",
    permissions=Privileges.NORMAL | Privileges.VERIFIED | Privileges.UNRESTRICTED,
    position=0,
)


def _make_service(
    *,
    banned_passwords: list[str] | None = None,
) -> tuple[
    AuthService,
    InMemoryUserQueryRepository,
    InMemoryRoleQueryRepository,
    InMemoryUnitOfWorkFactory,
]:
    """登録テスト用の AuthService と in-memory 依存を構築する.

    Args:
        banned_passwords (list[str] | None): 登録時に拒否する追加のパスワード一覧.

    Returns:
        tuple: 以下の順で返す依存.
            AuthService, user query repository, role query repository, unit of work factory.
    """
    uow_factory = InMemoryUnitOfWorkFactory()
    uow_factory.seed_roles([ROLE_DEFAULT])

    user_query_repo = InMemoryUserQueryRepository(uow_factory)
    role_query_repo = InMemoryRoleQueryRepository(uow_factory)
    session_store = InMemorySessionStore()
    password_service = PasswordService(
        hibp_client=None,
        banned_passwords=banned_passwords or [],
    )
    permission_service = PermissionService(role_repo=role_query_repo)

    svc = AuthService(
        uow_factory=uow_factory,
        user_query_repo=user_query_repo,
        role_query_repo=role_query_repo,
        password_service=password_service,
        permission_service=permission_service,
        session_store=session_store,
    )
    return svc, user_query_repo, role_query_repo, uow_factory


def _valid_form(
    *,
    username: str = "TestUser",
    email: str = "test@example.com",
    password: str = "SecurePass1234",
) -> RegistrationForm:
    """登録成功に使える既定値の RegistrationForm を生成する.

    Args:
        username (str): formへ設定するユーザー名.
        email (str): formへ設定するメールアドレス.
        password (str): formへ設定する平文パスワード.

    Returns:
        RegistrationForm: 指定値を持つ登録request form.
    """
    return RegistrationForm(username=username, email=email, password=password)


@final
class _StaleThenCurrentUserQueryRepository:
    """最初の重複確認だけ stale read を返す user query fake.

    初回readで競合を見せずその後のreadでは内側repositoryの現在値を返して永続化競合を再現する.
    """

    def __init__(self, inner: InMemoryUserQueryRepository) -> None:
        """古いreadを注入するための内側repositoryを設定する.

        Args:
            inner (InMemoryUserQueryRepository): 実際のユーザー状態を保持するrepository.
        """
        self._inner = inner
        self._safe_username_reads = 0
        self._email_reads = 0

    async def get_by_id(self, user_id: int) -> User | None:
        """ユーザーID検索を内側repositoryへ委譲する.

        Args:
            user_id (int): 取得するユーザーの識別子.

        Returns:
            User | None: 内側repositoryが返すユーザー. 見つからない場合はNone.
        """
        return await self._inner.get_by_id(user_id)

    async def get_by_safe_username(self, safe_username: str) -> User | None:
        """初回だけユーザーなしを返し以降は現在値を返す.

        Args:
            safe_username (str): 正規化済みの検索対象ユーザー名.

        Returns:
            User | None: 初回はNone. 2回目以降は内側repositoryの検索結果.
        """
        self._safe_username_reads += 1
        if self._safe_username_reads == 1:
            return None
        return await self._inner.get_by_safe_username(safe_username)

    async def get_by_email(self, email: str) -> User | None:
        """初回だけメールアドレス未登録を返し以降は現在値を返す.

        Args:
            email (str): 小文字化済みの検索対象メールアドレス.

        Returns:
            User | None: 初回はNone. 2回目以降は内側repositoryの検索結果.
        """
        self._email_reads += 1
        if self._email_reads == 1:
            return None
        return await self._inner.get_by_email(email)

    async def is_username_disallowed(self, safe_username: str) -> bool:
        """禁止ユーザー名の検索を内側repositoryへ委譲する.

        Args:
            safe_username (str): 禁止判定する正規化済みユーザー名.

        Returns:
            bool: 内側repositoryが返す禁止判定結果.
        """
        return await self._inner.is_username_disallowed(safe_username)


async def _seed_existing_registration(
    *,
    uow_factory: InMemoryUnitOfWorkFactory,
    password_service: PasswordService,
    form: RegistrationForm,
) -> None:
    """登録済みユーザーを command state へ直接投入する.

    Args:
        uow_factory (InMemoryUnitOfWorkFactory): stateを保持するunit of work factory.
        password_service (PasswordService): 保存用password hashを生成するservice.
        form (RegistrationForm): 登録済み状態として投入するform.

    Returns:
        None: ユーザーと既定roleを永続化して完了する.
    """
    now = datetime.now(UTC)
    password_hash = await password_service.prepare_password(form.password)
    async with uow_factory() as uow:
        created = await uow.users.create(
            User(
                id=0,
                username=form.username,
                safe_username=User.normalize_username(form.username),
                email=form.email.lower(),
                password_hash=password_hash,
                country="XX",
                created_at=now,
                updated_at=now,
            )
        )
        await uow.roles.assign_role(created.id, ROLE_DEFAULT.id)
        await uow.commit()


# ── Username validation (Req 3.1, 3.2) ──────────────────────────────


class TestUsernameValidation:
    """ユーザー名の形式, 文字数, 文字種のvalidationを検証するテスト群."""

    async def test_too_short(self) -> None:
        """1文字のユーザー名を登録し, username errorが返る契約を検証する.

        Returns:
            None: 短すぎる入力の拒否結果を検証して完了する.
        """
        svc, *_ = _make_service()
        result = await svc.register(_valid_form(username="A"))
        assert result.success is False
        assert "username" in result.errors

    async def test_too_long(self) -> None:
        """16文字のユーザー名を登録し, username errorが返る契約を検証する.

        Returns:
            None: 長すぎる入力の拒否結果を検証して完了する.
        """
        svc, *_ = _make_service()
        result = await svc.register(_valid_form(username="A" * 16))
        assert result.success is False
        assert "username" in result.errors

    async def test_min_length_boundary(self) -> None:
        """最小長のユーザー名を登録し, 成功する契約を検証する.

        Returns:
            None: 境界値の成功結果を検証して完了する.
        """
        svc, *_ = _make_service()
        result = await svc.register(_valid_form(username="Ab"))
        assert result.success is True

    async def test_max_length_boundary(self) -> None:
        """最大長のユーザー名を登録し, 成功する契約を検証する.

        Returns:
            None: 境界値の成功結果を検証して完了する.
        """
        svc, *_ = _make_service()
        result = await svc.register(_valid_form(username="A" * 15))
        assert result.success is True

    async def test_invalid_characters(self) -> None:
        """許可されない記号を含むユーザー名を拒否する契約を検証する.

        Returns:
            None: 不正文字のusername errorを検証して完了する.
        """
        svc, *_ = _make_service()
        result = await svc.register(_valid_form(username="Test@User!"))
        assert result.success is False
        assert "username" in result.errors

    async def test_space_and_underscore_coexist(self) -> None:
        """空白とunderscoreを併用したユーザー名を拒否する契約を検証する.

        Returns:
            None: 併用入力のusername errorを検証して完了する.
        """
        svc, *_ = _make_service()
        result = await svc.register(_valid_form(username="Test _User"))
        assert result.success is False
        assert "username" in result.errors

    async def test_space_only_allowed(self) -> None:
        """空白のみを含むユーザー名を許可する契約を検証する.

        Returns:
            None: 許可入力の成功結果を検証して完了する.
        """
        svc, *_ = _make_service()
        result = await svc.register(_valid_form(username="Test User"))
        assert result.success is True

    async def test_underscore_only_allowed(self) -> None:
        """underscoreのみを含むユーザー名を許可する契約を検証する.

        Returns:
            None: 許可入力の成功結果を検証して完了する.
        """
        svc, *_ = _make_service()
        result = await svc.register(_valid_form(username="Test_User"))
        assert result.success is True

    async def test_hyphen_allowed(self) -> None:
        """hyphenを含むユーザー名を許可する契約を検証する.

        Returns:
            None: 許可入力の成功結果を検証して完了する.
        """
        svc, *_ = _make_service()
        result = await svc.register(_valid_form(username="Test-User"))
        assert result.success is True

    async def test_alphanumeric_only(self) -> None:
        """英数字だけのユーザー名を許可する契約を検証する.

        Returns:
            None: 許可入力の成功結果を検証して完了する.
        """
        svc, *_ = _make_service()
        result = await svc.register(_valid_form(username="User123"))
        assert result.success is True

    async def test_empty_username(self) -> None:
        """空のユーザー名を拒否する契約を検証する.

        Returns:
            None: 空入力のusername errorを検証して完了する.
        """
        svc, *_ = _make_service()
        result = await svc.register(_valid_form(username=""))
        assert result.success is False
        assert "username" in result.errors


# ── Password validation (Req 3.3, 3.4) ──────────────────────────────


class TestPasswordValidation:
    """パスワードの文字数とユニーク文字数のvalidationを検証するテスト群."""

    async def test_too_short(self) -> None:
        """最小長未満のパスワードを拒否する契約を検証する.

        Returns:
            None: 短すぎる入力のpassword errorを検証して完了する.
        """
        svc, *_ = _make_service()
        result = await svc.register(_valid_form(password="Ab1cdef"))
        assert result.success is False
        assert "password" in result.errors

    async def test_too_long(self) -> None:
        """最大長超過のパスワードを拒否する契約を検証する.

        Returns:
            None: 長すぎる入力のpassword errorを検証して完了する.
        """
        svc, *_ = _make_service()
        result = await svc.register(_valid_form(password="A" * 33))
        assert result.success is False
        assert "password" in result.errors

    async def test_min_length_boundary(self) -> None:
        """最小長のパスワードを許可する契約を検証する.

        Returns:
            None: 境界値の成功結果を検証して完了する.
        """
        svc, *_ = _make_service()
        result = await svc.register(_valid_form(password="Abcd1234"))
        assert result.success is True

    async def test_max_length_boundary(self) -> None:
        """最大長のパスワードを許可する契約を検証する.

        Returns:
            None: 境界値の成功結果を検証して完了する.
        """
        svc, *_ = _make_service()
        result = await svc.register(_valid_form(password="Abcd" + "x" * 28))
        assert result.success is True

    async def test_insufficient_unique_chars(self) -> None:
        """ユニーク文字が1種類のパスワードを拒否する契約を検証する.

        Returns:
            None: password errorを検証して完了する.
        """
        svc, *_ = _make_service()
        # 'aaa' repeated = only 1 unique char
        result = await svc.register(_valid_form(password="aaaaaaaa"))
        assert result.success is False
        assert "password" in result.errors

    async def test_three_unique_chars_insufficient(self) -> None:
        """ユニーク文字が3種類のパスワードを拒否する契約を検証する.

        Returns:
            None: password errorを検証して完了する.
        """
        svc, *_ = _make_service()
        result = await svc.register(_valid_form(password="aabbccaa"))
        assert result.success is False
        assert "password" in result.errors

    async def test_four_unique_chars_sufficient(self) -> None:
        """ユニーク文字が4種類のパスワードを許可する契約を検証する.

        Returns:
            None: 成功結果を検証して完了する.
        """
        svc, *_ = _make_service()
        result = await svc.register(_valid_form(password="aabbccdd"))
        assert result.success is True

    async def test_length_and_unique_both_fail(self) -> None:
        """短すぎてユニーク文字も不足する入力の複数errorを検証する.

        Returns:
            None: password fieldの複数errorを検証して完了する.
        """
        svc, *_ = _make_service()
        result = await svc.register(_valid_form(password="aaa"))
        assert result.success is False
        assert "password" in result.errors
        min_expected_errors = 2
        assert len(result.errors["password"]) >= min_expected_errors


# ── Email validation (Req 3.5) ───────────────────────────────────────


class TestEmailValidation:
    """メールアドレスの形式validationを検証するテスト群."""

    async def test_valid_email(self) -> None:
        """形式が正しいメールアドレスを許可する契約を検証する.

        Returns:
            None: 成功結果を検証して完了する.
        """
        svc, *_ = _make_service()
        result = await svc.register(_valid_form(email="user@example.com"))
        assert result.success is True

    async def test_missing_at_sign(self) -> None:
        """アットマークを欠くメールアドレスを拒否する契約を検証する.

        Returns:
            None: email errorを検証して完了する.
        """
        svc, *_ = _make_service()
        result = await svc.register(_valid_form(email="userexample.com"))
        assert result.success is False
        assert "email" in result.errors

    async def test_missing_domain(self) -> None:
        """domainを欠くメールアドレスを拒否する契約を検証する.

        Returns:
            None: email errorを検証して完了する.
        """
        svc, *_ = _make_service()
        result = await svc.register(_valid_form(email="user@"))
        assert result.success is False
        assert "email" in result.errors

    async def test_missing_tld(self) -> None:
        """TLDを欠くメールアドレスを拒否する契約を検証する.

        Returns:
            None: email errorを検証して完了する.
        """
        svc, *_ = _make_service()
        result = await svc.register(_valid_form(email="user@example"))
        assert result.success is False
        assert "email" in result.errors

    async def test_empty_email(self) -> None:
        """空のメールアドレスを拒否する契約を検証する.

        Returns:
            None: email errorを検証して完了する.
        """
        svc, *_ = _make_service()
        result = await svc.register(_valid_form(email=""))
        assert result.success is False
        assert "email" in result.errors

    async def test_spaces_in_email(self) -> None:
        """空白を含むメールアドレスを拒否する契約を検証する.

        Returns:
            None: email errorを検証して完了する.
        """
        svc, *_ = _make_service()
        result = await svc.register(_valid_form(email="user @example.com"))
        assert result.success is False
        assert "email" in result.errors


# ── Duplicate checks (Req 1.5, 1.6) ─────────────────────────────────


class TestDuplicateChecks:
    """重複したユーザー名とメールアドレスの検出を検証するテスト群."""

    async def test_duplicate_username(self) -> None:
        """同じユーザー名の再登録を拒否する契約を検証する.

        Returns:
            None: username errorを検証して完了する.
        """
        svc, *_ = _make_service()
        _ = await svc.register(_valid_form(username="ExistingUser", email="first@example.com"))
        result = await svc.register(
            _valid_form(username="ExistingUser", email="second@example.com")
        )
        assert result.success is False
        assert "username" in result.errors

    async def test_duplicate_username_normalized(self) -> None:
        """正規化後に重複するユーザー名の再登録を拒否する契約を検証する.

        Returns:
            None: username errorを検証して完了する.
        """
        svc, *_ = _make_service()
        _ = await svc.register(_valid_form(username="Test User", email="first@example.com"))
        result = await svc.register(_valid_form(username="test_user", email="second@example.com"))
        assert result.success is False
        assert "username" in result.errors

    async def test_duplicate_email(self) -> None:
        """同じメールアドレスの再登録を拒否する契約を検証する.

        Returns:
            None: email errorを検証して完了する.
        """
        svc, *_ = _make_service()
        _ = await svc.register(_valid_form(username="User1", email="same@example.com"))
        result = await svc.register(_valid_form(username="User2", email="same@example.com"))
        assert result.success is False
        assert "email" in result.errors

    async def test_duplicate_email_case_insensitive(self) -> None:
        """大文字小文字だけが異なる重複メールを拒否する契約を検証する.

        Returns:
            None: email errorを検証して完了する.
        """
        svc, *_ = _make_service()
        _ = await svc.register(_valid_form(username="User1", email="Test@Example.COM"))
        result = await svc.register(_valid_form(username="User2", email="test@example.com"))
        assert result.success is False
        assert "email" in result.errors

    async def test_duplicate_final_submit_same_credentials_is_idempotent(self) -> None:
        """同一credentialsの登録再送を成功として扱う契約を検証する.

        Returns:
            None: idempotentな成功結果を検証して完了する.
        """
        svc, *_ = _make_service()
        form = _valid_form(username="RetryUser", email="retry@example.com")

        first_result = await svc.register(form)
        second_result = await svc.register(form)

        assert first_result.success is True
        assert second_result.success is True
        assert second_result.errors == {}

    async def test_duplicate_final_submit_wrong_password_still_fails(self) -> None:
        """既存ユーザーとpasswordが異なる再送を成功にしない契約を検証する.

        Returns:
            None: usernameとemailのerrorを検証して完了する.
        """
        svc, *_ = _make_service()
        _ = await svc.register(_valid_form(username="RetryUser", email="retry@example.com"))

        result = await svc.register(
            _valid_form(
                username="RetryUser",
                email="retry@example.com",
                password="Different1234",
            )
        )

        assert result.success is False
        assert set(result.errors) == {"username", "email"}

    async def test_persistence_username_conflict_same_credentials_is_idempotent(
        self,
    ) -> None:
        """read後のusername競合でも同一再送を成功にする契約を検証する.

        Returns:
            None: persistence競合後のidempotentな成功結果を検証して完了する.
        """
        uow_factory = InMemoryUnitOfWorkFactory()
        uow_factory.seed_roles([ROLE_DEFAULT])
        inner_user_query_repo = InMemoryUserQueryRepository(uow_factory)
        user_query_repo = _StaleThenCurrentUserQueryRepository(inner_user_query_repo)
        role_query_repo = InMemoryRoleQueryRepository(uow_factory)
        password_service = PasswordService(hibp_client=None, banned_passwords=[])
        form = _valid_form(username="RetryUser", email="retry@example.com")
        await _seed_existing_registration(
            uow_factory=uow_factory,
            password_service=password_service,
            form=form,
        )
        svc = AuthService(
            uow_factory=uow_factory,
            user_query_repo=user_query_repo,
            role_query_repo=role_query_repo,
            password_service=password_service,
            permission_service=PermissionService(role_repo=role_query_repo),
            session_store=InMemorySessionStore(),
        )

        result = await svc.register(form)

        assert result.success is True
        assert result.errors == {}


# ── Disallowed username (Req 1.7) ────────────────────────────────────


class TestDisallowedUsername:
    """禁止ユーザー名の登録拒否を検証するテスト群."""

    async def test_disallowed_username(self) -> None:
        """禁止一覧にある正規化ユーザー名を拒否する契約を検証する.

        Returns:
            None: username errorを検証して完了する.
        """
        svc, _, _, uow_factory = _make_service()
        async with uow_factory() as uow:
            await uow.users.add_disallowed_username("banned_user")
            await uow.commit()
        result = await svc.register(_valid_form(username="Banned User", email="new@example.com"))
        assert result.success is False
        assert "username" in result.errors

    async def test_allowed_username_passes(self) -> None:
        """禁止一覧にないユーザー名を許可する契約を検証する.

        Returns:
            None: 成功結果を検証して完了する.
        """
        svc, _, _, uow_factory = _make_service()
        async with uow_factory() as uow:
            await uow.users.add_disallowed_username("other_name")
            await uow.commit()
        result = await svc.register(_valid_form(username="AllowedUser", email="new@example.com"))
        assert result.success is True


# ── Password banned (Req 4.4, 4.5) ──────────────────────────────────


class TestPasswordBanned:
    """パスワード禁止判定との統合を検証するテスト群."""

    async def test_password_in_custom_banned_list(self) -> None:
        """custom禁止一覧のパスワードを拒否する契約を検証する.

        Returns:
            None: password errorを検証して完了する.
        """
        svc, *_ = _make_service(banned_passwords=["SecurePass1234"])
        result = await svc.register(_valid_form(password="SecurePass1234"))
        assert result.success is False
        assert "password" in result.errors

    async def test_password_banned_by_hibp(self) -> None:
        """HIBPが侵害済みと返すパスワードを拒否する契約を検証する.

        Returns:
            None: password errorを検証して完了する.
        """
        uow_factory = InMemoryUnitOfWorkFactory()
        uow_factory.seed_roles([ROLE_DEFAULT])
        user_query_repo = InMemoryUserQueryRepository(uow_factory)
        role_query_repo = InMemoryRoleQueryRepository(uow_factory)
        session_store = InMemorySessionStore()
        hibp_client = FakeHIBPClient(compromised_passwords={"SecurePass1234"})
        pw_svc = PasswordService(hibp_client=hibp_client, banned_passwords=[])
        permission_service = PermissionService(role_repo=role_query_repo)
        svc = AuthService(
            uow_factory=uow_factory,
            user_query_repo=user_query_repo,
            role_query_repo=role_query_repo,
            password_service=pw_svc,
            permission_service=permission_service,
            session_store=session_store,
        )
        result = await svc.register(_valid_form())
        assert result.success is False
        assert "password" in result.errors

    async def test_safe_password_passes(self) -> None:
        """禁止一覧にない安全なパスワードを許可する契約を検証する.

        Returns:
            None: 成功結果を検証して完了する.
        """
        svc, *_ = _make_service(banned_passwords=["other_password"])
        result = await svc.register(_valid_form(password="SafePass1234"))
        assert result.success is True


# ── Error accumulation ───────────────────────────────────────────────


class TestErrorAccumulation:
    """複数のvalidation errorを蓄積する登録契約を検証するテスト群."""

    async def test_multiple_field_errors_accumulated(self) -> None:
        """複数fieldが不正なformで全fieldのerrorを返す契約を検証する.

        Returns:
            None: username, email, passwordのerrorを検証して完了する.
        """
        svc, *_ = _make_service()
        result = await svc.register(_valid_form(username="!", email="bad", password="aaa"))
        assert result.success is False
        assert "username" in result.errors
        assert "email" in result.errors
        assert "password" in result.errors

    async def test_result_type_is_registration_result(self) -> None:
        """登録結果が RegistrationResult で返る契約を検証する.

        Returns:
            None: 結果の型を検証して完了する.
        """
        svc, *_ = _make_service()
        result = await svc.register(_valid_form())
        assert isinstance(result, RegistrationResult)


# ── check_only mode (Req 2.1, 2.2) ──────────────────────────────────


class TestCheckOnlyMode:
    """check_only modeでvalidationだけを実行する契約を検証するテスト群."""

    async def test_check_only_valid_no_user_created(self) -> None:
        """有効formのcheck_onlyでユーザーを作成しない契約を検証する.

        Returns:
            None: 成功結果と未作成状態を検証して完了する.
        """
        svc, user_repo, _, _ = _make_service()
        result = await svc.register(_valid_form(), check_only=True)
        assert result.success is True
        assert result.errors == {}
        # ユーザーは作成されていない
        user = await user_repo.get_by_safe_username("testuser")
        assert user is None

    async def test_check_only_invalid_returns_errors(self) -> None:
        """不正formのcheck_onlyでvalidation errorを返す契約を検証する.

        Returns:
            None: username errorを検証して完了する.
        """
        svc, *_ = _make_service()
        result = await svc.register(_valid_form(username="!"), check_only=True)
        assert result.success is False
        assert "username" in result.errors

    async def test_check_only_duplicate_detected(self) -> None:
        """重複formのcheck_onlyで重複errorを返す契約を検証する.

        Returns:
            None: username errorを検証して完了する.
        """
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
    """成功する登録で作成されるユーザーとroleを検証するテスト群."""

    async def test_user_created_in_repository(self) -> None:
        """有効formの登録がrepositoryへユーザーを作成する契約を検証する.

        Returns:
            None: 保存済みユーザーのfieldを検証して完了する.
        """
        svc, user_repo, _, _ = _make_service()
        result = await svc.register(_valid_form(username="NewUser", email="new@example.com"))
        assert result.success is True
        assert result.errors == {}
        user = await user_repo.get_by_safe_username("newuser")
        assert user is not None
        assert user.username == "NewUser"
        assert user.email == "new@example.com"

    async def test_safe_username_normalized(self) -> None:
        """safe_usernameを小文字とunderscoreへ正規化する契約を検証する.

        Returns:
            None: 保存済みsafe_usernameを検証して完了する.
        """
        svc, user_repo, _, _ = _make_service()
        _ = await svc.register(_valid_form(username="My User", email="u@example.com"))
        user = await user_repo.get_by_safe_username("my_user")
        assert user is not None
        assert user.safe_username == "my_user"

    async def test_password_stored_as_argon2id(self) -> None:
        """パスワードを argon2id hashとして保存する契約を検証する.

        Returns:
            None: 保存済みpassword hashの形式を検証して完了する.
        """
        svc, user_repo, _, _ = _make_service()
        _ = await svc.register(_valid_form(username="HashUser", email="h@example.com"))
        user = await user_repo.get_by_safe_username("hashuser")
        assert user is not None
        assert user.password_hash.startswith("$argon2id$")

    async def test_default_role_assigned(self) -> None:
        """登録成功時に既定roleを割り当てる契約を検証する.

        Returns:
            None: 割り当て済みroleを検証して完了する.
        """
        svc, user_repo, role_repo, _ = _make_service()
        _ = await svc.register(_valid_form(username="RoleUser", email="r@example.com"))
        user = await user_repo.get_by_safe_username("roleuser")
        assert user is not None
        roles = await role_repo.get_roles_for_user(user.id)
        assert len(roles) == 1
        assert roles[0].name == "Default"

    async def test_verified_flag_via_default_role(self) -> None:
        """既定roleが VERIFIED privilegeを与える契約を検証する.

        Returns:
            None: 合成したprivilegeに VERIFIED があることを検証して完了する.
        """
        svc, user_repo, role_repo, _ = _make_service()
        _ = await svc.register(_valid_form(username="VerUser", email="v@example.com"))
        user = await user_repo.get_by_safe_username("veruser")
        assert user is not None
        roles = await role_repo.get_roles_for_user(user.id)
        combined = Privileges.NONE
        for role in roles:
            combined |= role.permissions
        assert Privileges.VERIFIED in combined

    async def test_success_result_structure(self) -> None:
        """成功した登録が空のerrorを持つ結果を返す契約を検証する.

        Returns:
            None: success flagとerror集合を検証して完了する.
        """
        svc, *_ = _make_service()
        result = await svc.register(_valid_form())
        assert result.success is True
        assert result.errors == {}

    async def test_plaintext_password_not_stored(self) -> None:
        """平文と MD5 をpassword hashとして保存しない契約を検証する.

        Returns:
            None: 保存済みhashが両方の入力値と異なることを検証して完了する.
        """
        svc, user_repo, _, _ = _make_service()
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


def _login_request(
    *,
    username: str = "TestUser",
    password_md5: str = _LOGIN_PASSWORD_MD5,
) -> LoginRequest:
    """ログインテスト用の LoginRequest を既定client情報付きで生成する.

    Args:
        username (str): ログインするユーザー名.
        password_md5 (str): clientが送信する MD5 password hash.

    Returns:
        LoginRequest: 指定credentialsと既定client情報を持つrequest.
    """
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


async def _make_login_service() -> tuple[
    AuthService,
    InMemoryUserQueryRepository,
    InMemoryRoleQueryRepository,
    InMemorySessionStore,
    PermissionService,
    InMemoryUnitOfWorkFactory,
]:
    """ログインテスト用の AuthService と登録済みユーザーを構築する.

    Returns:
        tuple: 以下の順で返す依存.
            AuthService, user query repository, role query repository, session store,
            permission service, unit of work factory.
    """
    uow_factory = InMemoryUnitOfWorkFactory()
    uow_factory.seed_roles([ROLE_DEFAULT])

    user_query_repo = InMemoryUserQueryRepository(uow_factory)
    role_query_repo = InMemoryRoleQueryRepository(uow_factory)
    session_store = InMemorySessionStore()
    password_service = PasswordService(hibp_client=None, banned_passwords=[])
    permission_service = PermissionService(role_repo=role_query_repo)

    svc = AuthService(
        uow_factory=uow_factory,
        user_query_repo=user_query_repo,
        role_query_repo=role_query_repo,
        password_service=password_service,
        permission_service=permission_service,
        session_store=session_store,
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

    return svc, user_query_repo, role_query_repo, session_store, permission_service, uow_factory


# ── Login success (Req 5.1, 5.4, 5.5, 10.1) ──────────────────────────


class TestLoginSuccess:
    """ログイン成功時の LoginResponse とsession状態を検証するテスト群."""

    async def test_returns_login_response(self) -> None:
        """有効credentialsのログインが LoginResponse を返す契約を検証する.

        Returns:
            None: 結果の型を検証して完了する.
        """
        svc, *_ = await _make_login_service()
        result = await svc.login(_login_request(), country=_DEFAULT_COUNTRY)
        assert isinstance(result, LoginResponse)

    async def test_token_is_nonempty_string(self) -> None:
        """成功したログインが空ではないtokenを返す契約を検証する.

        Returns:
            None: tokenの型と長さを検証して完了する.
        """
        svc, *_ = await _make_login_service()
        result = await svc.login(_login_request(), country=_DEFAULT_COUNTRY)
        assert isinstance(result, LoginResponse)
        assert isinstance(result.token, str)
        assert len(result.token) > 0

    async def test_user_field_matches(self) -> None:
        """ログインresponseのuserが保存済みユーザーと一致する契約を検証する.

        Returns:
            None: user IDとusernameを検証して完了する.
        """
        svc, user_repo, *_ = await _make_login_service()
        result = await svc.login(_login_request(), country=_DEFAULT_COUNTRY)
        assert isinstance(result, LoginResponse)
        user = await user_repo.get_by_safe_username("testuser")
        assert user is not None
        assert result.user.id == user.id
        assert result.user.username == "TestUser"

    async def test_privileges_computed(self) -> None:
        """ログインresponseが既定role由来のprivilegeを返す契約を検証する.

        Returns:
            None: 計算済みprivilege集合を検証して完了する.
        """
        svc, *_ = await _make_login_service()
        result = await svc.login(_login_request(), country=_DEFAULT_COUNTRY)
        assert isinstance(result, LoginResponse)
        expected = Privileges.NORMAL | Privileges.VERIFIED | Privileges.UNRESTRICTED
        assert result.privileges == expected

    async def test_country_resolved(self) -> None:
        """ログインresponseが指定countryを返す契約を検証する.

        Returns:
            None: country fieldを検証して完了する.
        """
        svc, *_ = await _make_login_service()
        result = await svc.login(_login_request(), country="JP")
        assert isinstance(result, LoginResponse)
        assert result.country == "JP"

    async def test_session_data_populated(self) -> None:
        """ログインresponseのsession dataがclient情報を保持する契約を検証する.

        Returns:
            None: session dataの全fieldを検証して完了する.
        """
        svc, user_repo, *_ = await _make_login_service()
        result = await svc.login(_login_request(), country=_DEFAULT_COUNTRY)
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
        assert result.session_data.role_ids == (ROLE_DEFAULT.id,)

    async def test_session_stored_in_session_store(self) -> None:
        """成功したログインがsession storeへsessionを保存する契約を検証する.

        Returns:
            None: 保存済みsessionのrole IDsを検証して完了する.
        """
        svc, user_repo, _, session_store, _, _ = await _make_login_service()
        result = await svc.login(_login_request(), country=_DEFAULT_COUNTRY)
        assert isinstance(result, LoginResponse)
        user = await user_repo.get_by_safe_username("testuser")
        assert user is not None
        stored = await session_store.get_by_user(user.id)
        assert stored is not None
        assert stored.role_ids == result.role_ids

    async def test_session_retrievable_by_token(self) -> None:
        """成功したログインのtokenでsessionを取得できる契約を検証する.

        Returns:
            None: tokenによるsession取得結果を検証して完了する.
        """
        svc, _, _, session_store, _, _ = await _make_login_service()
        result = await svc.login(_login_request(), country=_DEFAULT_COUNTRY)
        assert isinstance(result, LoginResponse)
        stored = await session_store.get(result.token)
        assert stored is not None


# ── Login failure: user not found (Req 5.2) ───────────────────────────


class TestLoginUserNotFound:
    """存在しないユーザー名でのログイン失敗を検証するテスト群."""

    async def test_returns_authentication_failed(self) -> None:
        """存在しないユーザー名で authentication failureを返す契約を検証する.

        Returns:
            None: Authentication failed結果を検証して完了する.
        """
        svc, *_ = await _make_login_service()
        result = await svc.login(
            _login_request(username="NonExistent"),
            country=_DEFAULT_COUNTRY,
        )
        assert result is LoginResult.AUTHENTICATION_FAILED

    async def test_no_information_leak(self) -> None:
        """ユーザー不在とpassword不一致を同じ結果にする契約を検証する.

        Returns:
            None: 両方の Authentication failed結果が同じことを検証して完了する.
        """
        svc, *_ = await _make_login_service()
        not_found = await svc.login(
            _login_request(username="NoSuchUser"),
            country=_DEFAULT_COUNTRY,
        )
        wrong_pass = await svc.login(
            _login_request(password_md5="0" * 32),
            country=_DEFAULT_COUNTRY,
        )
        assert not_found == wrong_pass == LoginResult.AUTHENTICATION_FAILED


# ── Login failure: password mismatch (Req 5.2, 5.3) ──────────────────


class TestLoginPasswordMismatch:
    """正しいユーザー名と誤ったpasswordでのログイン失敗を検証するテスト群."""

    async def test_returns_authentication_failed(self) -> None:
        """password不一致で authentication failureを返す契約を検証する.

        Returns:
            None: Authentication failed結果を検証して完了する.
        """
        svc, *_ = await _make_login_service()
        result = await svc.login(
            _login_request(password_md5="0" * 32),
            country=_DEFAULT_COUNTRY,
        )
        assert result is LoginResult.AUTHENTICATION_FAILED

    async def test_no_session_created(self) -> None:
        """password不一致でsessionを作成しない契約を検証する.

        Returns:
            None: session storeに値がないことを検証して完了する.
        """
        svc, user_repo, _, session_store, _, _ = await _make_login_service()
        _ = await svc.login(
            _login_request(password_md5="0" * 32),
            country=_DEFAULT_COUNTRY,
        )
        user = await user_repo.get_by_safe_username("testuser")
        assert user is not None
        stored = await session_store.get_by_user(user.id)
        assert stored is None


# ── Re-login: old session replaced (Req 5.7, 5.8) ────────────────────


class TestLoginSessionReplacement:
    """再ログインで旧sessionを置き換える契約を検証するテスト群."""

    async def test_old_session_replaced_by_new(self) -> None:
        """再ログインが異なるtokenを発行して旧tokenを無効にする契約を検証する.

        Returns:
            None: 旧tokenの失効と新tokenの有効性を検証して完了する.
        """
        svc, _, _, session_store, _, _ = await _make_login_service()
        first = await svc.login(_login_request(), country=_DEFAULT_COUNTRY)
        assert isinstance(first, LoginResponse)
        first_token = first.token

        second = await svc.login(_login_request(), country=_DEFAULT_COUNTRY)
        assert isinstance(second, LoginResponse)
        second_token = second.token

        # トークンが異なること
        assert first_token != second_token

        # 旧トークンは無効化されている
        assert await session_store.exists(first_token) is False

        # 新トークンは有効
        assert await session_store.exists(second_token) is True

    async def test_only_one_session_per_user(self) -> None:
        """同一ユーザーの有効sessionを1件に保つ契約を検証する.

        Returns:
            None: 最終tokenだけが有効なsession状態を検証して完了する.
        """
        svc, user_repo, _, session_store, _, _ = await _make_login_service()

        # 3回ログイン
        last_result: LoginResponse | LoginResult | None = None
        for _ in range(3):
            last_result = await svc.login(_login_request(), country=_DEFAULT_COUNTRY)
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
    """予期しない例外で SERVER_ERROR を返す契約を検証するテスト群."""

    async def test_unexpected_exception_returns_server_error(self) -> None:
        """ユーザーqueryの予期しない例外を SERVER_ERROR へ変換する契約を検証する.

        Returns:
            None: server error結果を検証して完了する.
        """
        uow_factory = InMemoryUnitOfWorkFactory()
        uow_factory.seed_roles([ROLE_DEFAULT])
        inner_repo = InMemoryUserQueryRepository(uow_factory)
        user_repo = ErrorRaisingUserRepository(
            inner=inner_repo,
            error=RuntimeError("DB connection lost"),
        )
        role_query_repo = InMemoryRoleQueryRepository(uow_factory)
        session_store = InMemorySessionStore()
        password_service = PasswordService(hibp_client=None, banned_passwords=[])
        permission_service = PermissionService(role_repo=role_query_repo)

        svc = AuthService(
            uow_factory=uow_factory,
            user_query_repo=user_repo,
            role_query_repo=role_query_repo,
            password_service=password_service,
            permission_service=permission_service,
            session_store=session_store,
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

        # Arm the repository to raise on get_by_safe_username
        user_repo.arm()

        login_result = await svc.login(
            _login_request(username="ErrorUser"),
            country=_DEFAULT_COUNTRY,
        )
        assert login_result is LoginResult.SERVER_ERROR


# ═══════════════════════════════════════════════════════════════════════
# Structured logging テスト (Req 8.1, 8.2, 8.3)
# ═══════════════════════════════════════════════════════════════════════


class TestRegistrationLogging:
    """register() が出力するstructlog eventを検証するテスト群."""

    async def test_registration_success_emits_log(self) -> None:
        """登録成功時に registration_success eventを出力する契約を検証する.

        Returns:
            None: success eventのfieldを検証して完了する.
        """
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
        """validation失敗時に registration_failed eventを出力する契約を検証する.

        Returns:
            None: failure eventからsecretが漏れないことを検証して完了する.
        """
        svc, *_ = _make_service()
        with capture_logs() as cap_logs:
            result = await svc.register(_valid_form(username="!", email="bad", password="aaa"))
        assert result.success is False
        events = [e for e in cap_logs if e["event"] == "registration_failed"]
        assert len(events) == 1
        assert events[0]["username"] == "!"
        assert events[0]["reason"] == "validation_errors"
        assert events[0]["failed_fields"] == ["email", "password", "username"]
        assert events[0]["check_only"] is False
        assert "email" not in events[0]
        assert "password" not in events[0]
        assert events[0]["log_level"] == "warning"

    async def test_duplicate_failure_log_identifies_failed_fields(self) -> None:
        """重複登録失敗logがfailed fieldsを示しsecretを出さない契約を検証する.

        Returns:
            None: failure eventのreasonと非秘匿性を検証して完了する.
        """
        svc, *_ = _make_service()
        form = _valid_form(username="LogUser", email="log@example.com")
        _ = await svc.register(form)

        with capture_logs() as cap_logs:
            result = await svc.register(
                _valid_form(
                    username="LogUser",
                    email="log@example.com",
                    password="Different1234",
                )
            )

        assert result.success is False
        events = [e for e in cap_logs if e["event"] == "registration_failed"]
        assert len(events) == 1
        assert events[0]["username"] == "LogUser"
        assert events[0]["reason"] == "validation_errors"
        assert events[0]["failed_fields"] == ["email", "username"]
        assert events[0]["check_only"] is False
        assert "email" not in events[0]
        assert "password" not in events[0]
        assert events[0]["log_level"] == "warning"

    async def test_registration_check_only_no_success_log(self) -> None:
        """check_onlyの成功で registration_success eventを出力しない契約を検証する.

        Returns:
            None: success eventがないことを検証して完了する.
        """
        svc, *_ = _make_service()
        with capture_logs() as cap_logs:
            result = await svc.register(_valid_form(), check_only=True)
        assert result.success is True
        events = [e for e in cap_logs if e["event"] == "registration_success"]
        assert len(events) == 0


class TestLoginLogging:
    """login() が出力するstructlog eventを検証するテスト群."""

    async def test_login_success_emits_log(self) -> None:
        """ログイン成功時に login_success eventを出力する契約を検証する.

        Returns:
            None: success eventのfieldを検証して完了する.
        """
        svc, *_ = await _make_login_service()
        with capture_logs() as cap_logs:
            result = await svc.login(_login_request(), country=_DEFAULT_COUNTRY)
        assert isinstance(result, LoginResponse)
        events = [e for e in cap_logs if e["event"] == "login_success"]
        assert len(events) == 1
        assert events[0]["username"] == "TestUser"
        assert events[0]["user_id"] == result.user.id
        assert events[0]["log_level"] == "info"

    async def test_login_failed_user_not_found_emits_log(self) -> None:
        """ユーザー不在時に login_failed eventを出力する契約を検証する.

        Returns:
            None: failure eventのreasonを検証して完了する.
        """
        svc, *_ = await _make_login_service()
        with capture_logs() as cap_logs:
            result = await svc.login(
                _login_request(username="Ghost"),
                country=_DEFAULT_COUNTRY,
            )
        assert result is LoginResult.AUTHENTICATION_FAILED
        events = [e for e in cap_logs if e["event"] == "login_failed"]
        assert len(events) == 1
        assert events[0]["username"] == "Ghost"
        assert events[0]["reason"] == "authentication_failed"
        assert events[0]["log_level"] == "warning"

    async def test_login_failed_wrong_password_emits_log(self) -> None:
        """password不一致時に login_failed eventを出力する契約を検証する.

        Returns:
            None: failure eventのusernameとreasonを検証して完了する.
        """
        svc, *_ = await _make_login_service()
        with capture_logs() as cap_logs:
            result = await svc.login(
                _login_request(password_md5="0" * 32),
                country=_DEFAULT_COUNTRY,
            )
        assert result is LoginResult.AUTHENTICATION_FAILED
        events = [e for e in cap_logs if e["event"] == "login_failed"]
        assert len(events) == 1
        assert events[0]["username"] == "TestUser"
        assert events[0]["reason"] == "authentication_failed"

    async def test_login_server_error_emits_structured_log(self) -> None:
        """予期しない例外時に login_error eventを出力する契約を検証する.

        Returns:
            None: error eventのusernameとlog levelを検証して完了する.
        """
        uow_factory = InMemoryUnitOfWorkFactory()
        uow_factory.seed_roles([ROLE_DEFAULT])
        inner_repo = InMemoryUserQueryRepository(uow_factory)
        user_repo = ErrorRaisingUserRepository(
            inner=inner_repo,
            error=RuntimeError("DB connection lost"),
        )
        role_query_repo = InMemoryRoleQueryRepository(uow_factory)
        session_store = InMemorySessionStore()
        password_service = PasswordService(hibp_client=None, banned_passwords=[])
        permission_service = PermissionService(role_repo=role_query_repo)

        svc = AuthService(
            uow_factory=uow_factory,
            user_query_repo=user_repo,
            role_query_repo=role_query_repo,
            password_service=password_service,
            permission_service=permission_service,
            session_store=session_store,
        )

        result = await svc.register(
            RegistrationForm(
                username="ErrLogUser",
                email="errlog@example.com",
                password=_LOGIN_PASSWORD,
            ),
        )
        assert result.success is True

        # Arm the repository to raise on get_by_safe_username
        user_repo.arm()

        with capture_logs() as cap_logs:
            login_result = await svc.login(
                _login_request(username="ErrLogUser"),
                country=_DEFAULT_COUNTRY,
            )
        assert login_result is LoginResult.SERVER_ERROR
        events = [e for e in cap_logs if e["event"] == "login_error"]
        assert len(events) == 1
        assert events[0]["username"] == "ErrLogUser"
        assert events[0]["log_level"] == "error"
