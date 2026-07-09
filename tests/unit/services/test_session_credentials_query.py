"""SessionCredentialsQueryUseCase unit tests."""

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
    def __init__(self) -> None:
        self.users_by_safe_username: dict[str, User] = {}
        self.users_by_id: dict[int, User] = {}
        self.users_by_email: dict[str, User] = {}

    async def get_by_id(self, user_id: int) -> User | None:
        return self.users_by_id.get(user_id)

    async def get_by_safe_username(self, safe_username: str) -> User | None:
        return self.users_by_safe_username.get(safe_username)

    async def get_by_email(self, email: str) -> User | None:
        return self.users_by_email.get(email)

    async def is_username_disallowed(self, safe_username: str) -> bool:
        return safe_username == "banchobot"


def _make_user() -> User:
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
    result = await query.execute(
        SessionCredentialsQueryInput(username=username, password_md5=password_md5)
    )
    return result.outcome


async def test_authenticate_succeeds_with_valid_credentials_and_session() -> None:
    query, user_id = await _make_query_with_user()

    result = await _authenticate(query, username=_USERNAME, password_md5=_MD5_HEX)

    assert result.user_id == user_id
    assert result.username == _USERNAME
    assert result.failure is None


async def test_authenticate_accepts_uppercase_password_md5() -> None:
    """Legacy web auth の password MD5 hex は大小文字差を認証差にしない."""
    query, user_id = await _make_query_with_user()

    result = await _authenticate(query, username=_USERNAME, password_md5=_MD5_HEX.upper())

    assert result.user_id == user_id
    assert result.username == _USERNAME
    assert result.failure is None


async def test_authenticate_fails_when_username_is_none() -> None:
    query, _ = await _make_query_with_user()

    result = await _authenticate(query, username=None, password_md5=_MD5_HEX)

    assert result.user_id is None
    assert result.username is None
    assert result.failure is LegacyWebAuthFailure.INVALID_CREDENTIALS


async def test_authenticate_fails_when_password_md5_is_none() -> None:
    query, _ = await _make_query_with_user()

    result = await _authenticate(query, username=_USERNAME, password_md5=None)

    assert result.user_id is None
    assert result.username is None
    assert result.failure is LegacyWebAuthFailure.INVALID_CREDENTIALS


async def test_authenticate_fails_when_user_not_found() -> None:
    query, _ = await _make_query_with_user()

    result = await _authenticate(query, username="UnknownUser", password_md5=_MD5_HEX)

    assert result.user_id is None
    assert result.username is None
    assert result.failure is LegacyWebAuthFailure.INVALID_CREDENTIALS


async def test_authenticate_fails_when_password_does_not_match() -> None:
    query, _ = await _make_query_with_user()

    wrong_md5 = hashlib.md5(b"wrong_password").hexdigest()
    result = await _authenticate(query, username=_USERNAME, password_md5=wrong_md5)

    assert result.user_id is None
    assert result.username is None
    assert result.failure is LegacyWebAuthFailure.INVALID_CREDENTIALS


async def test_authenticate_fails_when_no_active_session() -> None:
    query, _ = await _make_query_with_user(create_session=False)

    result = await _authenticate(query, username=_USERNAME, password_md5=_MD5_HEX)

    assert result.user_id is None
    assert result.username is None
    assert result.failure is LegacyWebAuthFailure.NO_SESSION


async def test_authenticate_does_not_log_password_md5() -> None:
    query, _ = await _make_query_with_user(create_session=False)

    with capture_logs() as captured:
        _ = await _authenticate(query, username=_USERNAME, password_md5=_MD5_HEX)

    for log_entry in captured:
        message = str(log_entry)
        assert _MD5_HEX not in message, f"Log entry contains password_md5: {message}"


def test_query_matches_expected_interface() -> None:
    query = SessionCredentialsQueryUseCase(
        user_repository=UserQueryRepositoryStub(),
        password_service=PasswordService(hibp_client=None),
        session_store=InMemorySessionStore(),
    )
    assert hasattr(query, "execute")
    assert callable(query.execute)
