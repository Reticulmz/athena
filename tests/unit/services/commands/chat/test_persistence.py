"""Tests for chat persistence command use-cases."""

from __future__ import annotations

from tests.factories.domain import make_channel

from osu_server.domain.chat import ChatPersistenceFailureReason
from osu_server.repositories.memory.commands.state import InMemoryCommandRepositoryState
from osu_server.repositories.memory.unit_of_work import InMemoryUnitOfWorkFactory
from osu_server.services.commands.chat import (
    PersistChannelMessageCommand,
    PersistChannelMessageUseCase,
    PersistPrivateMessageCommand,
    PersistPrivateMessageUseCase,
)


async def _seed_channel(
    uow_factory: InMemoryUnitOfWorkFactory,
    *,
    name: str = "#osu",
) -> None:
    async with uow_factory() as uow:
        _ = await uow.channels.create(make_channel(name=name))
        await uow.commit()


async def test_persist_channel_message_use_case_writes_through_uow() -> None:
    state = InMemoryCommandRepositoryState()
    uow_factory = InMemoryUnitOfWorkFactory(state)
    await _seed_channel(uow_factory)
    use_case = PersistChannelMessageUseCase(uow_factory=uow_factory)

    result = await use_case.execute(
        PersistChannelMessageCommand(
            sender_id=1,
            channel_name="#osu",
            content="hello",
        )
    )

    assert result.success is True
    assert result.reason is None
    records = list(state.channel_messages_by_id.values())
    assert [(record.sender_id, record.channel_name, record.content) for record in records] == [
        (1, "#osu", "hello")
    ]


async def test_persist_channel_message_use_case_rolls_back_repository_failure() -> None:
    state = InMemoryCommandRepositoryState()
    use_case = PersistChannelMessageUseCase(uow_factory=InMemoryUnitOfWorkFactory(state))

    result = await use_case.execute(
        PersistChannelMessageCommand(
            sender_id=1,
            channel_name="#missing",
            content="hello",
        )
    )

    assert result.success is False
    assert result.reason is ChatPersistenceFailureReason.CHANNEL_NOT_FOUND
    assert state.channel_messages_by_id == {}


async def test_persist_private_message_use_case_writes_through_uow() -> None:
    state = InMemoryCommandRepositoryState()
    use_case = PersistPrivateMessageUseCase(
        uow_factory=InMemoryUnitOfWorkFactory(state),
    )

    result = await use_case.execute(
        PersistPrivateMessageCommand(
            sender_id=1,
            target_id=2,
            content="secret",
        )
    )

    assert result.success is True
    assert result.reason is None
    records = list(state.private_messages_by_id.values())
    assert [(record.sender_id, record.target_id, record.content) for record in records] == [
        (1, 2, "secret")
    ]


async def test_persist_channel_message_use_case_reports_missing_runtime() -> None:
    use_case = PersistChannelMessageUseCase()

    result = await use_case.execute(
        PersistChannelMessageCommand(
            sender_id=1,
            channel_name="#osu",
            content="hello",
        )
    )

    assert result.success is False
    assert result.reason is ChatPersistenceFailureReason.RUNTIME_UNAVAILABLE


async def test_persist_private_message_use_case_reports_missing_runtime() -> None:
    use_case = PersistPrivateMessageUseCase()

    result = await use_case.execute(
        PersistPrivateMessageCommand(
            sender_id=1,
            target_id=2,
            content="secret",
        )
    )

    assert result.success is False
    assert result.reason is ChatPersistenceFailureReason.RUNTIME_UNAVAILABLE
