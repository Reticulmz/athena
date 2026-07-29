"""Bancho binary protocolで使うCaterpillar wire typeを定義する."""

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
    """streamから1 byteを読み取り, 欠損時はpacket errorに変換する.

    Args:
        stream (BytesIO): BanchoStringのwire bytesを読むstream.

    Returns:
        int: 読み取った1 byteの0から255までの値.

    Raises:
        PacketReadError: streamが終端に達して1 byteを読めない場合.
    """
    b = stream.read(1)
    if not b:
        raise PacketReadError("Unexpected end of stream")
    return b[0]


def _stream_from_context(context: object) -> BytesIO:
    """Caterpillar contextから現在のbyte streamを取得する.

    Args:
        context (object): Caterpillarがfield pack/unpack時に渡すcontext map.

    Returns:
        BytesIO: BanchoString fieldが読み書きするstream.
    """
    context_map = cast("dict[str, object]", context)
    return cast("BytesIO", context_map[_CTX_STREAM_KEY])


class _BanchoString(FieldStruct):  # type: ignore[type-arg]
    """osu!の可変長BanchoString fieldをCaterpillarへ提供する.

    空文字列は0x00, 非空文字列は0x0b, ULEB128 byte長, UTF-8 bytesの順に符号化する.

    Attributes:
        __slots__ (tuple[str, ...]): field instanceが追加のinstance attributeを持たないことを
            示す空tuple.
    """

    __slots__: tuple[str, ...] = ()

    def __type__(self) -> type:
        """CaterpillarへfieldのPython runtime typeを返す.

        Returns:
            type: BanchoString fieldがpackおよびunpackするstr型.
        """
        return str

    def __size__(self, context: object) -> int:
        """固定field sizeを持たないことをCaterpillarへ通知する.

        Args:
            context (object): Caterpillarが渡すfield context. size計算には使用しない.

        Raises:
            DynamicSizeError: BanchoStringのbyte長が値によって変わるため.
        """
        raise DynamicSizeError("BanchoString has dynamic size")

    @override
    def pack_single(self, obj: str, context: object) -> None:
        """1つの文字列をBanchoString wire bytesとしてstreamへ書き込む.

        Args:
            obj (str): UTF-8へ符号化する文字列. 空文字列は0x00を使う.
            context (object): 書き込み先streamを持つCaterpillar context.

        Returns:
            None: wire bytesを書き込み, 値を返さず完了する.
        """
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
        """streamから1つのBanchoStringを復元する.

        Args:
            context (object): 読み取り元streamを持つCaterpillar context.

        Returns:
            str: 空文字列またはUTF-8 decode済みのwire文字列.

        Raises:
            PacketReadError: presence byteまたはULEB128の終端byteを読めないか不正な場合.
            UnicodeDecodeError: 非空文字列のpayloadがUTF-8としてdecodeできない場合.
        """
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
    """非負整数をULEB128としてstreamへ書き込む.

    Args:
        stream (BytesIO): ULEB128 bytesの書き込み先.
        value (int): 符号化する整数. 呼び出し元は非負値を渡す.

    Returns:
        None: ULEB128 bytesを書き込み, 値を返さず完了する.
    """
    while value > _ULEB128_VALUE_MASK:
        _ = stream.write(bytes([value & _ULEB128_VALUE_MASK | 0x80]))
        value >>= 7
    _ = stream.write(bytes([value]))


def _read_uleb128(stream: BytesIO) -> int:
    """streamからULEB128符号化された整数を読み取る.

    Args:
        stream (BytesIO): ULEB128 bytesの読み取り元.

    Returns:
        int: 継続bitが立っていないbyteまでを復元した非負整数.

    Raises:
        PacketReadError: 終端byteの前にstreamが尽きた場合.
    """
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
    """Bancho chat messageのwire field群を表す.

    Attributes:
        sender (str): BanchoStringで保持する送信者名.
        content (str): BanchoStringで保持する本文.
        target (str): BanchoStringで保持するchannelまたは宛先名.
        sender_id (int): signed int32で保持する送信者user ID.
    """

    sender: BanchoStringT
    content: BanchoStringT
    target: BanchoStringT
    sender_id: Annotated[int, int32]


@struct(order=LittleEndian)
class IntList:
    """uint16 countで前置するsigned int32 listを表す.

    Attributes:
        count (int): valuesの要素数を表すuint16 wire値.
        values (list[int]): count件のsigned int32値をwire順に保持する一覧.
    """

    count: Annotated[int, uint16]
    values: Annotated[list[int], int32[this.count]]


@struct(order=LittleEndian)
class Channel:
    """stable channel情報のwire field群を表す.

    Attributes:
        name (str): BanchoStringで保持するchannel名.
        topic (str): BanchoStringで保持するchannel topic.
        user_count (int): signed int16で保持する参加user数.
    """

    name: BanchoStringT
    topic: BanchoStringT
    user_count: Annotated[int, int16]


@struct(order=LittleEndian)
class StatusUpdate:
    """player status updateのwire field群を表す.

    Attributes:
        status (int): uint8のonline status wire値.
        status_text (str): BanchoStringで保持するstatus text.
        beatmap_md5 (str): BanchoStringで保持するcurrent beatmap MD5.
        mods (int): signed int32のstable mod bitmask.
        play_mode (int): uint8のstable game mode wire値.
        beatmap_id (int): signed int32のcurrent beatmap ID.
    """

    status: Annotated[int, uint8]
    status_text: BanchoStringT
    beatmap_md5: BanchoStringT
    mods: Annotated[int, int32]
    play_mode: Annotated[int, uint8]
    beatmap_id: Annotated[int, int32]
