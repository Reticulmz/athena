"""Wire types for the bancho binary protocol.

BanchoString — osu! proprietary string encoding (Req 3.1, 3.6)
Message — chat message with sender, content, target, sender_id (Req 3.2, 3.6)
IntList — uint16 count + int32[] dynamic array (Req 3.3, 3.6)
Channel — channel name, topic, user_count (Req 3.4, 3.6)
StatusUpdate — player status with mods, mode, beatmap info (Req 3.5, 3.6)
"""

from io import BytesIO
from typing import Annotated, Final, cast, override

from caterpillar import context as caterpillar_context
from caterpillar.byteorder import LittleEndian
from caterpillar.context import this
from caterpillar.exception import DynamicSizeError
from caterpillar.fields import FieldStruct, int16, int32, uint8, uint16
from caterpillar.model import struct

from osu_server.transports.stable.bancho.protocol.errors import PacketReadError

_PRESENCE_EMPTY: int = 0x00
_PRESENCE_STRING: int = 0x0B
_ULEB128_VALUE_MASK: int = 0x7F
_CTX_STREAM_KEY: Final[str] = cast("str", caterpillar_context.CTX_STREAM)


def _read_byte(stream: BytesIO) -> int:
    """Read a single byte from *stream*, raising on truncation."""
    b = stream.read(1)
    if not b:
        raise PacketReadError("Unexpected end of stream")
    return b[0]


def _stream_from_context(context: object) -> BytesIO:
    context_map = cast("dict[str, object]", context)
    return cast("BytesIO", context_map[_CTX_STREAM_KEY])


class _BanchoString(FieldStruct):  # type: ignore[type-arg]
    """osu! BanchoString: ``0x00`` (empty) or ``0x0b`` + ULEB128 length + UTF-8 data.

    Singleton instance exported as :data:`BanchoString` for use as a
    Caterpillar field type annotation (same pattern as ``uint8``, ``vint``).
    """

    __slots__: tuple[str, ...] = ()

    def __type__(self) -> type:
        return str

    def __size__(self, context: object) -> int:
        raise DynamicSizeError("BanchoString has dynamic size")

    @override
    def pack_single(self, obj: str, context: object) -> None:
        stream = _stream_from_context(context)

        if not obj:
            _ = stream.write(b"\x00")
            return

        data = obj.encode("utf-8")
        _ = stream.write(bytes([_PRESENCE_STRING]))
        _write_uleb128(stream, len(data))
        _ = stream.write(data)

    @override
    def unpack_single(self, context: object) -> str:
        stream = _stream_from_context(context)
        presence = _read_byte(stream)

        if presence == _PRESENCE_EMPTY:
            return ""
        if presence != _PRESENCE_STRING:
            msg = f"Invalid BanchoString presence byte: 0x{presence:02x}"
            raise PacketReadError(msg)

        length = _read_uleb128(stream)
        data: bytes = stream.read(length)
        return data.decode("utf-8")


def _write_uleb128(stream: BytesIO, value: int) -> None:
    """Encode *value* as ULEB128 and write to *stream*."""
    while value > _ULEB128_VALUE_MASK:
        _ = stream.write(bytes([value & _ULEB128_VALUE_MASK | 0x80]))
        value >>= 7
    _ = stream.write(bytes([value]))


def _read_uleb128(stream: BytesIO) -> int:
    """Read a ULEB128-encoded integer from *stream*."""
    result = 0
    shift = 0
    while True:
        byte = _read_byte(stream)
        result |= (byte & _ULEB128_VALUE_MASK) << shift
        if not (byte & 0x80):
            break
        shift += 7
    return result


BanchoString: _BanchoString = _BanchoString()
BanchoStringT = Annotated[str, BanchoString]
"""Singleton field type for use in Caterpillar struct annotations.

Usage::

    @struct(order=LittleEndian)
    class SomePacket:
        name: BanchoStringT
"""


# ── Wire Types (Req 3.2-3.5, 3.6) ───────────────────────────────────


@struct(order=LittleEndian)
class Message:
    """Chat message: sender, content, target (BanchoString) + sender_id (signed 32-bit).

    Req 3.2: Message type definition.
    """

    sender: BanchoStringT
    content: BanchoStringT
    target: BanchoStringT
    sender_id: Annotated[int, int32]


@struct(order=LittleEndian)
class IntList:
    """Length-prefixed list of signed 32-bit integers.

    Req 3.3: uint16 count + int32[] dynamic array.
    """

    count: Annotated[int, uint16]
    values: Annotated[list[int], int32[this.count]]


@struct(order=LittleEndian)
class Channel:
    """Channel info: name, topic (BanchoString) + user_count (signed 16-bit).

    Req 3.4: Channel type definition.
    """

    name: BanchoStringT
    topic: BanchoStringT
    user_count: Annotated[int, int16]


@struct(order=LittleEndian)
class StatusUpdate:
    """Player status update.

    Req 3.5: status (uint8), status_text/beatmap_md5 (BanchoString),
    mods (int32), play_mode (uint8), beatmap_id (int32).
    """

    status: Annotated[int, uint8]
    status_text: BanchoStringT
    beatmap_md5: BanchoStringT
    mods: Annotated[int, int32]
    play_mode: Annotated[int, uint8]
    beatmap_id: Annotated[int, int32]
