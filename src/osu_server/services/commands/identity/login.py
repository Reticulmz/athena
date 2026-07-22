"""ログイン認証をcommand inputとresultへ適合させるboundaryを提供する."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Protocol

if TYPE_CHECKING:
    from osu_server.domain.identity.authentication import LoginRequest, LoginResponse, LoginResult


class _LoginService(Protocol):
    """ログイン認証とsession作成を提供する依存serviceを定義する."""

    async def login(
        self,
        login_request: LoginRequest,
        *,
        country: str,
    ) -> LoginResponse | LoginResult:
        """ログインを認証し、成功時はactive sessionを作成する.

        Args:
            login_request (LoginRequest): パース済みのログインrequest.
            country (str): transport boundaryで解決した国コード.

        Returns:
            LoginResponse | LoginResult: 成功時のsession情報または失敗理由.
        """
        ...


@dataclass(slots=True, frozen=True)
class LoginCommandInput:
    """ログインcommandの入力を表す.

    Attributes:
        login_request (LoginRequest): 認証するパース済みログインrequest.
        country (str): transport boundaryで解決した国コード.
    """

    login_request: LoginRequest
    country: str


@dataclass(slots=True, frozen=True)
class LoginCommandResult:
    """ログインcommandの結果を表す.

    Attributes:
        outcome (LoginResponse | LoginResult): 成功時のsession情報または失敗理由.
    """

    outcome: LoginResponse | LoginResult


class LoginCommand(Protocol):
    """ログインworkflowを実行するcommand boundaryを定義する."""

    async def execute(self, input_data: LoginCommandInput) -> LoginCommandResult:
        """入力に従ってログインcommandを実行する.

        Args:
            input_data (LoginCommandInput): ログインrequestと国コード.

        Returns:
            LoginCommandResult: 認証の成否を含む結果.
        """
        ...


class LoginCommandUseCase:
    """ログインrequestを認証し、成功時にactive sessionを作成する.

    Attributes:
        _auth_service (_LoginService): 認証とsession作成を実行するservice.
    """

    _auth_service: _LoginService

    def __init__(self, *, auth_service: _LoginService) -> None:
        """ログインを実行するserviceを初期化する.

        Args:
            auth_service (_LoginService): 認証とsession作成を実行するservice.

        """
        self._auth_service = auth_service

    async def execute(self, input_data: LoginCommandInput) -> LoginCommandResult:
        """ログインrequestをserviceへ渡し、結果をcommand resultへ包む.

        Args:
            input_data (LoginCommandInput): ログインrequestと国コード.

        Returns:
            LoginCommandResult: 認証serviceの結果を保持するcommand result.
        """
        outcome = await self._auth_service.login(
            input_data.login_request,
            country=input_data.country,
        )
        return LoginCommandResult(outcome=outcome)


__all__ = [
    "LoginCommand",
    "LoginCommandInput",
    "LoginCommandResult",
    "LoginCommandUseCase",
]
