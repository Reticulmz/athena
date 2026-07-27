"""SessionCredentialsQueryUseCaseのlegacy credential確認契約を検証するmodule.

in-memory session storeとrepository/verifier stubを用いて,認証結果とcredentialの
取り扱いを対象にする.
"""

from __future__ import annotations

import hashlib
from datetime import UTC, datetime

from structlog.testing import capture_logs

from osu_server.domain.identity.authentication import LegacyWebAuthFailure, LegacyWebAuthResult
from osu_server.domain.identity.sessions import SessionData
from osu_server.domain.identity.users import User
from osu_server.repositories.memory.session_store import InMemorySessionStore
from osu_server.services.queries.identity import (
    SessionCredentialsQueryInput,
    SessionCredentialsQueryUseCase,
)
from osu_server.services.queries.identity.password_service import PasswordService

_NOW = datetime(2026, 6, 7, tzinfo=UTC)
_PLAIN_PASSWORD = "test_password"
_MD5_HEX = hashlib.md5(_PLAIN_PASSWORD.encode()).hexdigest()
_USERNAME = "TestUser"
_SAFE_USERNAME = User.normalize_username(_USERNAME)


class UserQueryRepositoryStub:
    """Session credential query用のuser lookupを提供するrepository stub.

    Attributes:
        users_by_safe_username (dict[str, User]): safe usernameで検索するuser集合.
        users_by_id (dict[int, User]): user IDで検索するuser集合.
        users_by_email (dict[str, User]): emailで検索するuser集合.
    """

    def __init__(self) -> None:
        """空のuser lookup indexを持つstubを初期化する."""
        self.users_by_safe_username: dict[str, User] = {}
        self.users_by_id: dict[int, User] = {}
        self.users_by_email: dict[str, User] = {}

    async def get_by_id(self, user_id: int) -> User | None:
        """User IDに一致する登録済みuserを返す.

        Args:
            user_id (int): 検索するuserの識別子.

        Returns:
            User | None: IDに対応するuser. 未登録の場合はNone.
        """
        return self.users_by_id.get(user_id)

    async def get_by_safe_username(self, safe_username: str) -> User | None:
        """Safe usernameに一致する登録済みuserを返す.

        Args:
            safe_username (str): 正規化済みusernameの検索値.

        Returns:
            User | None: usernameに対応するuser. 未登録の場合はNone.
        """
        return self.users_by_safe_username.get(safe_username)

    async def get_by_email(self, email: str) -> User | None:
        """Emailに一致する登録済みuserを返す.

        Args:
            email (str): 検索するemail address.

        Returns:
            User | None: emailに対応するuser. 未登録の場合はNone.
        """
        return self.users_by_email.get(email)

    async def is_username_disallowed(self, safe_username: str) -> bool:
        """BanchoBotのsafe usernameだけを禁止状態として返す.

        Args:
            safe_username (str): 禁止判定する正規化済みusername.

        Returns:
            bool: 値がbanchobotの場合はTrue. それ以外はFalse.
        """
        return safe_username == "banchobot"


def _make_user() -> User:
    """Session credential queryで使う未永続化の通常userを作成する.

    Returns:
        User: 固定username,email,timestampを持つtest用user.
    """
    return User(
        id=0,
        username=_USERNAME,
        safe_username=_SAFE_USERNAME,
        email="test@example.com",
        password_hash="",
        country="JP",
        created_at=_NOW,
        updated_at=_NOW,
    )


def _make_session_data(*, user_id: int, username: str = _USERNAME) -> SessionData:
    """指定userに対応するactive session dataを作成する.

    Args:
        user_id (int): sessionを紐付けるuserの識別子.
        username (str): sessionに表示するusername.

    Returns:
        SessionData: legacy client metadataを持つtest用active session.
    """
    return SessionData(
        user_id=user_id,
        username=username,
        privileges=1,
        country="JP",
        osu_version="stable",
        utc_offset=9,
        display_city=False,
        client_hashes="",
        pm_private=False,
    )


async def _make_query_with_user(
    *,
    password_md5: str = _MD5_HEX,
    create_session: bool = True,
) -> tuple[SessionCredentialsQueryUseCase, int]:
    """認証可能なuserと任意のactive sessionを持つquery use caseを作成する.

    Args:
        password_md5 (str): 保存hashへ登録するlegacy password MD5 credential.
        create_session (bool): Trueなら認証成功に必要なactive sessionを作成する.

    Returns:
        tuple[SessionCredentialsQueryUseCase, int]: 構成済みquery use caseと登録済みuser ID.
    """
    user_repo = UserQueryRepositoryStub()
    session_store = InMemorySessionStore()
    password_service = PasswordService(hibp_client=None, banned_passwords=[])

    password_hash = await password_service.hash(password_md5)

    user = _make_user()
    user.password_hash = password_hash
    user.id = 7
    user_repo.users_by_safe_username[user.safe_username] = user
    user_repo.users_by_id[user.id] = user
    user_repo.users_by_email[user.email] = user

    if create_session:
        session_data = _make_session_data(user_id=user.id)
        await session_store.create(
            user_id=user.id,
            token=f"token_{user.id}",
            data=session_data,
        )

    query = SessionCredentialsQueryUseCase(
        user_repository=user_repo,
        password_service=password_service,
        session_store=session_store,
    )
    return query, user.id


async def _authenticate(
    query: SessionCredentialsQueryUseCase,
    *,
    username: str | None,
    password_md5: str | None,
) -> LegacyWebAuthResult:
    """Credential queryを実行してlegacy web authentication結果だけを返す.

    Args:
        query (SessionCredentialsQueryUseCase): 実行するsession credential query use case.
        username (str | None): legacy requestから受け取るusername.
        password_md5 (str | None): legacy requestから受け取るpassword MD5 credential.

    Returns:
        LegacyWebAuthResult: query resultから取り出した認証成功情報または失敗理由.
    """
    result = await query.execute(
        SessionCredentialsQueryInput(username=username, password_md5=password_md5)
    )
    return result.outcome


async def test_authenticate_succeeds_with_valid_credentials_and_session() -> None:
    """有効credentialとactive sessionで認証に成功する契約を検証する.

    Returns:
        None: user ID,username,failure不在の認証結果を検証して完了し,呼び出し側へ値を返さない.
    """
    query, user_id = await _make_query_with_user()

    result = await _authenticate(query, username=_USERNAME, password_md5=_MD5_HEX)

    assert result.user_id == user_id
    assert result.username == _USERNAME
    assert result.failure is None


async def test_authenticate_accepts_uppercase_password_md5() -> None:
    """Legacy web authのpassword MD5 hexを大文字でも認証する契約を検証する.

    Returns:
        None: 大文字MD5 credentialによる認証成功を検証して完了し,呼び出し側へ値を返さない.
    """
    query, user_id = await _make_query_with_user()

    result = await _authenticate(query, username=_USERNAME, password_md5=_MD5_HEX.upper())

    assert result.user_id == user_id
    assert result.username == _USERNAME
    assert result.failure is None


async def test_authenticate_fails_when_username_is_none() -> None:
    """Username未送信時にINVALID_CREDENTIALSを返す契約を検証する.

    Returns:
        None: usernameなしの匿名認証失敗結果を検証して完了し,呼び出し側へ値を返さない.
    """
    query, _ = await _make_query_with_user()

    result = await _authenticate(query, username=None, password_md5=_MD5_HEX)

    assert result.user_id is None
    assert result.username is None
    assert result.failure is LegacyWebAuthFailure.INVALID_CREDENTIALS


async def test_authenticate_fails_when_password_md5_is_none() -> None:
    """Password MD5未送信時にINVALID_CREDENTIALSを返す契約を検証する.

    Returns:
        None: credentialなしの匿名認証失敗結果を検証して完了し,呼び出し側へ値を返さない.
    """
    query, _ = await _make_query_with_user()

    result = await _authenticate(query, username=_USERNAME, password_md5=None)

    assert result.user_id is None
    assert result.username is None
    assert result.failure is LegacyWebAuthFailure.INVALID_CREDENTIALS


async def test_authenticate_fails_when_user_not_found() -> None:
    """未登録usernameをINVALID_CREDENTIALSとして扱う契約を検証する.

    Returns:
        None: user未検出時の匿名認証失敗結果を検証して完了し,呼び出し側へ値を返さない.
    """
    query, _ = await _make_query_with_user()

    result = await _authenticate(query, username="UnknownUser", password_md5=_MD5_HEX)

    assert result.user_id is None
    assert result.username is None
    assert result.failure is LegacyWebAuthFailure.INVALID_CREDENTIALS


async def test_authenticate_fails_when_password_does_not_match() -> None:
    """保存hashと不一致のpassword MD5をINVALID_CREDENTIALSとして扱う契約を検証する.

    Returns:
        None: password不一致時の匿名認証失敗結果を検証して完了し,呼び出し側へ値を返さない.
    """
    query, _ = await _make_query_with_user()

    wrong_md5 = hashlib.md5(b"wrong_password").hexdigest()
    result = await _authenticate(query, username=_USERNAME, password_md5=wrong_md5)

    assert result.user_id is None
    assert result.username is None
    assert result.failure is LegacyWebAuthFailure.INVALID_CREDENTIALS


async def test_authenticate_fails_when_no_active_session() -> None:
    """有効credentialでもactive sessionがなければNO_SESSIONを返す契約を検証する.

    Returns:
        None: session不在時の認証失敗理由を検証して完了し,呼び出し側へ値を返さない.
    """
    query, _ = await _make_query_with_user(create_session=False)

    result = await _authenticate(query, username=_USERNAME, password_md5=_MD5_HEX)

    assert result.user_id is None
    assert result.username is None
    assert result.failure is LegacyWebAuthFailure.NO_SESSION


async def test_authenticate_does_not_log_password_md5() -> None:
    """認証失敗logにraw password MD5を含めない契約を検証する.

    Returns:
        None: 取得した全log entryにcredentialがないことを検証して完了し,呼び出し側へ値を返さない.
    """
    query, _ = await _make_query_with_user(create_session=False)

    with capture_logs() as captured:
        _ = await _authenticate(query, username=_USERNAME, password_md5=_MD5_HEX)

    for log_entry in captured:
        message = str(log_entry)
        assert _MD5_HEX not in message, f"Log entry contains password_md5: {message}"


def test_query_matches_expected_interface() -> None:
    """SessionCredentialsQueryUseCaseがexecute query interfaceを実装する契約を検証する.

    Returns:
        None: execute attributeの存在とcallable性を検証して完了し,呼び出し側へ値を返さない.
    """
    query = SessionCredentialsQueryUseCase(
        user_repository=UserQueryRepositoryStub(),
        password_service=PasswordService(hibp_client=None),
        session_store=InMemorySessionStore(),
    )
    assert hasattr(query, "execute")
    assert callable(query.execute)
