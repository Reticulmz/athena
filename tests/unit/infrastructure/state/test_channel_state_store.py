"""ChannelStateStoreのmemory実装に対する契約を検証する."""

from __future__ import annotations

import pytest

from osu_server.infrastructure.state.interfaces.channel_state_store import (
    ChannelStateStore,
)
from osu_server.infrastructure.state.memory.channel_state_store import (
    InMemoryChannelStateStore,
)


@pytest.fixture
def store() -> InMemoryChannelStateStore:
    """各testへ空の双方向membership storeを提供する.

    Returns:
        InMemoryChannelStateStore: 各testで独立して使用するchannel membership store.
    """
    return InMemoryChannelStateStore()


# -- Protocol conformance ----------------------------------------------------


def test_implements_protocol() -> None:
    """memory実装を生成したときChannelStateStore Protocolとして認識されることを確認する.

    Returns:
        None: 検証を完了し値を返さない.
    """
    assert isinstance(InMemoryChannelStateStore(), ChannelStateStore)


# -- add_member / is_member --------------------------------------------------


async def test_add_member_and_is_member(store: InMemoryChannelStateStore) -> None:
    """空のstoreへmemberを追加したときmembership照会がTrueを返すことを確認する.

    Args:
        store (InMemoryChannelStateStore): 検証対象の空のchannel membership store.

    Returns:
        None: 検証を完了し値を返さない.
    """
    await store.add_member("#osu", 1)

    assert await store.is_member("#osu", 1) is True


async def test_is_member_returns_false_for_non_member(
    store: InMemoryChannelStateStore,
) -> None:
    """未登録channelを照会したときmembership照会がFalseを返すことを確認する.

    Args:
        store (InMemoryChannelStateStore): 検証対象の空のchannel membership store.

    Returns:
        None: 検証を完了し値を返さない.
    """
    assert await store.is_member("#osu", 1) is False


async def test_add_member_idempotent(store: InMemoryChannelStateStore) -> None:
    """同じmemberを二度追加したとき取得集合が重複なく1件に保たれることを確認する.

    Args:
        store (InMemoryChannelStateStore): 検証対象の空のchannel membership store.

    Returns:
        None: 検証を完了し値を返さない.
    """
    await store.add_member("#osu", 1)
    await store.add_member("#osu", 1)

    members = await store.get_members("#osu")
    assert members == {1}


# -- remove_member -----------------------------------------------------------


async def test_remove_member(store: InMemoryChannelStateStore) -> None:
    """登録済みmemberを削除したときmembership照会がFalseへ変わることを確認する.

    Args:
        store (InMemoryChannelStateStore): 検証対象の空のchannel membership store.

    Returns:
        None: 検証を完了し値を返さない.
    """
    await store.add_member("#osu", 1)
    await store.remove_member("#osu", 1)

    assert await store.is_member("#osu", 1) is False


async def test_remove_member_idempotent(store: InMemoryChannelStateStore) -> None:
    """未登録memberを削除したとき例外を出さずmembershipがFalseのままであることを確認する.

    Args:
        store (InMemoryChannelStateStore): 検証対象の空のchannel membership store.

    Returns:
        None: 検証を完了し値を返さない.
    """
    await store.remove_member("#osu", 999)

    assert await store.is_member("#osu", 999) is False


# -- get_members / get_member_count ------------------------------------------


async def test_get_members_returns_all(store: InMemoryChannelStateStore) -> None:
    """3人を同じchannelへ追加したとき全user IDの集合を返すことを確認する.

    Args:
        store (InMemoryChannelStateStore): 検証対象の空のchannel membership store.

    Returns:
        None: 検証を完了し値を返さない.
    """
    await store.add_member("#osu", 1)
    await store.add_member("#osu", 2)
    await store.add_member("#osu", 3)

    members = await store.get_members("#osu")

    assert members == {1, 2, 3}


async def test_get_members_empty_channel(store: InMemoryChannelStateStore) -> None:
    """未知channelを取得したとき空集合を返すことを確認する.

    Args:
        store (InMemoryChannelStateStore): 検証対象の空のchannel membership store.

    Returns:
        None: 検証を完了し値を返さない.
    """
    members = await store.get_members("#unknown")

    assert members == set()


async def test_get_member_count(store: InMemoryChannelStateStore) -> None:
    """2人を追加したchannelのmember数を取得したとき2を返すことを確認する.

    Args:
        store (InMemoryChannelStateStore): 検証対象の空のchannel membership store.

    Returns:
        None: 検証を完了し値を返さない.
    """
    await store.add_member("#osu", 1)
    await store.add_member("#osu", 2)

    count = await store.get_member_count("#osu")

    expected_count = 2
    assert count == expected_count


async def test_get_member_count_empty_channel(
    store: InMemoryChannelStateStore,
) -> None:
    """未知channelのmember数を取得したとき0を返すことを確認する.

    Args:
        store (InMemoryChannelStateStore): 検証対象の空のchannel membership store.

    Returns:
        None: 検証を完了し値を返さない.
    """
    count = await store.get_member_count("#unknown")

    assert count == 0


# -- get_user_channels -------------------------------------------------------


async def test_get_user_channels(store: InMemoryChannelStateStore) -> None:
    """同じuserを3つのchannelへ追加したとき所属channel集合を返すことを確認する.

    Args:
        store (InMemoryChannelStateStore): 検証対象の空のchannel membership store.

    Returns:
        None: 検証を完了し値を返さない.
    """
    await store.add_member("#osu", 1)
    await store.add_member("#announce", 1)
    await store.add_member("#japanese", 1)

    channels = await store.get_user_channels(1)

    assert channels == {"#osu", "#announce", "#japanese"}


async def test_get_user_channels_empty(store: InMemoryChannelStateStore) -> None:
    """未知userの所属channelを取得したとき空集合を返すことを確認する.

    Args:
        store (InMemoryChannelStateStore): 検証対象の空のchannel membership store.

    Returns:
        None: 検証を完了し値を返さない.
    """
    channels = await store.get_user_channels(9999)

    assert channels == set()


# -- remove_user_from_all ----------------------------------------------------


async def test_remove_user_from_all_returns_channels(
    store: InMemoryChannelStateStore,
) -> None:
    """複数channelのmemberを全削除したとき削除対象channel集合を返すことを確認する.

    Args:
        store (InMemoryChannelStateStore): 検証対象の空のchannel membership store.

    Returns:
        None: 検証を完了し値を返さない.
    """
    await store.add_member("#osu", 1)
    await store.add_member("#announce", 1)

    removed = await store.remove_user_from_all(1)

    assert removed == {"#osu", "#announce"}


async def test_remove_user_from_all_clears_membership(
    store: InMemoryChannelStateStore,
) -> None:
    """全channelからuserを削除したとき全membershipと逆引きが空になることを確認する.

    Args:
        store (InMemoryChannelStateStore): 検証対象の空のchannel membership store.

    Returns:
        None: 検証を完了し値を返さない.
    """
    await store.add_member("#osu", 1)
    await store.add_member("#announce", 1)

    _ = await store.remove_user_from_all(1)

    assert await store.is_member("#osu", 1) is False
    assert await store.is_member("#announce", 1) is False
    assert await store.get_user_channels(1) == set()


async def test_remove_user_from_all_updates_channel_members(
    store: InMemoryChannelStateStore,
) -> None:
    """全channelから一人を削除したとき各channelの残存member集合を更新することを確認する.

    Args:
        store (InMemoryChannelStateStore): 検証対象の空のchannel membership store.

    Returns:
        None: 検証を完了し値を返さない.
    """
    await store.add_member("#osu", 1)
    await store.add_member("#osu", 2)
    await store.add_member("#announce", 1)

    _ = await store.remove_user_from_all(1)

    assert await store.get_members("#osu") == {2}
    assert await store.get_members("#announce") == set()


async def test_remove_user_from_all_empty(store: InMemoryChannelStateStore) -> None:
    """未知userを全削除したとき空集合を返すことを確認する.

    Args:
        store (InMemoryChannelStateStore): 検証対象の空のchannel membership store.

    Returns:
        None: 検証を完了し値を返さない.
    """
    removed = await store.remove_user_from_all(9999)

    assert removed == set()


# -- Bidirectional index consistency -----------------------------------------


async def test_bidirectional_consistency_after_add(
    store: InMemoryChannelStateStore,
) -> None:
    """複数membershipを追加したときchannel側とuser側の両indexが一致することを確認する.

    Args:
        store (InMemoryChannelStateStore): 検証対象の空のchannel membership store.

    Returns:
        None: 検証を完了し値を返さない.
    """
    await store.add_member("#osu", 1)
    await store.add_member("#osu", 2)
    await store.add_member("#announce", 1)

    # channel -> members
    assert await store.get_members("#osu") == {1, 2}
    assert await store.get_members("#announce") == {1}

    # user -> channels
    assert await store.get_user_channels(1) == {"#osu", "#announce"}
    assert await store.get_user_channels(2) == {"#osu"}


async def test_bidirectional_consistency_after_remove(
    store: InMemoryChannelStateStore,
) -> None:
    """一つのmembershipを削除したときchannel側とuser側の両indexが同期することを確認する.

    Args:
        store (InMemoryChannelStateStore): 検証対象の空のchannel membership store.

    Returns:
        None: 検証を完了し値を返さない.
    """
    await store.add_member("#osu", 1)
    await store.add_member("#osu", 2)
    await store.add_member("#announce", 1)

    await store.remove_member("#osu", 1)

    # channel -> members
    assert await store.get_members("#osu") == {2}
    assert await store.get_members("#announce") == {1}

    # user -> channels
    assert await store.get_user_channels(1) == {"#announce"}
    assert await store.get_user_channels(2) == {"#osu"}


async def test_bidirectional_consistency_after_remove_user_from_all(
    store: InMemoryChannelStateStore,
) -> None:
    """userの全membershipを削除したとき両indexで他userの状態を保つことを確認する.

    Args:
        store (InMemoryChannelStateStore): 検証対象の空のchannel membership store.

    Returns:
        None: 検証を完了し値を返さない.
    """
    await store.add_member("#osu", 1)
    await store.add_member("#osu", 2)
    await store.add_member("#announce", 1)
    await store.add_member("#announce", 2)
    await store.add_member("#japanese", 1)

    _ = await store.remove_user_from_all(1)

    # channel -> members: user 1 removed from all
    assert await store.get_members("#osu") == {2}
    assert await store.get_members("#announce") == {2}
    assert await store.get_members("#japanese") == set()

    # user -> channels: user 1 has no channels, user 2 unaffected
    assert await store.get_user_channels(1) == set()
    assert await store.get_user_channels(2) == {"#osu", "#announce"}


# -- get_members returns a copy ----------------------------------------------


async def test_get_members_returns_copy(store: InMemoryChannelStateStore) -> None:
    """取得したmember集合を変更してもstore内のmembershipが変わらないことを確認する.

    Args:
        store (InMemoryChannelStateStore): 検証対象の空のchannel membership store.

    Returns:
        None: 検証を完了し値を返さない.
    """
    await store.add_member("#osu", 1)

    members = await store.get_members("#osu")
    members.add(999)

    assert await store.get_members("#osu") == {1}


async def test_get_user_channels_returns_copy(
    store: InMemoryChannelStateStore,
) -> None:
    """取得したchannel集合を変更してもstore内の逆indexが変わらないことを確認する.

    Args:
        store (InMemoryChannelStateStore): 検証対象の空のchannel membership store.

    Returns:
        None: 検証を完了し値を返さない.
    """
    await store.add_member("#osu", 1)

    channels = await store.get_user_channels(1)
    channels.add("#fake")

    assert await store.get_user_channels(1) == {"#osu"}
