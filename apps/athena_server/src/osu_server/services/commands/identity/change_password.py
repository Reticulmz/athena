"""ユーザーのパスワードを変更するcommand use-caseを提供する."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import TYPE_CHECKING, Protocol

from osu_server.domain.identity.passwords import (
    PASSWORD_COMPROMISED_MESSAGE,
    validate_plain_password,
)
from osu_server.domain.identity.system_users import BANCHO_BOT_USER_ID
from osu_server.domain.identity.users import User

if TYPE_CHECKING:
    from osu_server.repositories.interfaces.queries.users import UserQueryRepository
    from osu_server.repositories.interfaces.unit_of_work import UnitOfWorkFactory


class _PasswordService(Protocol):
    """パスワードの検証とhash化を提供する依存serviceを定義する."""

    async def prepare_password(self, plain_password: str) -> str:
        """平文passwordを保存用hashへ変換する.

        Args:
            plain_password (str): policy検証済みの平文password.

        Returns:
            str: 保存可能なpassword hash.
        """
        ...

    async def is_password_banned(self, password: str) -> bool:
        """passwordが漏えいまたは禁止一覧に含まれるかを判定する.

        Args:
            password (str): 検査対象の平文password.

        Returns:
            bool: passwordを拒否すべき場合はTrue.
        """
        ...


class ChangeUserPasswordStatus(StrEnum):
    """パスワード変更commandの完了状態を表す.

    Attributes:
        CHANGED (ChangeUserPasswordStatus): password hashを更新した状態.
        USER_NOT_FOUND (ChangeUserPasswordStatus): 対象usernameのユーザーがない状態.
        INVALID_PASSWORD (ChangeUserPasswordStatus): password policyまたは禁止判定に失敗した状態.
        SYSTEM_USER_DENIED (ChangeUserPasswordStatus): system userの変更を拒否した状態.
    """

    CHANGED = "changed"
    USER_NOT_FOUND = "user_not_found"
    INVALID_PASSWORD = "invalid_password"
    SYSTEM_USER_DENIED = "system_user_denied"


@dataclass(slots=True, frozen=True)
class ChangeUserPasswordCommandInput:
    """パスワード変更commandの入力を表す.

    Attributes:
        username (str): 変更対象ユーザーの入力username.
        plain_password (str): policyと漏えい検査を行う新しい平文password.
    """

    username: str
    plain_password: str


@dataclass(slots=True, frozen=True)
class ChangeUserPasswordCommandResult:
    """パスワード変更commandの結果を表す.

    Attributes:
        status (ChangeUserPasswordStatus): commandの完了状態.
        username (str): 検索または入力に用いたusername.
        user_id (int | None): 特定できた対象ユーザーのID. 未特定時はNone.
        errors (tuple[str, ...]): INVALID_PASSWORD時のpolicyまたは禁止理由.
    """

    status: ChangeUserPasswordStatus
    username: str
    user_id: int | None = None
    errors: tuple[str, ...] = ()

    @property
    def changed(self) -> bool:
        """Password hashを実際に更新したかを返す.

        Returns:
            bool: statusがCHANGEDの場合はTrue.
        """
        return self.status is ChangeUserPasswordStatus.CHANGED


class ChangeUserPasswordCommand(Protocol):
    """パスワード変更workflowを実行するcommand boundaryを定義する."""

    async def execute(
        self,
        input_data: ChangeUserPasswordCommandInput,
    ) -> ChangeUserPasswordCommandResult:
        """入力に従ってパスワード変更を実行する.

        Args:
            input_data (ChangeUserPasswordCommandInput): 対象usernameと新しい平文password.

        Returns:
            ChangeUserPasswordCommandResult: 変更可否と失敗理由を表す結果.
        """
        ...


class ChangeUserPasswordCommandUseCase:
    """command Unit of Work境界でユーザーのpassword hashを更新する.

    Attributes:
        _uow_factory (UnitOfWorkFactory): password hashを書き込むUnit of Workのfactory.
        _user_query_repository (UserQueryRepository): usernameからユーザーを読むquery repository.
        _password_service (_PasswordService): password policyとhash化を提供するservice.
        _system_user_id (int): password変更を拒否するsystem userのID.
    """

    _uow_factory: UnitOfWorkFactory
    _user_query_repository: UserQueryRepository
    _password_service: _PasswordService
    _system_user_id: int

    def __init__(
        self,
        *,
        uow_factory: UnitOfWorkFactory,
        user_query_repository: UserQueryRepository,
        password_service: _PasswordService,
        system_user_id: int = BANCHO_BOT_USER_ID,
    ) -> None:
        """パスワード変更に必要な依存を初期化する.

        Args:
            uow_factory (UnitOfWorkFactory): password hashを書き込むUnit of Workのfactory.
            user_query_repository (UserQueryRepository): usernameからユーザーを読むrepository.
            password_service (_PasswordService): password検証とhash化を行うservice.
            system_user_id (int): 変更を拒否するsystem userのID.

        """
        self._uow_factory = uow_factory
        self._user_query_repository = user_query_repository
        self._password_service = password_service
        self._system_user_id = system_user_id

    async def execute(
        self,
        input_data: ChangeUserPasswordCommandInput,
    ) -> ChangeUserPasswordCommandResult:
        """対象ユーザーのpassword hashをpolicyに従って更新する.

        Args:
            input_data (ChangeUserPasswordCommandInput): 対象usernameと新しい平文password.

        Returns:
            ChangeUserPasswordCommandResult: 更新,拒否,または未発見を表す結果.

        Notes:
            system userのpasswordは変更せず,漏えいpasswordもINVALID_PASSWORDとして返す.
        """
        safe_username = User.normalize_username(input_data.username)
        user = await self._user_query_repository.get_by_safe_username(safe_username)
        if user is None:
            return ChangeUserPasswordCommandResult(
                status=ChangeUserPasswordStatus.USER_NOT_FOUND,
                username=input_data.username,
            )

        if user.id == self._system_user_id:
            return ChangeUserPasswordCommandResult(
                status=ChangeUserPasswordStatus.SYSTEM_USER_DENIED,
                username=user.username,
                user_id=user.id,
            )

        policy_errors = validate_plain_password(input_data.plain_password)
        if policy_errors:
            return ChangeUserPasswordCommandResult(
                status=ChangeUserPasswordStatus.INVALID_PASSWORD,
                username=user.username,
                user_id=user.id,
                errors=policy_errors,
            )

        if await self._password_service.is_password_banned(input_data.plain_password):
            return ChangeUserPasswordCommandResult(
                status=ChangeUserPasswordStatus.INVALID_PASSWORD,
                username=user.username,
                user_id=user.id,
                errors=(PASSWORD_COMPROMISED_MESSAGE,),
            )

        password_hash = await self._password_service.prepare_password(input_data.plain_password)
        async with self._uow_factory() as uow:
            updated = await uow.users.update_password_hash(user.id, password_hash)
            if not updated:
                return ChangeUserPasswordCommandResult(
                    status=ChangeUserPasswordStatus.USER_NOT_FOUND,
                    username=user.username,
                    user_id=user.id,
                )
            await uow.commit()

        return ChangeUserPasswordCommandResult(
            status=ChangeUserPasswordStatus.CHANGED,
            username=user.username,
            user_id=user.id,
        )


__all__ = [
    "ChangeUserPasswordCommand",
    "ChangeUserPasswordCommandInput",
    "ChangeUserPasswordCommandResult",
    "ChangeUserPasswordCommandUseCase",
    "ChangeUserPasswordStatus",
]
