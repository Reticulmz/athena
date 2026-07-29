"""Active sessionを前提にcredentialを確認するquery use-caseを定義するmodule.

stable web legacy authenticationのcredential確認結果をread-only resultとして返す.
"""

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
    """保存済みhashとcredentialを照合するpassword verifier protocolを表す."""

    async def verify(self, hashed: str, password: str) -> bool:
        """保存済みhashと入力credentialが一致するかを返す.

        Args:
            hashed (str): userに保存されたpassword hash.
            password (str): stable clientが送信したpassword-md5 credential.

        Returns:
            bool: credentialが保存済みhashと一致する場合はTrue.
        """
        ...


@dataclass(slots=True, frozen=True)
class SessionCredentialsQueryInput:
    """stable web legacy credentialを確認するquery inputを表す.

    Attributes:
        username (str | None): 確認するusername. 未送信時はNone.
        password_md5 (str | None): stable clientのpassword-md5 credential. 未送信時はNone.
    """

    username: str | None
    password_md5: str | None


@dataclass(slots=True, frozen=True)
class SessionCredentialsQueryResult:
    """stable web legacy credential queryの結果を表す.

    Attributes:
        outcome (LegacyWebAuthResult): 認証済みuser情報または失敗理由を持つ結果.
    """

    outcome: LegacyWebAuthResult


class SessionCredentialsQuery(Protocol):
    """active sessionを前提にstable web legacy credentialを確認するquery protocolを表す."""

    async def execute(
        self,
        input_data: SessionCredentialsQueryInput,
    ) -> SessionCredentialsQueryResult:
        """指定credentialのread-only authentication結果を返す.

        Args:
            input_data (SessionCredentialsQueryInput): usernameとpassword-md5を持つquery input.

        Returns:
            SessionCredentialsQueryResult: 認証済みuser情報または失敗理由を持つ結果.
        """
        ...


class SessionCredentialsQueryUseCase:
    """active session read modelに対してrequest credentialを確認するquery use-caseを表す.

    Attributes:
        _user_repository (UserQueryRepository): safe usernameからuserを読むquery repository.
        _password_service (_PasswordVerifier): 保存済みhashとpassword-md5を照合するverifier.
        _session_store (UserSessionLookup): user単位のactive sessionを読むvolatile state store.
    """

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
        """credential確認に必要なread dependencyを設定する.

        Args:
            user_repository (UserQueryRepository): safe usernameからuserを読むrepository.
            password_service (_PasswordVerifier): 保存済みhashとcredentialを照合するverifier.
            session_store (UserSessionLookup): user単位のactive sessionを読むstore.
        """
        self._user_repository = user_repository
        self._password_service = password_service
        self._session_store = session_store

    async def execute(
        self,
        input_data: SessionCredentialsQueryInput,
    ) -> SessionCredentialsQueryResult:
        """credentialとactive sessionを確認してstable web legacy authentication結果を返す.

        Args:
            input_data (SessionCredentialsQueryInput): usernameとpassword-md5を持つquery input.

        Returns:
            SessionCredentialsQueryResult: 認証済みuser情報または
                INVALID_CREDENTIALS/NO_SESSION結果.

        Notes:
            password-md5のraw値はlogへ記録しない. user未検出とpassword不一致は同じ
            INVALID_CREDENTIALSとして返し, active sessionがない場合だけNO_SESSIONを返す.
        """
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
