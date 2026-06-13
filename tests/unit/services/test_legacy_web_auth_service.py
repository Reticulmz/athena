"""LegacyWebAuthService unit tests.

TDD RED -> GREEN -> REFACTOR.
Validates us/ha credential authentication with active session requirement.
"""

from __future__ import annotations

import hashlib
from datetime import UTC, datetime

from structlog.testing import capture_logs

from osu_server.domain.identity.authentication import LegacyWebAuthFailure, LegacyWebAuthResult
from osu_server.domain.identity.sessions import SessionData
from osu_server.domain.identity.users import User
from osu_server.repositories.memory.session_store import InMemorySessionStore
from osu_server.repositories.memory.user_repository import InMemoryUserRepository
from osu_server.services.legacy_web_auth_service import LegacyWebAuthService
from osu_server.services.password_service import PasswordService

_NOW = datetime(2026, 6, 7, tzinfo=UTC)
_PLAIN_PASSWORD = "test_password"
_MD5_HEX = hashlib.md5(_PLAIN_PASSWORD.encode()).hexdigest()
_USERNAME = "TestUser"
_SAFE_USERNAME = User.normalize_username(_USERNAME)


def _make_user() -> User:
    return User(
        id=0,  # assigned by repository
        username=_USERNAME,
        safe_username=_SAFE_USERNAME,
        email="test@example.com",
        password_hash="",  # set after hashing
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


async def _make_service_with_user(
    *,
    password_md5: str = _MD5_HEX,
    create_session: bool = True,
) -> tuple[LegacyWebAuthService, int]:
    """Create a LegacyWebAuthService with a pre-registered user.

    Returns (service, user_id).
    """
    user_repo = InMemoryUserRepository()
    session_store = InMemorySessionStore()
    password_service = PasswordService(hibp_client=None, banned_passwords=[])

    # Hash the MD5 value as the stored password hash
    password_hash = await password_service.hash(password_md5)

    user = _make_user()
    user.password_hash = password_hash
    created = await user_repo.create(user)

    if create_session:
        session_data = _make_session_data(user_id=created.id)
        await session_store.create(
            user_id=created.id, token=f"token_{created.id}", data=session_data
        )

    svc = LegacyWebAuthService(
        user_repo=user_repo,
        password_service=password_service,
        session_store=session_store,
    )
    return svc, created.id


# ---------------------------------------------------------------------------
# Happy path
# ---------------------------------------------------------------------------


async def test_authenticate_succeeds_with_valid_credentials_and_session() -> None:
    """Valid us/ha with active session returns success result."""
    svc, user_id = await _make_service_with_user()

    result = await svc.authenticate(username=_USERNAME, password_md5=_MD5_HEX)

    assert isinstance(result, LegacyWebAuthResult)
    assert result.user_id == user_id
    assert result.username == _USERNAME
    assert result.failure is None


# ---------------------------------------------------------------------------
# Missing credentials
# ---------------------------------------------------------------------------


async def test_authenticate_fails_when_username_is_none() -> None:
    """Missing username returns invalid_credentials failure."""
    svc, _ = await _make_service_with_user()

    result = await svc.authenticate(username=None, password_md5=_MD5_HEX)

    assert result.user_id is None
    assert result.username is None
    assert result.failure is LegacyWebAuthFailure.INVALID_CREDENTIALS


async def test_authenticate_fails_when_password_md5_is_none() -> None:
    """Missing password_md5 returns invalid_credentials failure."""
    svc, _ = await _make_service_with_user()

    result = await svc.authenticate(username=_USERNAME, password_md5=None)

    assert result.user_id is None
    assert result.username is None
    assert result.failure is LegacyWebAuthFailure.INVALID_CREDENTIALS


# ---------------------------------------------------------------------------
# User lookup failures
# ---------------------------------------------------------------------------


async def test_authenticate_fails_when_user_not_found() -> None:
    """Unknown username returns invalid_credentials failure."""
    svc, _ = await _make_service_with_user()

    result = await svc.authenticate(username="UnknownUser", password_md5=_MD5_HEX)

    assert result.user_id is None
    assert result.username is None
    assert result.failure is LegacyWebAuthFailure.INVALID_CREDENTIALS


async def test_authenticate_fails_when_password_does_not_match() -> None:
    """Wrong password_md5 returns invalid_credentials failure."""
    svc, _ = await _make_service_with_user()

    wrong_md5 = hashlib.md5(b"wrong_password").hexdigest()
    result = await svc.authenticate(username=_USERNAME, password_md5=wrong_md5)

    assert result.user_id is None
    assert result.username is None
    assert result.failure is LegacyWebAuthFailure.INVALID_CREDENTIALS


# ---------------------------------------------------------------------------
# Session presence
# ---------------------------------------------------------------------------


async def test_authenticate_fails_when_no_active_session() -> None:
    """Valid credentials without active session returns no_session failure."""
    svc, _ = await _make_service_with_user(create_session=False)

    result = await svc.authenticate(username=_USERNAME, password_md5=_MD5_HEX)

    assert result.user_id is None
    assert result.username is None
    assert result.failure is LegacyWebAuthFailure.NO_SESSION


# ---------------------------------------------------------------------------
# Credential redaction (requirement 12.2)
# ---------------------------------------------------------------------------


async def test_authenticate_does_not_log_password_md5() -> None:
    """Password MD5 must not appear in log messages (requirement 12.2)."""
    svc, _ = await _make_service_with_user(create_session=False)

    with capture_logs() as captured:
        _ = await svc.authenticate(username=_USERNAME, password_md5=_MD5_HEX)

    for log_entry in captured:
        message = str(log_entry)
        assert _MD5_HEX not in message, f"Log entry contains password_md5: {message}"


# ---------------------------------------------------------------------------
# Contract (runtime_checkable protocol conformance)
# ---------------------------------------------------------------------------


def test_service_matches_expected_interface() -> None:
    """Verify LegacyWebAuthService has the expected authenticate method."""
    svc = LegacyWebAuthService(
        user_repo=InMemoryUserRepository(),
        password_service=PasswordService(hibp_client=None),
        session_store=InMemorySessionStore(),
    )
    assert hasattr(svc, "authenticate")
    assert callable(svc.authenticate)
