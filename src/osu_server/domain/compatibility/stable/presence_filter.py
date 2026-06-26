"""Stable client presence filter enum values."""

from enum import IntEnum


class StablePresenceFilter(IntEnum):
    """Stable client の PresenceFilter wire 値を表す。"""

    NoPlayers = 0
    All = 1
    Friends = 2


__all__ = ["StablePresenceFilter"]
