"""Protocol exception hierarchy for bancho binary protocol.

Design: Error Handling section
- PacketError: base exception for all protocol errors
- PacketReadError (Req 4.4, 4.5): raised on insufficient header/payload data
- DuplicateHandlerError (Req 5.5): raised on duplicate handler registration
"""


class PacketError(Exception):
    """パケットプロトコルの基底例外"""


class PacketReadError(PacketError):
    """パケット読み取り時のエラー (ヘッダ/ペイロード不足)"""


class DuplicateHandlerError(PacketError):
    """同一 ClientPacketID への重複ハンドラ登録"""
