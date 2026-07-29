"""stable clientのlogin後に送るS2C packetを構築する."""

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
    """LOGIN_REPLYのsigned int32 result payloadを表す.

    Attributes:
        user_id (int): 成功時はstable user ID, 失敗時は負のerror code.
    """

    user_id: Annotated[int, int32]


@cpstruct(order=LittleEndian)
class ProtocolVersionPayload:
    """PROTOCOL_VERSIONのsigned int32 payloadを表す.

    Attributes:
        version (int): stable clientへ通知するprotocol version.
    """

    version: Annotated[int, int32]


@cpstruct(order=LittleEndian)
class LoginPermissionsPayload:
    """LOGIN_PERMISSIONSのsigned int32 payloadを表す.

    Attributes:
        permissions (int): stable clientへ返すpermission bitmask.
    """

    permissions: Annotated[int, int32]


@cpstruct(order=LittleEndian)
class NotificationPayload:
    """ANNOUNCEのBanchoString message payloadを表す.

    Attributes:
        message (str): stable clientに表示するnotification text.
    """

    message: BanchoStringT


@cpstruct(order=LittleEndian)
class SilenceInfoPayload:
    """SILENCE_INFOの残り秒数payloadを表す.

    Attributes:
        remaining_seconds (int): signed int32で送る残りsilence秒数.
    """

    remaining_seconds: Annotated[int, int32]


@cpstruct(order=LittleEndian)
class FriendsListPayload:
    """FRIENDS_LISTのcount-prefixed user ID listを表す.

    Attributes:
        count (int): friend_idsの要素数を表すuint16 wire値.
        friend_ids (list[int]): count件のsigned int32 stable user ID.
    """

    count: Annotated[int, uint16]
    friend_ids: Annotated[list[int], int32[this.count]]


@cpstruct(order=LittleEndian)
class UserPresenceBundlePayload:
    """USER_PRESENCE_BUNDLEのcount-prefixed online user ID listを表す.

    Attributes:
        count (int): user_idsの要素数を表すuint16 wire値.
        user_ids (list[int]): count件のsigned int32 online stable user ID.
    """

    count: Annotated[int, uint16]
    user_ids: Annotated[list[int], int32[this.count]]


def login_reply(user_id: int) -> bytes:
    """LOGIN_REPLY packetを構築する.

    Args:
        user_id (int): 成功時のstable user IDまたは失敗時の負のerror code.

    Returns:
        bytes: 7 byte headerとsigned int32 payloadを含むpacket.
    """
    payload: bytes = pack(LoginReplyPayload(user_id=user_id))
    return write_packet(ServerPacketID.LOGIN_REPLY, payload)


def protocol_version(version: int) -> bytes:
    """PROTOCOL_VERSION packetを構築する.

    Args:
        version (int): stable clientへ通知するprotocol version.

    Returns:
        bytes: 7 byte headerとsigned int32 payloadを含むpacket.
    """
    payload: bytes = pack(ProtocolVersionPayload(version=version))
    return write_packet(ServerPacketID.PROTOCOL_VERSION, payload)


def login_permissions(permissions: int) -> bytes:
    """LOGIN_PERMISSIONS packetを構築する.

    Args:
        permissions (int): stable clientへ返すpermission bitmask.

    Returns:
        bytes: 7 byte headerとsigned int32 payloadを含むpacket.
    """
    payload: bytes = pack(LoginPermissionsPayload(permissions=permissions))
    return write_packet(ServerPacketID.LOGIN_PERMISSIONS, payload)


def notification(message: str) -> bytes:
    """ANNOUNCE packetを構築する.

    Args:
        message (str): stable clientに表示するnotification text.

    Returns:
        bytes: 7 byte headerとBanchoString payloadを含むpacket.
    """
    payload: bytes = pack(NotificationPayload(message=message))
    return write_packet(ServerPacketID.ANNOUNCE, payload)


def channel_info_complete() -> bytes:
    """空payloadのCHANNEL_INFO_COMPLETE packetを構築する.

    Returns:
        bytes: 7 byte headerだけを含むcomplete packet.
    """
    return write_packet(ServerPacketID.CHANNEL_INFO_COMPLETE)


def silence_info(remaining_seconds: int) -> bytes:
    """SILENCE_INFO packetを構築する.

    Args:
        remaining_seconds (int): stable clientに通知する残りsilence秒数.

    Returns:
        bytes: 7 byte headerとsigned int32 payloadを含むpacket.
    """
    payload: bytes = pack(SilenceInfoPayload(remaining_seconds=remaining_seconds))
    return write_packet(ServerPacketID.SILENCE_INFO, payload)


def friends_list(friend_ids: list[int]) -> bytes:
    """FRIENDS_LIST packetを構築する.

    Args:
        friend_ids (list[int]): stable clientに通知するfriend user ID一覧.

    Returns:
        bytes: 7 byte headerとcount-prefixed user ID payloadを含むpacket.
    """
    payload: bytes = pack(FriendsListPayload(count=len(friend_ids), friend_ids=friend_ids))
    return write_packet(ServerPacketID.FRIENDS_LIST, payload)


def user_presence_bundle(user_ids: list[int]) -> bytes:
    """USER_PRESENCE_BUNDLE packetを構築する.

    Args:
        user_ids (list[int]): stable clientに通知するonline user ID一覧.

    Returns:
        bytes: 7 byte headerとcount-prefixed user ID payloadを含むpacket.
    """
    payload: bytes = pack(UserPresenceBundlePayload(count=len(user_ids), user_ids=user_ids))
    return write_packet(ServerPacketID.USER_PRESENCE_BUNDLE, payload)


# ── Task 4.2: Complex payload builders ──────────────────────────────


@cpstruct(order=LittleEndian)
class _UserPresenceData:
    """USER_PRESENCE payloadのwire field群を表す.

    Attributes:
        user_id (int): signed int32のstable user ID.
        username (str): BanchoStringのusername.
        timezone (int): uint8のtimezone offset値.
        country_id (int): uint8のcountry ID.
        permissions_mode (int): permission bitとmodeを合成したuint8値.
        longitude (float): float32のlongitude.
        latitude (float): float32のlatitude.
        rank (int): signed int32のglobal rank.
    """

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
    """USER_PRESENCE packetを構築する.

    Args:
        user_id (int): stable user ID.
        username (str): stable clientへ表示するusername.
        timezone (int): uint8 timezone offset値.
        country_id (int): uint8 country ID.
        permissions (int): permissions_modeの下位5 bitに入れるpermission値.
        mode (int): permissions_modeへ左5 bit移動して合成するmode値.
        longitude (float): float32として送るlongitude.
        latitude (float): float32として送るlatitude.
        rank (int): signed int32として送るglobal rank.

    Returns:
        bytes: 7 byte headerとUSER_PRESENCE payloadを含むpacket.
    """
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
    """USER_STATS payloadのwire field群を表す.

    Attributes:
        user_id (int): signed int32のstable user ID.
        status_update (StatusUpdate): player statusを持つwire field群.
        ranked_score (int): signed int64のranked score.
        accuracy (float): float32のaccuracy ratio.
        play_count (int): signed int32のplay count.
        total_score (int): signed int64のtotal score.
        rank (int): signed int32のglobal rank.
        pp (int): uint16のperformance point値.
    """

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
    """USER_STATS packetを構築する.

    Args:
        user_id (int): stable clientに通知するuser ID.
        status (int): StatusUpdate.statusのwire値.
        status_text (str): stable status text.
        beatmap_md5 (str): current beatmap MD5. 未設定時は空文字列.
        mods (int): stable mods bitmask.
        play_mode (int): stable mode wire値.
        beatmap_id (int): current beatmap ID. 未設定時は0.
        ranked_score (int): ranked score.
        accuracy (float): 0.0から1.0のfloat32 accuracy ratio.
        play_count (int): play count.
        total_score (int): total score.
        rank (int): global rank. 未設定時は0.
        pp (int): uint16として送るperformance point. 65535を超える値は丸める.

    Returns:
        bytes: 7 byte headerとpayloadを含むcomplete packet.

    Notes:
        外部signatureとppの65535上限はstable client互換のため維持する.
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
    """CHANNEL_AVAILABLEのChannel payloadを表す.

    Attributes:
        channel (Channel): stable clientに公開するchannel情報.
    """

    channel: Channel


@cpstruct(order=LittleEndian)
class ChannelAvailableAutojoinPayload:
    """CHANNEL_AVAILABLE_AUTOJOINのChannel payloadを表す.

    Attributes:
        channel (Channel): autojoin対象として公開するchannel情報.
    """

    channel: Channel


def channel_available(*, name: str, topic: str, user_count: int) -> bytes:
    """CHANNEL_AVAILABLE packetを構築する.

    Args:
        name (str): stable channel名.
        topic (str): stable clientに表示するchannel topic.
        user_count (int): channel内user数.

    Returns:
        bytes: 7 byte headerとChannel payloadを含むpacket.
    """
    ch = Channel(name=name, topic=topic, user_count=user_count)
    payload: bytes = pack(ChannelAvailablePayload(channel=ch))
    return write_packet(ServerPacketID.CHANNEL_AVAILABLE, payload)


def channel_available_autojoin(*, name: str, topic: str, user_count: int) -> bytes:
    """CHANNEL_AVAILABLE_AUTOJOIN packetを構築する.

    Args:
        name (str): stable channel名.
        topic (str): stable clientに表示するchannel topic.
        user_count (int): channel内user数.

    Returns:
        bytes: 7 byte headerとChannel payloadを含むpacket.
    """
    ch = Channel(name=name, topic=topic, user_count=user_count)
    payload: bytes = pack(ChannelAvailableAutojoinPayload(channel=ch))
    return write_packet(ServerPacketID.CHANNEL_AVAILABLE_AUTOJOIN, payload)
