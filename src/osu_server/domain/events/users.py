"""User contextが発行する接続状態domain eventを定義するmodule."""

from __future__ import annotations

from dataclasses import dataclass

from osu_server.domain.events import Event


@dataclass(frozen=True, slots=True)
class UserConnected(Event):
    """Userがserverへ接続したことを表すdomain event.

    Attributes:
        user_id (int): 接続したuserのID.
    """

    user_id: int


@dataclass(frozen=True, slots=True)
class UserDisconnected(Event):
    """Userがserverから切断したことを表すdomain event.

    Attributes:
        user_id (int): 切断したuserのID.
    """

    user_id: int
