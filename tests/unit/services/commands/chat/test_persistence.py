"""chat永続化command use caseのUnit testを検証する."""

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
    """Channel message保存用のchannelをmemory UoWへ登録する.

    Args:
        uow_factory (InMemoryUnitOfWorkFactory): channelを永続化するmemory Unit of Work factory.
        name (str): 登録するchannel名.

    Returns:
        None: channelをcommitして、呼び出し側へ値を返さずに完了する.
    """
    async with uow_factory() as uow:
        _ = await uow.channels.create(make_channel(name=name))
        await uow.commit()


async def test_persist_channel_message_use_case_writes_through_uow() -> None:
    """Channel messageをcommitする永続化契約を検証する.

    登録済みchannelへmessageを送る条件で、成功resultとsender、channel、contentを持つrecordが
    memory stateに一件だけ観測できることを確認する.

    Returns:
        None: 永続化されたrecordを検証して、呼び出し側へ値を返さずに完了する.
    """
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
    """存在しないchannelの保存失敗がrollbackされる契約を検証する.

    未登録channelへmessageを送る条件で、CHANNEL_NOT_FOUND failure resultと空のchannel message
    stateが観測できることを確認する.

    Returns:
        None: failure resultと未永続化stateを検証して、呼び出し側へ値を返さずに完了する.
    """
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
    """Private messageをcommitする永続化契約を検証する.

    senderとtargetを持つmessageを送る条件で、成功resultと両user IDおよびcontentを持つrecordが
    memory stateに観測できることを確認する.

    Returns:
        None: 永続化されたprivate messageを検証して、呼び出し側へ値を返さずに完了する.
    """
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
    """Channel messageのruntime未構成をfailure resultへ変換する契約を検証する.

    Unit of Work factoryなしでuse caseを実行する条件で、RUNTIME_UNAVAILABLE failure resultが
    観測できることを確認する.

    Returns:
        None: runtime未構成のfailure resultを検証して、呼び出し側へ値を返さずに完了する.
    """
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
    """Private messageのruntime未構成をfailure resultへ変換する契約を検証する.

    Unit of Work factoryなしでuse caseを実行する条件で、RUNTIME_UNAVAILABLE failure resultが
    観測できることを確認する.

    Returns:
        None: runtime未構成のfailure resultを検証して、呼び出し側へ値を返さずに完了する.
    """
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
