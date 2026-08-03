"""Bancho friend handlerがpayloadをidentity commandへ変換することを検証する."""

from __future__ import annotations

from osu_server.domain.identity.friends import (
    FriendMutationOutcome,
    FriendMutationStatus,
)
from osu_server.services.commands.identity import (
    AddFriendCommand,
    RemoveFriendCommand,
    UpdateFriendOnlyDmCommand,
)
from osu_server.transports.stable.bancho.handlers.friends import FriendHandlers
from osu_server.transports.stable.bancho.protocol.c2s import (
    friend_only_dms_payload,
    friend_user_id_payload,
)


class StubAddFriendUseCase:
    """Add friend commandを記録して成功結果を返すtest stub.

    Attributes:
        calls (list[AddFriendCommand]): executeへ渡されたcommandの呼出順list.
    """

    def __init__(self) -> None:
        """空のcommand記録を持つstubを初期化する."""
        self.calls: list[AddFriendCommand] = []

    async def execute(self, command: AddFriendCommand) -> FriendMutationOutcome:
        """Add friend commandを記録してADDED outcomeを返す.

        Args:
            command (AddFriendCommand): handlerが構築したfriend追加command.

        Returns:
            FriendMutationOutcome: ADDED statusを持つ成功outcome.
        """
        self.calls.append(command)
        return FriendMutationOutcome(status=FriendMutationStatus.ADDED)


class StubRemoveFriendUseCase:
    """Remove friend commandを記録して成功結果を返すtest stub.

    Attributes:
        calls (list[RemoveFriendCommand]): executeへ渡されたcommandの呼出順list.
    """

    def __init__(self) -> None:
        """空のcommand記録を持つstubを初期化する."""
        self.calls: list[RemoveFriendCommand] = []

    async def execute(self, command: RemoveFriendCommand) -> FriendMutationOutcome:
        """Remove friend commandを記録してREMOVED outcomeを返す.

        Args:
            command (RemoveFriendCommand): handlerが構築したfriend削除command.

        Returns:
            FriendMutationOutcome: REMOVED statusを持つ成功outcome.
        """
        self.calls.append(command)
        return FriendMutationOutcome(status=FriendMutationStatus.REMOVED)


class StubUpdateFriendOnlyDmUseCase:
    """Friend only DM設定commandを記録して成功を返すtest stub.

    Attributes:
        calls (list[UpdateFriendOnlyDmCommand]): executeへ渡されたcommandの呼出順list.
    """

    def __init__(self) -> None:
        """空のcommand記録を持つstubを初期化する."""
        self.calls: list[UpdateFriendOnlyDmCommand] = []

    async def execute(self, command: UpdateFriendOnlyDmCommand) -> bool:
        """Friend only DM設定commandを記録して成功を返す.

        Args:
            command (UpdateFriendOnlyDmCommand): handlerが構築した設定更新command.

        Returns:
            bool: 常にTrue. testでcommand生成だけを検証できる成功値.
        """
        self.calls.append(command)
        return True


async def test_add_friend_parses_int32_target_and_calls_use_case() -> None:
    """Add friend payloadのint32 targetをcommandへ変換することを検証する.

    Returns:
        None: ownerとtarget user IDを持つAddFriendCommandの記録を確認して完了する.
    """
    add_friend = StubAddFriendUseCase()
    handlers = _handlers(add_friend=add_friend)

    await handlers.handle_add_friend(friend_user_id_payload(42), user_id=7)

    assert add_friend.calls == [AddFriendCommand(owner_user_id=7, target_user_id=42)]


async def test_remove_friend_parses_int32_target_and_calls_use_case() -> None:
    """Remove friend payloadのint32 targetをcommandへ変換することを検証する.

    Returns:
        None: ownerとtarget user IDを持つRemoveFriendCommandの記録を確認して完了する.
    """
    remove_friend = StubRemoveFriendUseCase()
    handlers = _handlers(remove_friend=remove_friend)

    await handlers.handle_remove_friend(friend_user_id_payload(42), user_id=7)

    assert remove_friend.calls == [RemoveFriendCommand(owner_user_id=7, target_user_id=42)]


async def test_change_friendonly_dms_parses_boolean_and_calls_use_case() -> None:
    """Friend only DM payloadのboolean値を更新commandへ変換することを検証する.

    Returns:
        None: trueとfalseを保った2件のUpdateFriendOnlyDmCommandを確認して完了する.
    """
    update_friend_only_dm = StubUpdateFriendOnlyDmUseCase()
    handlers = _handlers(update_friend_only_dm=update_friend_only_dm)

    await handlers.handle_change_friendonly_dms(friend_only_dms_payload(True), user_id=7)
    await handlers.handle_change_friendonly_dms(friend_only_dms_payload(False), user_id=7)

    assert update_friend_only_dm.calls == [
        UpdateFriendOnlyDmCommand(user_id=7, enabled=True),
        UpdateFriendOnlyDmCommand(user_id=7, enabled=False),
    ]


async def test_malformed_payloads_are_dropped_without_mutation() -> None:
    """Malformed friend payloadがidentity commandを発行しないことを検証する.

    Returns:
        None: add/remove/setting各stubのcommand記録が空であることを確認して完了する.
    """
    add_friend = StubAddFriendUseCase()
    remove_friend = StubRemoveFriendUseCase()
    update_friend_only_dm = StubUpdateFriendOnlyDmUseCase()
    handlers = _handlers(
        add_friend=add_friend,
        remove_friend=remove_friend,
        update_friend_only_dm=update_friend_only_dm,
    )

    await handlers.handle_add_friend(b"\x01\x02", user_id=7)
    await handlers.handle_remove_friend(b"\x01\x02", user_id=7)
    await handlers.handle_change_friendonly_dms(b"", user_id=7)
    await handlers.handle_change_friendonly_dms(b"\x01\x00", user_id=7)
    await handlers.handle_change_friendonly_dms(b"\x02", user_id=7)

    assert add_friend.calls == []
    assert remove_friend.calls == []
    assert update_friend_only_dm.calls == []


def _handlers(
    *,
    add_friend: StubAddFriendUseCase | None = None,
    remove_friend: StubRemoveFriendUseCase | None = None,
    update_friend_only_dm: StubUpdateFriendOnlyDmUseCase | None = None,
) -> FriendHandlers:
    """指定stubを持つFriendHandlersを構築する.

    Args:
        add_friend (StubAddFriendUseCase | None): add handlerへ渡すstub. None時は新規stubを使う.
        remove_friend (StubRemoveFriendUseCase | None): remove handler用stub.
            None時は新規stubを使う.
        update_friend_only_dm (StubUpdateFriendOnlyDmUseCase | None): setting handler用stub.
            None時は新規stubを使う.

    Returns:
        FriendHandlers: friend command用stubが注入済みのhandler集合.
    """
    return FriendHandlers(
        add_friend=add_friend or StubAddFriendUseCase(),
        remove_friend=remove_friend or StubRemoveFriendUseCase(),
        update_friend_only_dm=update_friend_only_dm or StubUpdateFriendOnlyDmUseCase(),
    )
