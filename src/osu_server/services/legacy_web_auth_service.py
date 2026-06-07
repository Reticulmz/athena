"""LegacyWebAuthService — stable web credential authentication for getscores endpoints.

Accepts endpoint-extracted username and password_md5 values, verifies credentials,
and requires active bancho session presence before serving getscores metadata.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import TYPE_CHECKING

import structlog

from osu_server.domain.user import User

if TYPE_CHECKING:
    from osu_server.repositories.interfaces.session_store import SessionStore
    from osu_server.repositories.interfaces.user_repository import UserRepository
    from osu_server.services.password_service import PasswordService

logger: structlog.stdlib.BoundLogger = structlog.get_logger(__name__)  # pyright: ignore[reportAny]


class LegacyWebAuthFailure(Enum):
    INVALID_CREDENTIALS = "invalid_credentials"
    NO_SESSION = "no_session"


@dataclass(slots=True, frozen=True)
class LegacyWebAuthResult:
    user_id: int | None = None
    username: str | None = None
    failure: LegacyWebAuthFailure | None = None


class LegacyWebAuthService:
    """Verifies legacy web credentials (us/ha) and active session presence.

    Dependencies:
        user_repo: UserRepository — finds users by safe_username
        password_service: PasswordService — verifies password_md5 against stored hash
        session_store: SessionStore — checks for active session by user_id
    """

    _user_repo: UserRepository
    _password_service: PasswordService
    _session_store: SessionStore

    def __init__(
        self,
        *,
        user_repo: UserRepository,
        password_service: PasswordService,
        session_store: SessionStore,
    ) -> None:
        self._user_repo = user_repo
        self._password_service = password_service
        self._session_store = session_store

    async def authenticate(
        self,
        username: str | None,
        password_md5: str | None,
    ) -> LegacyWebAuthResult:
        """Authenticate a user by us/ha credentials with active session check.

        Args:
            username: The ``us`` query parameter value (raw username).
            password_md5: The ``ha`` query parameter value (MD5 hex digest).

        Returns:
            LegacyWebAuthResult with user_id/username on success, or failure reason.
        """
        if username is None or password_md5 is None:
            logger.info(
                "legacy_web_auth_failed",
                reason="missing_credentials",
                has_username=username is not None,
                has_password_md5=password_md5 is not None,
            )
            return LegacyWebAuthResult(failure=LegacyWebAuthFailure.INVALID_CREDENTIALS)

        safe_username = User.normalize_username(username)
        user = await self._user_repo.get_by_safe_username(safe_username)

        if user is None:
            logger.info(
                "legacy_web_auth_failed",
                reason="user_not_found",
                safe_username=safe_username,
            )
            return LegacyWebAuthResult(failure=LegacyWebAuthFailure.INVALID_CREDENTIALS)

        password_valid = await self._password_service.verify(user.password_hash, password_md5)

        if not password_valid:
            logger.info(
                "legacy_web_auth_failed",
                reason="password_mismatch",
                user_id=user.id,
            )
            return LegacyWebAuthResult(failure=LegacyWebAuthFailure.INVALID_CREDENTIALS)

        session = await self._session_store.get_by_user(user.id)

        if session is None:
            logger.info(
                "legacy_web_auth_failed",
                reason="no_active_session",
                user_id=user.id,
            )
            return LegacyWebAuthResult(failure=LegacyWebAuthFailure.NO_SESSION)

        logger.info(
            "legacy_web_auth_success",
            user_id=user.id,
        )
        return LegacyWebAuthResult(user_id=user.id, username=user.username)
