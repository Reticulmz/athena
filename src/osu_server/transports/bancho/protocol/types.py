# pyright: reportAny=false, reportUnknownVariableType=false
# pyright: reportUnknownMemberType=false, reportUnknownArgumentType=false
"""Wire types for the bancho binary protocol.

BanchoString — osu! proprietary string encoding:
  - Presence byte ``0x00`` → empty string
  - Presence byte ``0x0b`` + ULEB128 byte-length + UTF-8 data → non-empty string

Design ref: BanchoString component in bancho-protocol design.md
Requirements: 3.1, 3.6
"""

from __future__ import annotations

from typing import TYPE_CHECKING, cast, override

if TYPE_CHECKING:
    from io import BytesIO

from caterpillar.context import CTX_STREAM
from caterpillar.exception import DynamicSizeError
from caterpillar.fields import FieldStruct

_PRESENCE_EMPTY: int = 0x00
_PRESENCE_STRING: int = 0x0B
_ULEB128_CONTINUATION_MASK: int = 0x7F


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
        stream = cast("BytesIO", context[CTX_STREAM])  # pyright: ignore[reportIndexIssue]

        if not obj:
            _ = stream.write(b"\x00")
            return

        data = obj.encode("utf-8")
        _ = stream.write(bytes([_PRESENCE_STRING]))
        _write_uleb128(stream, len(data))
        _ = stream.write(data)

    @override
    def unpack_single(self, context: object) -> str:
        stream = cast("BytesIO", context[CTX_STREAM])  # pyright: ignore[reportIndexIssue]
        presence: int = stream.read(1)[0]

        if presence == _PRESENCE_EMPTY:
            return ""

        length = _read_uleb128(stream)
        data: bytes = stream.read(length)
        return data.decode("utf-8")


def _write_uleb128(stream: BytesIO, value: int) -> None:
    """Encode *value* as ULEB128 and write to *stream*."""
    while value > _ULEB128_CONTINUATION_MASK:
        _ = stream.write(bytes([value & _ULEB128_CONTINUATION_MASK | 0x80]))
        value >>= 7
    _ = stream.write(bytes([value]))


def _read_uleb128(stream: BytesIO) -> int:
    """Read a ULEB128-encoded integer from *stream*."""
    result = 0
    shift = 0
    while True:
        byte: int = stream.read(1)[0]
        result |= (byte & _ULEB128_CONTINUATION_MASK) << shift
        if not (byte & 0x80):
            break
        shift += 7
    return result


BanchoString: _BanchoString = _BanchoString()
"""Singleton field type for use in Caterpillar struct annotations.

Usage::

    @struct(order=LittleEndian)
    class Message:
        sender: BanchoString   # pyright: ignore[reportInvalidTypeForm]
        content: BanchoString  # pyright: ignore[reportInvalidTypeForm]
"""
