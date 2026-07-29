"""Bancho protocol subsystemの例外型を定義する.

wire-level I/O errorとdispatcherのhandler登録errorを共通のPacketError hierarchyへまとめる.
"""


class PacketError(Exception):
    """Bancho packet protocol例外の基底classを表す."""


class PacketReadError(PacketError):
    """packet headerまたはpayloadを読み切れないことを表す."""


class DuplicateHandlerError(PacketError):
    """同一ClientPacketIDへのhandler重複登録を表す."""
