"""Unit tests for ScoreAuthorizationService."""

import pytest

from osu_server.infrastructure.auth.score_authorization import (
    AuthorizationContext,
    ScoreAuthorizationService,
)


@pytest.fixture
def service() -> ScoreAuthorizationService:
    """Create service instance."""
    return ScoreAuthorizationService()


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
    async def test_invalid_password_rejection(self, service: ScoreAuthorizationService) -> None:
        """Invalid password should reject."""
        result = await service.authorize_submission(
            password_md5="invalid_hash",
            payload_username="test_user",
            payload_user_id=1000,
        )

        assert not result.authorized
        assert not result.password_valid
        assert not result.session_valid

    @pytest.mark.asyncio
    async def test_no_active_session_rejection(self, service: ScoreAuthorizationService) -> None:
        """No active session should reject (mocked as password_valid=False)."""
        result = await service.authorize_submission(
            password_md5="wrong_password",
            payload_username="test_user",
            payload_user_id=1000,
        )

        assert not result.authorized
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
