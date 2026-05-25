"""Tests for ChannelStateStore Protocol + InMemoryChannelStateStore."""

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
    return InMemoryChannelStateStore()


# -- Protocol conformance ----------------------------------------------------


def test_implements_protocol() -> None:
    """InMemoryChannelStateStore satisfies the ChannelStateStore Protocol."""
    assert isinstance(InMemoryChannelStateStore(), ChannelStateStore)


# -- add_member / is_member --------------------------------------------------


async def test_add_member_and_is_member(store: InMemoryChannelStateStore) -> None:
    """add_member registers the user; is_member returns True."""
    await store.add_member("#osu", 1)

    assert await store.is_member("#osu", 1) is True


async def test_is_member_returns_false_for_non_member(
    store: InMemoryChannelStateStore,
) -> None:
    """is_member returns False for a user not in the channel."""
    assert await store.is_member("#osu", 1) is False


async def test_add_member_idempotent(store: InMemoryChannelStateStore) -> None:
    """Adding the same user twice does not duplicate entries."""
    await store.add_member("#osu", 1)
    await store.add_member("#osu", 1)

    members = await store.get_members("#osu")
    assert members == {1}


# -- remove_member -----------------------------------------------------------


async def test_remove_member(store: InMemoryChannelStateStore) -> None:
    """remove_member unregisters the user from the channel."""
    await store.add_member("#osu", 1)
    await store.remove_member("#osu", 1)

    assert await store.is_member("#osu", 1) is False


async def test_remove_member_idempotent(store: InMemoryChannelStateStore) -> None:
    """Removing a non-member is a no-op (no error)."""
    await store.remove_member("#osu", 999)

    assert await store.is_member("#osu", 999) is False


# -- get_members / get_member_count ------------------------------------------


async def test_get_members_returns_all(store: InMemoryChannelStateStore) -> None:
    """get_members returns the full set of member user IDs."""
    await store.add_member("#osu", 1)
    await store.add_member("#osu", 2)
    await store.add_member("#osu", 3)

    members = await store.get_members("#osu")

    assert members == {1, 2, 3}


async def test_get_members_empty_channel(store: InMemoryChannelStateStore) -> None:
    """get_members returns an empty set for an unknown channel."""
    members = await store.get_members("#unknown")

    assert members == set()


async def test_get_member_count(store: InMemoryChannelStateStore) -> None:
    """get_member_count returns the number of members."""
    await store.add_member("#osu", 1)
    await store.add_member("#osu", 2)

    count = await store.get_member_count("#osu")

    expected_count = 2
    assert count == expected_count


async def test_get_member_count_empty_channel(
    store: InMemoryChannelStateStore,
) -> None:
    """get_member_count returns 0 for an unknown channel."""
    count = await store.get_member_count("#unknown")

    assert count == 0


# -- get_user_channels -------------------------------------------------------


async def test_get_user_channels(store: InMemoryChannelStateStore) -> None:
    """get_user_channels returns all channels the user has joined."""
    await store.add_member("#osu", 1)
    await store.add_member("#announce", 1)
    await store.add_member("#japanese", 1)

    channels = await store.get_user_channels(1)

    assert channels == {"#osu", "#announce", "#japanese"}


async def test_get_user_channels_empty(store: InMemoryChannelStateStore) -> None:
    """get_user_channels returns an empty set for an unknown user."""
    channels = await store.get_user_channels(9999)

    assert channels == set()


# -- remove_user_from_all ----------------------------------------------------


async def test_remove_user_from_all_returns_channels(
    store: InMemoryChannelStateStore,
) -> None:
    """remove_user_from_all returns the set of channels the user was in."""
    await store.add_member("#osu", 1)
    await store.add_member("#announce", 1)

    removed = await store.remove_user_from_all(1)

    assert removed == {"#osu", "#announce"}


async def test_remove_user_from_all_clears_membership(
    store: InMemoryChannelStateStore,
) -> None:
    """After remove_user_from_all, the user is no longer in any channel."""
    await store.add_member("#osu", 1)
    await store.add_member("#announce", 1)

    _ = await store.remove_user_from_all(1)

    assert await store.is_member("#osu", 1) is False
    assert await store.is_member("#announce", 1) is False
    assert await store.get_user_channels(1) == set()


async def test_remove_user_from_all_updates_channel_members(
    store: InMemoryChannelStateStore,
) -> None:
    """remove_user_from_all removes the user from each channel's member set."""
    await store.add_member("#osu", 1)
    await store.add_member("#osu", 2)
    await store.add_member("#announce", 1)

    _ = await store.remove_user_from_all(1)

    assert await store.get_members("#osu") == {2}
    assert await store.get_members("#announce") == set()


async def test_remove_user_from_all_empty(store: InMemoryChannelStateStore) -> None:
    """remove_user_from_all for an unknown user returns an empty set."""
    removed = await store.remove_user_from_all(9999)

    assert removed == set()


# -- Bidirectional index consistency -----------------------------------------


async def test_bidirectional_consistency_after_add(
    store: InMemoryChannelStateStore,
) -> None:
    """After add_member, both indices reflect the membership."""
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
    """After remove_member, both indices are updated consistently."""
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
    """After remove_user_from_all, both indices are consistent."""
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
    """get_members returns a copy; mutating it does not affect the store."""
    await store.add_member("#osu", 1)

    members = await store.get_members("#osu")
    members.add(999)

    assert await store.get_members("#osu") == {1}


async def test_get_user_channels_returns_copy(
    store: InMemoryChannelStateStore,
) -> None:
    """get_user_channels returns a copy; mutating it does not affect the store."""
    await store.add_member("#osu", 1)

    channels = await store.get_user_channels(1)
    channels.add("#fake")

    assert await store.get_user_channels(1) == {"#osu"}
