"""User domain events."""

from __future__ import annotations

from dataclasses import dataclass

from osu_server.domain.events import Event


@dataclass(frozen=True, slots=True)
class UserConnected(Event):
    """ユーザーがサーバーへ接続したことを表すドメインイベント。"""

    user_id: int


@dataclass(frozen=True, slots=True)
class UserDisconnected(Event):
    """ユーザーがサーバーから切断したことを表すドメインイベント。"""

    user_id: int
