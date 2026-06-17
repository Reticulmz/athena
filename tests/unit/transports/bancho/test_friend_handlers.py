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
    def __init__(self) -> None:
        self.calls: list[AddFriendCommand] = []

    async def execute(self, command: AddFriendCommand) -> FriendMutationOutcome:
        self.calls.append(command)
        return FriendMutationOutcome(status=FriendMutationStatus.ADDED)


class StubRemoveFriendUseCase:
    def __init__(self) -> None:
        self.calls: list[RemoveFriendCommand] = []

    async def execute(self, command: RemoveFriendCommand) -> FriendMutationOutcome:
        self.calls.append(command)
        return FriendMutationOutcome(status=FriendMutationStatus.REMOVED)


class StubUpdateFriendOnlyDmUseCase:
    def __init__(self) -> None:
        self.calls: list[UpdateFriendOnlyDmCommand] = []

    async def execute(self, command: UpdateFriendOnlyDmCommand) -> bool:
        self.calls.append(command)
        return True


async def test_add_friend_parses_int32_target_and_calls_use_case() -> None:
    add_friend = StubAddFriendUseCase()
    handlers = _handlers(add_friend=add_friend)

    await handlers.handle_add_friend(friend_user_id_payload(42), user_id=7)

    assert add_friend.calls == [AddFriendCommand(owner_user_id=7, target_user_id=42)]


async def test_remove_friend_parses_int32_target_and_calls_use_case() -> None:
    remove_friend = StubRemoveFriendUseCase()
    handlers = _handlers(remove_friend=remove_friend)

    await handlers.handle_remove_friend(friend_user_id_payload(42), user_id=7)

    assert remove_friend.calls == [RemoveFriendCommand(owner_user_id=7, target_user_id=42)]


async def test_change_friendonly_dms_parses_boolean_and_calls_use_case() -> None:
    update_friend_only_dm = StubUpdateFriendOnlyDmUseCase()
    handlers = _handlers(update_friend_only_dm=update_friend_only_dm)

    await handlers.handle_change_friendonly_dms(friend_only_dms_payload(True), user_id=7)
    await handlers.handle_change_friendonly_dms(friend_only_dms_payload(False), user_id=7)

    assert update_friend_only_dm.calls == [
        UpdateFriendOnlyDmCommand(user_id=7, enabled=True),
        UpdateFriendOnlyDmCommand(user_id=7, enabled=False),
    ]


async def test_malformed_payloads_are_dropped_without_mutation() -> None:
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
    return FriendHandlers(
        add_friend=add_friend or StubAddFriendUseCase(),
        remove_friend=remove_friend or StubRemoveFriendUseCase(),
        update_friend_only_dm=update_friend_only_dm or StubUpdateFriendOnlyDmUseCase(),
    )
