"""Unit tests for ScoreAuthorizationService."""

import hashlib
from datetime import UTC, datetime

import pytest

from osu_server.domain.identity.sessions import SessionData
from osu_server.domain.identity.users import User
from osu_server.repositories.memory.session_store import InMemorySessionStore
from osu_server.repositories.memory.user_repository import InMemoryUserRepository
from osu_server.services.password_service import PasswordService
from osu_server.services.score_authorization_service import (
    AuthorizationContext,
    ScoreAuthorizationService,
)
from tests.support.fakes import make_score_authorization_service

_NOW = datetime(2026, 6, 12, tzinfo=UTC)


async def _make_repository_backed_service(
    *,
    username: str = "PlayerOne",
    password: str = "password",
    create_session: bool = True,
) -> tuple[ScoreAuthorizationService, str, int]:
    user_repo = InMemoryUserRepository()
    password_service = PasswordService(hibp_client=None, banned_passwords=[])
    session_store = InMemorySessionStore()

    password_md5 = hashlib.md5(password.encode()).hexdigest()
    user = await user_repo.create(
        User(
            id=0,
            username=username,
            safe_username=User.normalize_username(username),
            email="player@example.com",
            password_hash=await password_service.hash(password_md5),
            country="JP",
            created_at=_NOW,
            updated_at=_NOW,
        )
    )
    if create_session:
        await session_store.create(
            user.id,
            f"token-{user.id}",
            SessionData(
                user_id=user.id,
                username=user.username,
                privileges=1,
                country="JP",
                osu_version="20260412",
                utc_offset=9,
                display_city=False,
                client_hashes="",
                pm_private=False,
            ),
        )

    return (
        ScoreAuthorizationService(
            user_repo=user_repo,
            password_service=password_service,
            session_store=session_store,
        ),
        password_md5,
        user.id,
    )


@pytest.fixture
def service() -> ScoreAuthorizationService:
    """Create service instance."""
    return make_score_authorization_service()


class TestScoreAuthorizationService:
    """Test ScoreAuthorizationService."""

    @pytest.mark.asyncio
    async def test_valid_authorization(self, service: ScoreAuthorizationService) -> None:
        """Valid credentials with matching payload should authorize."""
        result = await service.authorize_submission(
            password_md5="aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
            payload_username="test_user",
            payload_user_id=1000,
        )

        assert result.authorized
        assert result.user_id == 1000
        assert result.username == "test_user"
        assert result.session_valid
        assert result.password_valid
        assert result.payload_identity_match

    @pytest.mark.asyncio
    async def test_valid_authorization_without_payload_user_id(
        self, service: ScoreAuthorizationService
    ) -> None:
        """Stable payloads identify users by username, not user ID."""
        result = await service.authorize_submission(
            password_md5="aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
            payload_username="test_user",
            payload_user_id=0,
        )

        assert result.authorized
        assert result.user_id == 1000
        assert result.payload_identity_match

    @pytest.mark.asyncio
    async def test_repository_backed_authorization(self) -> None:
        """Repository-backed auth accepts real users with active sessions."""
        service, password_md5, user_id = await _make_repository_backed_service()

        result = await service.authorize_submission(
            password_md5=password_md5,
            payload_username="PlayerOne",
            payload_user_id=0,
        )

        assert result.authorized
        assert result.user_id == user_id
        assert result.username == "PlayerOne"
        assert result.password_valid
        assert result.session_valid
        assert result.payload_identity_match

    @pytest.mark.asyncio
    async def test_invalid_password_rejection(self, service: ScoreAuthorizationService) -> None:
        """Invalid password should reject."""
        result = await service.authorize_submission(
            password_md5="invalid_hash",
            payload_username="test_user",
            payload_user_id=1000,
        )

        assert not result.authorized
        assert not result.password_valid
        assert result.session_valid

    @pytest.mark.asyncio
    async def test_no_active_session_rejection(self) -> None:
        """No active session should reject even when the password is valid."""
        service_without_session = make_score_authorization_service(create_session=False)
        result = await service_without_session.authorize_submission(
            password_md5="aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
            payload_username="test_user",
            payload_user_id=1000,
        )

        assert not result.authorized
        assert result.password_valid
        assert not result.session_valid

    @pytest.mark.asyncio
    async def test_payload_identity_mismatch_rejection(
        self, service: ScoreAuthorizationService
    ) -> None:
        """Payload identity mismatch should reject."""
        result = await service.authorize_submission(
            password_md5="aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
            payload_username="wrong_user",
            payload_user_id=9999,
        )

        assert not result.authorized
        assert not result.payload_identity_match

    @pytest.mark.asyncio
    async def test_no_raw_credentials_logged(
        self, service: ScoreAuthorizationService, caplog: pytest.LogCaptureFixture
    ) -> None:
        """Raw password-md5 should never appear in logs."""
        password_md5 = "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"

        _ = await service.authorize_submission(
            password_md5=password_md5,
            payload_username="test_user",
            payload_user_id=1000,
        )

        # Check no raw password in any log record
        for record in caplog.records:
            assert password_md5 not in record.message


class TestAuthorizationContext:
    """Test AuthorizationContext."""

    def test_authorized_property_all_valid(self) -> None:
        """authorized should be True when all checks pass."""
        ctx = AuthorizationContext(
            user_id=1000,
            username="test_user",
            session_valid=True,
            password_valid=True,
            payload_identity_match=True,
        )

        assert ctx.authorized

    def test_authorized_property_session_invalid(self) -> None:
        """authorized should be False when session invalid."""
        ctx = AuthorizationContext(
            user_id=1000,
            username="test_user",
            session_valid=False,
            password_valid=True,
            payload_identity_match=True,
        )

        assert not ctx.authorized

    def test_authorized_property_password_invalid(self) -> None:
        """authorized should be False when password invalid."""
        ctx = AuthorizationContext(
            user_id=1000,
            username="test_user",
            session_valid=True,
            password_valid=False,
            payload_identity_match=True,
        )

        assert not ctx.authorized

    def test_authorized_property_identity_mismatch(self) -> None:
        """authorized should be False when identity mismatch."""
        ctx = AuthorizationContext(
            user_id=1000,
            username="test_user",
            session_valid=True,
            password_valid=True,
            payload_identity_match=False,
        )

        assert not ctx.authorized
