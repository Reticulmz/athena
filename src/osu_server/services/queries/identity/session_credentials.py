"""Session credential authentication query use-case boundary."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Protocol

import structlog

from osu_server.domain.identity.authentication import LegacyWebAuthFailure, LegacyWebAuthResult
from osu_server.domain.identity.users import User

if TYPE_CHECKING:
    from osu_server.repositories.interfaces.queries.users import UserQueryRepository
    from osu_server.repositories.interfaces.session_store import UserSessionLookup

logger: structlog.stdlib.BoundLogger = structlog.get_logger(__name__)  # pyright: ignore[reportAny]


class _PasswordVerifier(Protocol):
    async def verify(self, hashed: str, password: str) -> bool: ...


@dataclass(slots=True, frozen=True)
class SessionCredentialsQueryInput:
    username: str | None
    password_md5: str | None


@dataclass(slots=True, frozen=True)
class SessionCredentialsQueryResult:
    outcome: LegacyWebAuthResult


class SessionCredentialsQuery(Protocol):
    async def execute(
        self,
        input_data: SessionCredentialsQueryInput,
    ) -> SessionCredentialsQueryResult: ...


class SessionCredentialsQueryUseCase:
    """Authenticate request credentials against the active session read model."""

    _user_repository: UserQueryRepository
    _password_service: _PasswordVerifier
    _session_store: UserSessionLookup

    def __init__(
        self,
        *,
        user_repository: UserQueryRepository,
        password_service: _PasswordVerifier,
        session_store: UserSessionLookup,
    ) -> None:
        self._user_repository = user_repository
        self._password_service = password_service
        self._session_store = session_store

    async def execute(
        self,
        input_data: SessionCredentialsQueryInput,
    ) -> SessionCredentialsQueryResult:
        if input_data.username is None or input_data.password_md5 is None:
            logger.info(
                "session_credentials_auth_failed",
                reason="missing_credentials",
                has_username=input_data.username is not None,
                has_password_md5=input_data.password_md5 is not None,
            )
            return SessionCredentialsQueryResult(
                outcome=LegacyWebAuthResult(failure=LegacyWebAuthFailure.INVALID_CREDENTIALS)
            )

        safe_username = User.normalize_username(input_data.username)
        user = await self._user_repository.get_by_safe_username(safe_username)
        if user is None:
            logger.info(
                "session_credentials_auth_failed",
                reason="user_not_found",
                safe_username=safe_username,
            )
            return SessionCredentialsQueryResult(
                outcome=LegacyWebAuthResult(failure=LegacyWebAuthFailure.INVALID_CREDENTIALS)
            )

        password_valid = await self._password_service.verify(
            user.password_hash,
            input_data.password_md5,
        )
        if not password_valid:
            logger.info(
                "session_credentials_auth_failed",
                reason="password_mismatch",
                user_id=user.id,
            )
            return SessionCredentialsQueryResult(
                outcome=LegacyWebAuthResult(failure=LegacyWebAuthFailure.INVALID_CREDENTIALS)
            )

        session = await self._session_store.get_by_user(user.id)
        if session is None:
            logger.info(
                "session_credentials_auth_failed",
                reason="no_active_session",
                user_id=user.id,
            )
            return SessionCredentialsQueryResult(
                outcome=LegacyWebAuthResult(failure=LegacyWebAuthFailure.NO_SESSION)
            )

        logger.info("session_credentials_auth_success", user_id=user.id)
        return SessionCredentialsQueryResult(
            outcome=LegacyWebAuthResult(user_id=user.id, username=user.username)
        )


__all__ = [
    "SessionCredentialsQuery",
    "SessionCredentialsQueryInput",
    "SessionCredentialsQueryResult",
    "SessionCredentialsQueryUseCase",
]
