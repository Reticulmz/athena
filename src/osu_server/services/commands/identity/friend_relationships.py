"""friend relationshipとFriend-Only DMを変更するcommand use-caseを提供する."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Protocol

from osu_server.domain.identity.friends import (
    FriendableSystemUserCatalog,
    FriendMutationOutcome,
    FriendMutationStatus,
)

if TYPE_CHECKING:
    from osu_server.repositories.interfaces.session_store import SessionPrivacyRuntime
    from osu_server.repositories.interfaces.unit_of_work import UnitOfWorkFactory


@dataclass(frozen=True, slots=True)
class AddFriendCommand:
    """一方向のfriend relationship追加要求を表す.

    Attributes:
        owner_user_id (int): relationshipを追加するユーザーID.
        target_user_id (int): friendとして追加する対象ユーザーID.
    """

    owner_user_id: int
    target_user_id: int


@dataclass(frozen=True, slots=True)
class RemoveFriendCommand:
    """一方向のfriend relationship削除要求を表す.

    Attributes:
        owner_user_id (int): relationshipを削除するユーザーID.
        target_user_id (int): friendから削除する対象ユーザーID.
    """

    owner_user_id: int
    target_user_id: int


@dataclass(frozen=True, slots=True)
class UpdateFriendOnlyDmCommand:
    """active sessionのFriend-Only DM設定変更要求を表す.

    Attributes:
        user_id (int): 設定を更新するユーザーID.
        enabled (bool): Friend-Only DMを有効にする場合はTrue.
    """

    user_id: int
    enabled: bool


class AddFriendCommandUseCase(Protocol):
    """friend relationship追加workflowのcommand boundaryを定義する."""

    async def execute(self, command: AddFriendCommand) -> FriendMutationOutcome:
        """Friend relationshipの追加要求を実行する.

        Args:
            command (AddFriendCommand): relationshipを追加するownerとtarget.

        Returns:
            FriendMutationOutcome: 追加またはno-opを表す結果.
        """
        ...


class RemoveFriendCommandUseCase(Protocol):
    """friend relationship削除workflowのcommand boundaryを定義する."""

    async def execute(self, command: RemoveFriendCommand) -> FriendMutationOutcome:
        """Friend relationshipの削除要求を実行する.

        Args:
            command (RemoveFriendCommand): relationshipを削除するownerとtarget.

        Returns:
            FriendMutationOutcome: 削除またはno-opを表す結果.
        """
        ...


class UpdateFriendOnlyDmCommandUseCase(Protocol):
    """Friend-Only DM設定変更workflowのcommand boundaryを定義する."""

    async def execute(self, command: UpdateFriendOnlyDmCommand) -> bool:
        """Active sessionのFriend-Only DM設定を更新する.

        Args:
            command (UpdateFriendOnlyDmCommand): 更新対象ユーザーと有効状態.

        Returns:
            bool: active sessionの設定を更新できた場合はTrue.
        """
        ...


class AddFriendUseCase:
    """Bancho互換のno-op規則で一方向friend relationshipを追加する.

    Attributes:
        _uow_factory (UnitOfWorkFactory): friend relationshipを書き込むUnit of Workのfactory.
        _system_user_catalog (FriendableSystemUserCatalog): 許可targetを判定するcatalog.
    """

    def __init__(
        self,
        *,
        uow_factory: UnitOfWorkFactory,
        system_user_catalog: FriendableSystemUserCatalog,
    ) -> None:
        """Friend relationship追加に必要な依存を初期化する.

        Args:
            uow_factory (UnitOfWorkFactory): friend relationshipを書き込むUnit of Workのfactory.
            system_user_catalog (FriendableSystemUserCatalog): 許可targetを判定するcatalog.

        """
        self._uow_factory: UnitOfWorkFactory = uow_factory
        self._system_user_catalog: FriendableSystemUserCatalog = system_user_catalog

    async def execute(self, command: AddFriendCommand) -> FriendMutationOutcome:
        """一方向friend relationshipを追加する.

        Args:
            command (AddFriendCommand): relationshipを追加するownerとtarget.

        Returns:
            FriendMutationOutcome: 追加成功またはBancho互換no-opを表す結果.

        Notes:
            self target、許可されないsystem user、存在しないtarget、重複は永続化せずno-opになる.
        """
        if command.owner_user_id == command.target_user_id:
            return _no_op()
        if not self._system_user_catalog.allows_target(command.target_user_id):
            return _no_op()

        async with self._uow_factory() as uow:
            if not await uow.friends.target_exists(command.target_user_id):
                return _no_op()
            changed = await uow.friends.add_relationship(
                command.owner_user_id,
                command.target_user_id,
            )
            if changed:
                await uow.commit()
                return FriendMutationOutcome(status=FriendMutationStatus.ADDED)
        return _no_op()


class RemoveFriendUseCase:
    """存在しないrelationshipもno-opとして一方向friend relationshipを削除する.

    Attributes:
        _uow_factory (UnitOfWorkFactory): friend relationshipを削除するUnit of Workのfactory.
    """

    def __init__(self, *, uow_factory: UnitOfWorkFactory) -> None:
        """Friend relationship削除に必要な依存を初期化する.

        Args:
            uow_factory (UnitOfWorkFactory): friend relationshipを削除するUnit of Workのfactory.

        """
        self._uow_factory: UnitOfWorkFactory = uow_factory

    async def execute(self, command: RemoveFriendCommand) -> FriendMutationOutcome:
        """一方向friend relationshipを削除する.

        Args:
            command (RemoveFriendCommand): relationshipを削除するownerとtarget.

        Returns:
            FriendMutationOutcome: 削除成功またはidempotentなno-opを表す結果.

        Notes:
            self targetと存在しないrelationshipは永続化せずno-opになる.
        """
        if command.owner_user_id == command.target_user_id:
            return _no_op()

        async with self._uow_factory() as uow:
            changed = await uow.friends.remove_relationship(
                command.owner_user_id,
                command.target_user_id,
            )
            if changed:
                await uow.commit()
                return FriendMutationOutcome(status=FriendMutationStatus.REMOVED)
        return _no_op()


class UpdateFriendOnlyDmUseCase:
    """active sessionのFriend-Only DM状態を更新する.

    Attributes:
        _session_store (SessionPrivacyRuntime): active sessionのprivacy状態を更新するruntime store.
    """

    def __init__(self, *, session_store: SessionPrivacyRuntime) -> None:
        """Friend-Only DM状態を更新するruntime storeを初期化する.

        Args:
            session_store (SessionPrivacyRuntime): session privacyを更新するruntime store.

        """
        self._session_store: SessionPrivacyRuntime = session_store

    async def execute(self, command: UpdateFriendOnlyDmCommand) -> bool:
        """Active sessionのFriend-Only DM状態を更新する.

        Args:
            command (UpdateFriendOnlyDmCommand): 更新対象ユーザーと有効状態.

        Returns:
            bool: active sessionの設定を更新できた場合はTrue.

        Notes:
            durable user preferenceではなく、現在存在するsessionだけを更新する.
        """
        return await self._session_store.update_pm_private(command.user_id, command.enabled)


def _no_op() -> FriendMutationOutcome:
    """永続状態を変更しないfriend mutation結果を作成する.

    Returns:
        FriendMutationOutcome: statusがNO_OPの結果.
    """
    return FriendMutationOutcome(status=FriendMutationStatus.NO_OP)


__all__ = [
    "AddFriendCommand",
    "AddFriendCommandUseCase",
    "AddFriendUseCase",
    "RemoveFriendCommand",
    "RemoveFriendCommandUseCase",
    "RemoveFriendUseCase",
    "UpdateFriendOnlyDmCommand",
    "UpdateFriendOnlyDmCommandUseCase",
    "UpdateFriendOnlyDmUseCase",
]
