"""アカウント登録をcommand inputとresultへ適合させるboundaryを提供する."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Protocol

if TYPE_CHECKING:
    from osu_server.domain.identity.authentication import RegistrationForm, RegistrationResult


class _RegistrationService(Protocol):
    """登録入力の検証とアカウント作成を提供する依存serviceを定義する."""

    async def register(
        self,
        form_data: RegistrationForm,
        check_only: bool = False,
    ) -> RegistrationResult:
        """登録フォームを検証し、必要に応じてアカウントを作成する.

        Args:
            form_data (RegistrationForm): username、email、passwordを含む登録フォーム.
            check_only (bool): 永続化せず検証だけを行う場合はTrue.

        Returns:
            RegistrationResult: 登録または検証の成否を表す結果.
        """
        ...


@dataclass(slots=True, frozen=True)
class RegisterUserCommandInput:
    """ユーザー登録commandの入力を表す.

    Attributes:
        form_data (RegistrationForm): username、email、passwordを含む登録フォーム.
        check_only (bool): 永続化せず検証だけを行う場合はTrue.
    """

    form_data: RegistrationForm
    check_only: bool = False


@dataclass(slots=True, frozen=True)
class RegisterUserCommandResult:
    """ユーザー登録commandの結果を表す.

    Attributes:
        outcome (RegistrationResult): 登録または検証の成否を表す結果.
    """

    outcome: RegistrationResult


class RegisterUserCommand(Protocol):
    """ユーザー登録workflowを実行するcommand boundaryを定義する."""

    async def execute(self, input_data: RegisterUserCommandInput) -> RegisterUserCommandResult:
        """入力に従ってユーザー登録commandを実行する.

        Args:
            input_data (RegisterUserCommandInput): 登録フォームと検証専用指定.

        Returns:
            RegisterUserCommandResult: 登録serviceの結果を保持するcommand result.
        """
        ...


class RegisterUserCommandUseCase:
    """登録入力を検証し、要求時はアカウントを作成する.

    Attributes:
        _auth_service (_RegistrationService): 登録の検証と永続化を行うservice.
    """

    _auth_service: _RegistrationService

    def __init__(self, *, auth_service: _RegistrationService) -> None:
        """ユーザー登録を実行するserviceを初期化する.

        Args:
            auth_service (_RegistrationService): 登録の検証と永続化を行うservice.

        """
        self._auth_service = auth_service

    async def execute(self, input_data: RegisterUserCommandInput) -> RegisterUserCommandResult:
        """登録フォームをserviceへ渡し、結果をcommand resultへ包む.

        Args:
            input_data (RegisterUserCommandInput): 登録フォームと検証専用指定.

        Returns:
            RegisterUserCommandResult: 登録serviceの結果を保持するcommand result.
        """
        outcome = await self._auth_service.register(
            form_data=input_data.form_data,
            check_only=input_data.check_only,
        )
        return RegisterUserCommandResult(outcome=outcome)


__all__ = [
    "RegisterUserCommand",
    "RegisterUserCommandInput",
    "RegisterUserCommandResult",
    "RegisterUserCommandUseCase",
]
