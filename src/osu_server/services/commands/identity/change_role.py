"""ユーザーのroleを置換するcommand use-caseを提供する."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import TYPE_CHECKING, Protocol

from osu_server.domain.identity.authorization import Privileges
from osu_server.domain.identity.leaderboard_visibility import is_leaderboard_visible_user
from osu_server.domain.identity.system_users import BANCHO_BOT_USER_ID
from osu_server.domain.identity.users import User
from osu_server.shared.ports import (
    BeatmapLeaderboardRebuildWorkerWake,
    NoopBeatmapLeaderboardRebuildWorkerWake,
)

if TYPE_CHECKING:
    from collections.abc import Iterable

    from osu_server.domain.identity.roles import Role
    from osu_server.domain.identity.sessions import (
        AuthorizationRefreshStatus,
        UserAuthorizationRefreshResult,
    )
    from osu_server.repositories.interfaces.unit_of_work import UnitOfWorkFactory


class _SessionAuthorizationRefreshService(Protocol):
    """ユーザーのsession authorizationを再計算する依存serviceを定義する."""

    async def refresh_user_authorization(
        self,
        user_id: int,
    ) -> UserAuthorizationRefreshResult:
        """指定ユーザーのactive session authorizationを更新する.

        Args:
            user_id (int): authorizationを再計算するユーザーID.

        Returns:
            UserAuthorizationRefreshResult: 更新,session不在,または計算失敗を表す結果.
        """
        ...


class ChangeUserRoleStatus(StrEnum):
    """role変更commandの完了状態を表す.

    Attributes:
        CHANGED (ChangeUserRoleStatus): role割り当てを更新した状態.
        UNCHANGED (ChangeUserRoleStatus): 既に指定roleだけが割り当てられていた状態.
        USER_NOT_FOUND (ChangeUserRoleStatus): 対象usernameのユーザーがない状態.
        ROLE_NOT_FOUND (ChangeUserRoleStatus): 指定roleがない状態.
        SYSTEM_USER_DENIED (ChangeUserRoleStatus): system userへの変更を拒否した状態.
    """

    CHANGED = "changed"
    UNCHANGED = "unchanged"
    USER_NOT_FOUND = "user_not_found"
    ROLE_NOT_FOUND = "role_not_found"
    SYSTEM_USER_DENIED = "system_user_denied"


@dataclass(slots=True, frozen=True)
class ChangeUserRoleCommandInput:
    """role変更commandの入力を表す.

    Attributes:
        username (str): 変更対象ユーザーの入力username.
        role_name (str): ユーザーへ唯一割り当てるrole名.
    """

    username: str
    role_name: str


@dataclass(slots=True, frozen=True)
class ChangeUserRoleCommandResult:
    """role変更commandの結果と後続処理の状態を表す.

    Attributes:
        status (ChangeUserRoleStatus): role割り当ての完了状態.
        username (str): 検索または入力に用いたusername.
        role_name (str): 要求または確定したrole名.
        user_id (int | None): 特定できた対象ユーザーのID. 未特定時はNone.
        role_id (int | None): 特定できたtarget roleのID. 未特定時はNone.
        previous_role_names (tuple[str, ...]): 更新前に割り当てられていたrole名.
        authorization_refresh_status (AuthorizationRefreshStatus | None): 認可更新結果.
            未実行時はNone.
        leaderboard_rebuild_requested (bool): leaderboard再構築を要求したか.
        leaderboard_rebuild_failed (bool): 要求したleaderboard再構築が失敗したか.
        leaderboard_rebuild_error (str | None): 再構築失敗時のerror文字列.
            成功または未要求時はNone.
    """

    status: ChangeUserRoleStatus
    username: str
    role_name: str
    user_id: int | None = None
    role_id: int | None = None
    previous_role_names: tuple[str, ...] = ()
    authorization_refresh_status: AuthorizationRefreshStatus | None = None
    leaderboard_rebuild_requested: bool = False
    leaderboard_rebuild_failed: bool = False
    leaderboard_rebuild_error: str | None = None

    @property
    def changed(self) -> bool:
        """role割り当てを実際に変更したかを返す.

        Returns:
            bool: statusがCHANGEDの場合はTrue.
        """
        return self.status is ChangeUserRoleStatus.CHANGED


class ChangeUserRoleCommand(Protocol):
    """ユーザーのroleを唯一のtarget roleへ置換するcommand boundaryを定義する."""

    async def execute(
        self,
        input_data: ChangeUserRoleCommandInput,
    ) -> ChangeUserRoleCommandResult:
        """入力に従ってrole変更を実行する.

        Args:
            input_data (ChangeUserRoleCommandInput): 対象usernameとtarget role名.

        Returns:
            ChangeUserRoleCommandResult: 変更可否と後続処理の状態を表す結果.
        """
        ...


class ChangeUserRoleCommandUseCase:
    """ユーザーの割り当てroleを一つのtarget roleへ置換する.

    Attributes:
        _uow_factory (UnitOfWorkFactory): role割り当てを更新するUnit of Workのfactory.
        _session_authorization_service (_SessionAuthorizationRefreshService): 認可更新service.
        _leaderboard_rebuild_wake (BeatmapLeaderboardRebuildWorkerWake): 再構築起動port.
        _system_user_id (int): role変更を拒否するsystem userのID.
    """

    _uow_factory: UnitOfWorkFactory
    _session_authorization_service: _SessionAuthorizationRefreshService
    _leaderboard_rebuild_wake: BeatmapLeaderboardRebuildWorkerWake
    _system_user_id: int

    def __init__(
        self,
        *,
        uow_factory: UnitOfWorkFactory,
        session_authorization_service: _SessionAuthorizationRefreshService,
        leaderboard_rebuild_wake: BeatmapLeaderboardRebuildWorkerWake | None = None,
        system_user_id: int = BANCHO_BOT_USER_ID,
    ) -> None:
        """role変更と後続処理に必要な依存を初期化する.

        Args:
            uow_factory (UnitOfWorkFactory): role割り当てを更新するUnit of Workのfactory.
            session_authorization_service (_SessionAuthorizationRefreshService): 認可更新service.
            leaderboard_rebuild_wake (BeatmapLeaderboardRebuildWorkerWake | None): 再構築起動port.
                Noneの場合はno-op実装を使う.
            system_user_id (int): role変更を拒否するsystem userのID.

        """
        self._uow_factory = uow_factory
        self._session_authorization_service = session_authorization_service
        self._leaderboard_rebuild_wake = (
            leaderboard_rebuild_wake or NoopBeatmapLeaderboardRebuildWorkerWake()
        )
        self._system_user_id = system_user_id

    async def execute(
        self,
        input_data: ChangeUserRoleCommandInput,
    ) -> ChangeUserRoleCommandResult:
        """Target roleだけをユーザーへ割り当て,authorizationを更新する.

        Args:
            input_data (ChangeUserRoleCommandInput): 対象usernameとtarget role名.

        Returns:
            ChangeUserRoleCommandResult: role変更,authorization更新,再構築要求の状態を表す結果.

        Notes:
            visibilityが変化した場合だけleaderboard再構築を要求し,その失敗は結果へ記録する.
        """
        safe_username = User.normalize_username(input_data.username)
        async with self._uow_factory() as uow:
            user = await uow.users.get_by_safe_username(safe_username)
            if user is None:
                return ChangeUserRoleCommandResult(
                    status=ChangeUserRoleStatus.USER_NOT_FOUND,
                    username=input_data.username,
                    role_name=input_data.role_name,
                )

            if user.id == self._system_user_id:
                return ChangeUserRoleCommandResult(
                    status=ChangeUserRoleStatus.SYSTEM_USER_DENIED,
                    username=user.username,
                    user_id=user.id,
                    role_name=input_data.role_name,
                )

            target_role = await uow.roles.get_by_name(input_data.role_name)
            if target_role is None:
                return ChangeUserRoleCommandResult(
                    status=ChangeUserRoleStatus.ROLE_NOT_FOUND,
                    username=user.username,
                    user_id=user.id,
                    role_name=input_data.role_name,
                )

            current_roles = await uow.roles.get_roles_for_user(user.id)
            current_role_ids = tuple(role.id for role in current_roles)
            previous_role_names = tuple(role.name for role in current_roles)
            previous_leaderboard_visible = is_leaderboard_visible_user(
                _combine_role_privileges(current_roles)
            )
            next_leaderboard_visible = is_leaderboard_visible_user(target_role.permissions)
            if current_role_ids == (target_role.id,):
                status = ChangeUserRoleStatus.UNCHANGED
            else:
                await uow.roles.set_roles_for_user(user.id, (target_role.id,))
                await uow.commit()
                status = ChangeUserRoleStatus.CHANGED

        refresh_result = await self._session_authorization_service.refresh_user_authorization(
            user.id
        )
        rebuild_requested = (
            status is ChangeUserRoleStatus.CHANGED
            and previous_leaderboard_visible != next_leaderboard_visible
        )
        rebuild_failed = False
        rebuild_error: str | None = None
        if rebuild_requested:
            try:
                await self._leaderboard_rebuild_wake.wake_user_rebuild(
                    user_id=user.id,
                    reason="user_visibility_changed",
                )
            except Exception as exc:
                rebuild_failed = True
                rebuild_error = str(exc)

        return ChangeUserRoleCommandResult(
            status=status,
            username=user.username,
            user_id=user.id,
            role_name=target_role.name,
            role_id=target_role.id,
            previous_role_names=previous_role_names,
            authorization_refresh_status=refresh_result.status,
            leaderboard_rebuild_requested=rebuild_requested,
            leaderboard_rebuild_failed=rebuild_failed,
            leaderboard_rebuild_error=rebuild_error,
        )


def _combine_role_privileges(roles: Iterable[Role]) -> Privileges:
    """複数roleのpermissionをビット和で結合する.

    Args:
        roles (Iterable[Role]): permissionを集約するrole列.

    Returns:
        Privileges: すべてのrole permissionを含む値.
    """
    privileges = Privileges.NONE
    for role in roles:
        privileges |= role.permissions
    return privileges


__all__ = [
    "ChangeUserRoleCommand",
    "ChangeUserRoleCommandInput",
    "ChangeUserRoleCommandResult",
    "ChangeUserRoleCommandUseCase",
    "ChangeUserRoleStatus",
]
