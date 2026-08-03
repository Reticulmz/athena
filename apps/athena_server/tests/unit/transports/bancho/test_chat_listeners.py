"""ChatListenersのdisconnect時channel cleanup contractを検証する."""

from __future__ import annotations

import pytest

from osu_server.domain.events.users import UserDisconnected
from osu_server.transports.stable.bancho.listeners.chat import ChatListeners

# ── Stubs ────────────────────────────────────────────────────────────────


class StubChannelStateStore:
    """channel membership削除を記録するChannelStateStore stubを提供する.

    Attributes:
        removed_from (set[str]): 削除結果として返すchannel名の集合.
        removed_user_ids (list[int]): remove_user_from_allへ渡されたuser IDの順序.
    """

    removed_from: set[str]
    removed_user_ids: list[int]

    def __init__(self, removed_from: set[str] | None = None) -> None:
        """削除結果を固定できるchannel state stubを初期化する.

        Args:
            removed_from (set[str] | None): 削除済みchannelとして返す名前の集合.
                Noneなら既定の2 channelを使う.
        """
        self.removed_from = removed_from or {"#osu", "#test"}
        self.removed_user_ids = []

    async def remove_user_from_all(self, user_id: int) -> set[str]:
        """指定userの全channel削除を記録して設定済み結果を返す.

        Args:
            user_id (int): membershipから除去するuserのID.

        Returns:
            set[str]: 削除済みchannel名の設定済み集合.
        """
        self.removed_user_ids.append(user_id)
        return self.removed_from


# ── Fixtures ─────────────────────────────────────────────────────────────


@pytest.fixture
def channel_state() -> StubChannelStateStore:
    """Disconnect cleanup呼び出しを検証するchannel state stubを提供する.

    Returns:
        StubChannelStateStore: 既定channelを返し, 削除対象user IDを記録するstub.
    """
    return StubChannelStateStore()


@pytest.fixture
def listeners(
    channel_state: StubChannelStateStore,
) -> ChatListeners:
    """Channel state stubを注入したChatListenersを提供する.

    Args:
        channel_state (StubChannelStateStore): cleanup結果と呼び出しを記録するfixture.

    Returns:
        ChatListeners: disconnect eventをchannel cleanupへ適応するlistener.
    """
    return ChatListeners(
        channel_state=channel_state,  # pyright: ignore[reportArgumentType]
    )


# ── on_user_disconnected ────────────────────────────────────────────────


class TestOnUserDisconnected:
    """disconnect eventのchannel membership cleanupを検証する."""

    async def test_removes_user_from_all_channels(
        self,
        listeners: ChatListeners,
        channel_state: StubChannelStateStore,
    ) -> None:
        """UserDisconnectedが対象userを全channelから削除する契約を検証する.

        Args:
            listeners (ChatListeners): disconnect eventを処理するlistener fixture.
            channel_state (StubChannelStateStore): 削除対象を記録するchannel state fixture.

        Returns:
            None: cleanup対象user IDを検証して完了し, 呼び出し側へ値を返さない.
        """
        event = UserDisconnected(user_id=42)

        await listeners.on_user_disconnected(event)

        assert channel_state.removed_user_ids == [42]
