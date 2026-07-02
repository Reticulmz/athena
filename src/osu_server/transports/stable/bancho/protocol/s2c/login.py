"""S2C login packet builders.

Each builder function returns a complete packet (7-byte header + payload)
using :func:`write_packet`.

Design ref: S2C Login Packets component in bancho-protocol design.md
Requirements: 6.1-6.12
"""

from typing import Annotated

from caterpillar.byteorder import LittleEndian
from caterpillar.context import this
from caterpillar.fields import float32, int32, int64, uint8, uint16
from caterpillar.model import pack
from caterpillar.model import struct as cpstruct

from osu_server.transports.stable.bancho.protocol.enums import ServerPacketID
from osu_server.transports.stable.bancho.protocol.types import (
    BanchoStringT,
    Channel,
    StatusUpdate,
)
from osu_server.transports.stable.bancho.protocol.writer import write_packet

# ── Task 4.1: Scalar payload builders ───────────────────────────────


@cpstruct(order=LittleEndian)
class LoginReplyPayload:
    """LOGIN_REPLY payload.

    挙動:
        login 成功時の user id または失敗時の負の error code を保持する.
    引数:
        user_id: stable client に返す signed 32-bit の login result.
    戻り値:
        Caterpillar pack 時に sInt 1 field の byte 列へ encode される.
    例外:
        user_id が int32 範囲外の場合は Caterpillar の pack error を送出する.
    制約:
        packet header は含めず, payload 本体だけを表す.
    """

    user_id: Annotated[int, int32]


@cpstruct(order=LittleEndian)
class ProtocolVersionPayload:
    """PROTOCOL_VERSION payload.

    挙動:
        stable bancho protocol version を signed 32-bit 値として保持する.
    引数:
        version: stable client に通知する protocol version.
    戻り値:
        Caterpillar pack 時に sInt 1 field の byte 列へ encode される.
    例外:
        version が int32 範囲外の場合は Caterpillar の pack error を送出する.
    制約:
        packet header は含めず, payload 本体だけを表す.
    """

    version: Annotated[int, int32]


@cpstruct(order=LittleEndian)
class LoginPermissionsPayload:
    """LOGIN_PERMISSIONS payload.

    挙動:
        stable client permission bitmask を signed 32-bit 値として保持する.
    引数:
        permissions: stable client に返す permission bitmask.
    戻り値:
        Caterpillar pack 時に sInt 1 field の byte 列へ encode される.
    例外:
        permissions が int32 範囲外の場合は Caterpillar の pack error を送出する.
    制約:
        packet header は含めず, payload 本体だけを表す.
    """

    permissions: Annotated[int, int32]


@cpstruct(order=LittleEndian)
class NotificationPayload:
    """ANNOUNCE payload.

    挙動:
        stable client に表示する notification text を BanchoString として保持する.
    引数:
        message: 表示する notification text.
    戻り値:
        Caterpillar pack 時に BanchoString の byte 列へ encode される.
    例外:
        message が encode 不能な場合は Caterpillar の pack error を送出する.
    制約:
        packet header は含めず, payload 本体だけを表す.
    """

    message: BanchoStringT


@cpstruct(order=LittleEndian)
class SilenceInfoPayload:
    """SILENCE_INFO payload.

    挙動:
        残り silence 秒数を signed 32-bit 値として保持する.
    引数:
        remaining_seconds: stable client に通知する残り silence 秒数.
    戻り値:
        Caterpillar pack 時に sInt 1 field の byte 列へ encode される.
    例外:
        remaining_seconds が int32 範囲外の場合は Caterpillar の pack error を送出する.
    制約:
        packet header は含めず, payload 本体だけを表す.
    """

    remaining_seconds: Annotated[int, int32]


@cpstruct(order=LittleEndian)
class FriendsListPayload:
    """FRIENDS_LIST payload.

    挙動:
        friend user id の一覧を uint16 count + int32 array として保持する.
    引数:
        count: friend_ids の要素数.
        friend_ids: stable user id の一覧.
    戻り値:
        Caterpillar pack 時に IntList と同じ byte 列へ encode される.
    例外:
        count と friend_ids の長さが一致しない場合や値が wire type の範囲外の場合は
        Caterpillar の pack error を送出する.
    制約:
        count は builder 側で len(friend_ids) から設定する.
    """

    count: Annotated[int, uint16]
    friend_ids: Annotated[list[int], int32[this.count]]


@cpstruct(order=LittleEndian)
class UserPresenceBundlePayload:
    """USER_PRESENCE_BUNDLE payload.

    挙動:
        online user id の一覧を uint16 count + int32 array として保持する.
    引数:
        count: user_ids の要素数.
        user_ids: online stable user id の一覧.
    戻り値:
        Caterpillar pack 時に IntList と同じ byte 列へ encode される.
    例外:
        count と user_ids の長さが一致しない場合や値が wire type の範囲外の場合は
        Caterpillar の pack error を送出する.
    制約:
        count は builder 側で len(user_ids) から設定する.
    """

    count: Annotated[int, uint16]
    user_ids: Annotated[list[int], int32[this.count]]


def login_reply(user_id: int) -> bytes:
    """LOGIN_REPLY packet を構築する.

    引数:
        user_id: 成功時の stable user id, または失敗時の負の error code.
    戻り値:
        7 byte header と payload を含む complete packet.
    例外:
        user_id が int32 範囲外の場合は Caterpillar の pack error を送出する.
    制約:
        外部シグネチャと sInt payload format は互換性維持のため変更しない.
    """
    payload: bytes = pack(LoginReplyPayload(user_id=user_id))
    return write_packet(ServerPacketID.LOGIN_REPLY, payload)


def protocol_version(version: int) -> bytes:
    """PROTOCOL_VERSION packet を構築する.

    引数:
        version: stable bancho protocol version.
    戻り値:
        7 byte header と payload を含む complete packet.
    例外:
        version が int32 範囲外の場合は Caterpillar の pack error を送出する.
    制約:
        外部シグネチャと sInt payload format は互換性維持のため変更しない.
    """
    payload: bytes = pack(ProtocolVersionPayload(version=version))
    return write_packet(ServerPacketID.PROTOCOL_VERSION, payload)


def login_permissions(permissions: int) -> bytes:
    """LOGIN_PERMISSIONS packet を構築する.

    引数:
        permissions: stable client permission bitmask.
    戻り値:
        7 byte header と payload を含む complete packet.
    例外:
        permissions が int32 範囲外の場合は Caterpillar の pack error を送出する.
    制約:
        外部シグネチャと sInt payload format は互換性維持のため変更しない.
    """
    payload: bytes = pack(LoginPermissionsPayload(permissions=permissions))
    return write_packet(ServerPacketID.LOGIN_PERMISSIONS, payload)


def notification(message: str) -> bytes:
    """ANNOUNCE packet を構築する.

    引数:
        message: stable client に表示する notification text.
    戻り値:
        7 byte header と payload を含む complete packet.
    例外:
        message が encode 不能な場合は Caterpillar の pack error を送出する.
    制約:
        外部シグネチャと BanchoString payload format は互換性維持のため変更しない.
    """
    payload: bytes = pack(NotificationPayload(message=message))
    return write_packet(ServerPacketID.ANNOUNCE, payload)


def channel_info_complete() -> bytes:
    """Req 6.9: ChannelInfoComplete — empty payload."""
    return write_packet(ServerPacketID.CHANNEL_INFO_COMPLETE)


def silence_info(remaining_seconds: int) -> bytes:
    """SILENCE_INFO packet を構築する.

    引数:
        remaining_seconds: stable client に通知する残り silence 秒数.
    戻り値:
        7 byte header と payload を含む complete packet.
    例外:
        remaining_seconds が int32 範囲外の場合は Caterpillar の pack error を送出する.
    制約:
        外部シグネチャと sInt payload format は互換性維持のため変更しない.
    """
    payload: bytes = pack(SilenceInfoPayload(remaining_seconds=remaining_seconds))
    return write_packet(ServerPacketID.SILENCE_INFO, payload)


def friends_list(friend_ids: list[int]) -> bytes:
    """FRIENDS_LIST packet を構築する.

    引数:
        friend_ids: stable client に通知する friend user id 一覧.
    戻り値:
        7 byte header と payload を含む complete packet.
    例外:
        user id が int32 範囲外, または件数が uint16 範囲外の場合は Caterpillar の
        pack error を送出する.
    制約:
        外部シグネチャと IntList payload format は互換性維持のため変更しない.
    """
    payload: bytes = pack(FriendsListPayload(count=len(friend_ids), friend_ids=friend_ids))
    return write_packet(ServerPacketID.FRIENDS_LIST, payload)


def user_presence_bundle(user_ids: list[int]) -> bytes:
    """USER_PRESENCE_BUNDLE packet を構築する.

    引数:
        user_ids: stable client に通知する online user id 一覧.
    戻り値:
        7 byte header と payload を含む complete packet.
    例外:
        user id が int32 範囲外, または件数が uint16 範囲外の場合は Caterpillar の
        pack error を送出する.
    制約:
        外部シグネチャと IntList payload format は互換性維持のため変更しない.
    """
    payload: bytes = pack(UserPresenceBundlePayload(count=len(user_ids), user_ids=user_ids))
    return write_packet(ServerPacketID.USER_PRESENCE_BUNDLE, payload)


# ── Task 4.2: Complex payload builders ──────────────────────────────


@cpstruct(order=LittleEndian)
class _UserPresenceData:
    """Wire format for UserPresence payload (Req 6.5)."""

    user_id: Annotated[int, int32]
    username: BanchoStringT
    timezone: Annotated[int, uint8]
    country_id: Annotated[int, uint8]
    permissions_mode: Annotated[int, uint8]  # permissions | (mode << 5)
    longitude: Annotated[float, float32]
    latitude: Annotated[float, float32]
    rank: Annotated[int, int32]


def user_presence(
    *,
    user_id: int,
    username: str,
    timezone: int,
    country_id: int,
    permissions: int,
    mode: int,
    longitude: float,
    latitude: float,
    rank: int,
) -> bytes:
    """Req 6.5: UserPresence."""
    data = _UserPresenceData(
        user_id=user_id,
        username=username,
        timezone=timezone,
        country_id=country_id,
        permissions_mode=permissions | (mode << 5),
        longitude=longitude,
        latitude=latitude,
        rank=rank,
    )
    payload: bytes = pack(data)
    return write_packet(ServerPacketID.USER_PRESENCE, payload)


@cpstruct(order=LittleEndian)
class _UserStatsData:
    """UserStats payload の wire format。"""

    user_id: Annotated[int, int32]
    status_update: StatusUpdate
    ranked_score: Annotated[int, int64]
    accuracy: Annotated[float, float32]
    play_count: Annotated[int, int32]
    total_score: Annotated[int, int64]
    rank: Annotated[int, int32]
    pp: Annotated[int, uint16]


def user_stats(
    *,
    user_id: int,
    status: int,
    status_text: str,
    beatmap_md5: str,
    mods: int,
    play_mode: int,
    beatmap_id: int,
    ranked_score: int,
    accuracy: float,
    play_count: int,
    total_score: int,
    rank: int,
    pp: int,
) -> bytes:
    """UserStats packet を構築する。

    引数:
        user_id: stable client に通知する user id。
        status: StatusUpdate.status の wire 値。
        status_text: Stable status text。
        beatmap_md5: 現在の beatmap md5。未設定時は空文字。
        mods: Stable mods bitmask。
        play_mode: Stable mode wire 値。
        beatmap_id: 現在の beatmap id。未設定時は 0。
        ranked_score: Ranked score。
        accuracy: 0.0-1.0 ratio の f32 値。
        play_count: Play count。
        total_score: Total score。
        rank: Global rank。未設定時は 0。
        pp: Stable wire の uint16 pp 値。65535 を超える値は丸める。

    戻り値:
        7 byte header と payload を含む complete packet。

    例外:
        値が wire type の範囲外の場合は Caterpillar の pack error を送出する。

    制約:
        外部シグネチャは互換性維持のため変更しない。
    """
    data = _UserStatsData(
        user_id=user_id,
        status_update=StatusUpdate(
            status=status,
            status_text=status_text,
            beatmap_md5=beatmap_md5,
            mods=mods,
            play_mode=play_mode,
            beatmap_id=beatmap_id,
        ),
        ranked_score=ranked_score,
        accuracy=accuracy,
        play_count=play_count,
        total_score=total_score,
        rank=rank,
        pp=min(pp, 65535),
    )
    payload: bytes = pack(data)
    return write_packet(ServerPacketID.USER_STATS, payload)


@cpstruct(order=LittleEndian)
class ChannelAvailablePayload:
    """CHANNEL_AVAILABLE payload.

    挙動:
        stable client に公開する channel info を Channel wire type として保持する.
    引数:
        channel: name/topic/user_count を含む Channel.
    戻り値:
        Caterpillar pack 時に Channel と同じ byte 列へ encode される.
    例外:
        field 値が wire type の範囲外の場合は Caterpillar の pack error を送出する.
    制約:
        packet header は含めず, payload 本体だけを表す.
    """

    channel: Channel


@cpstruct(order=LittleEndian)
class ChannelAvailableAutojoinPayload:
    """CHANNEL_AVAILABLE_AUTOJOIN payload.

    挙動:
        autojoin 対象の channel info を Channel wire type として保持する.
    引数:
        channel: name/topic/user_count を含む Channel.
    戻り値:
        Caterpillar pack 時に Channel と同じ byte 列へ encode される.
    例外:
        field 値が wire type の範囲外の場合は Caterpillar の pack error を送出する.
    制約:
        CHANNEL_AVAILABLE と同じ Channel payload format を使う.
    """

    channel: Channel


def channel_available(*, name: str, topic: str, user_count: int) -> bytes:
    """CHANNEL_AVAILABLE packet を構築する.

    引数:
        name: stable channel name.
        topic: stable client に表示する channel topic.
        user_count: channel 内の user count.
    戻り値:
        7 byte header と payload を含む complete packet.
    例外:
        field 値が wire type の範囲外の場合は Caterpillar の pack error を送出する.
    制約:
        外部シグネチャと Channel payload format は互換性維持のため変更しない.
    """
    ch = Channel(name=name, topic=topic, user_count=user_count)
    payload: bytes = pack(ChannelAvailablePayload(channel=ch))
    return write_packet(ServerPacketID.CHANNEL_AVAILABLE, payload)


def channel_available_autojoin(*, name: str, topic: str, user_count: int) -> bytes:
    """CHANNEL_AVAILABLE_AUTOJOIN packet を構築する.

    引数:
        name: stable channel name.
        topic: stable client に表示する channel topic.
        user_count: channel 内の user count.
    戻り値:
        7 byte header と payload を含む complete packet.
    例外:
        field 値が wire type の範囲外の場合は Caterpillar の pack error を送出する.
    制約:
        CHANNEL_AVAILABLE と同じ Channel payload format を維持する.
    """
    ch = Channel(name=name, topic=topic, user_count=user_count)
    payload: bytes = pack(ChannelAvailableAutojoinPayload(channel=ch))
    return write_packet(ServerPacketID.CHANNEL_AVAILABLE_AUTOJOIN, payload)
