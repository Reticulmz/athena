"""Stable client presence filter の compatibility enum を定義する module."""

from enum import IntEnum


class StablePresenceFilter(IntEnum):
    """Stable client の PresenceFilter wire 値を表す enum.

    Attributes:
        NoPlayers (StablePresenceFilter): player presence を受け取らない filter の wire 値0.
        All (StablePresenceFilter): 全 player presence を受け取る filter の wire 値1.
        Friends (StablePresenceFilter): friend の presence だけを受け取る filter の wire 値2.
    """

    NoPlayers = 0
    All = 1
    Friends = 2


__all__ = ["StablePresenceFilter"]
