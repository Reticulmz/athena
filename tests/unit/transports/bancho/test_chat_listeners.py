"""Tests for ChatListeners local disconnect cleanup."""

from __future__ import annotations

import pytest

from osu_server.domain.events.users import UserDisconnected
from osu_server.transports.stable.bancho.listeners.chat import ChatListeners

# ── Stubs ────────────────────────────────────────────────────────────────


class StubChannelStateStore:
    """ChannelStateStore スタブ。"""

    removed_from: set[str]
    removed_user_ids: list[int]

    def __init__(self, removed_from: set[str] | None = None) -> None:
        self.removed_from = removed_from or {"#osu", "#test"}
        self.removed_user_ids = []

    async def remove_user_from_all(self, user_id: int) -> set[str]:
        self.removed_user_ids.append(user_id)
        return self.removed_from


# ── Fixtures ─────────────────────────────────────────────────────────────


@pytest.fixture
def channel_state() -> StubChannelStateStore:
    return StubChannelStateStore()


@pytest.fixture
def listeners(
    channel_state: StubChannelStateStore,
) -> ChatListeners:
    return ChatListeners(
        channel_state=channel_state,  # pyright: ignore[reportArgumentType]
    )


# ── on_user_disconnected ────────────────────────────────────────────────


class TestOnUserDisconnected:
    async def test_removes_user_from_all_channels(
        self,
        listeners: ChatListeners,
        channel_state: StubChannelStateStore,
    ) -> None:
        event = UserDisconnected(user_id=42)

        await listeners.on_user_disconnected(event)

        assert channel_state.removed_user_ids == [42]
