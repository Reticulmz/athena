# pyright: reportAny=false, reportUnknownVariableType=false
# pyright: reportUnknownMemberType=false, reportUnknownArgumentType=false
# pyright: reportInvalidTypeForm=false
# Caterpillar's metaclass/descriptor patterns require these file-level suppressions.
"""S2C login packet builders.

Each builder function returns a complete packet (7-byte header + payload)
using :func:`write_packet`.

Design ref: S2C Login Packets component in bancho-protocol design.md
Requirements: 6.1-6.12
"""

import struct

from caterpillar.byteorder import LittleEndian
from caterpillar.fields import float32, int32, int64, uint8, uint16
from caterpillar.model import pack
from caterpillar.model import struct as cpstruct

from osu_server.transports.bancho.protocol.enums import ServerPacketID
from osu_server.transports.bancho.protocol.types import BanchoString, Channel, IntList
from osu_server.transports.bancho.protocol.writer import write_packet

_INT32_FMT = struct.Struct("<i")


# ── Task 4.1: Scalar payload builders ───────────────────────────────


def login_reply(user_id: int) -> bytes:
    """Req 6.1: LoginReply — positive=userId, negative=error code."""
    return write_packet(ServerPacketID.LOGIN_REPLY, _INT32_FMT.pack(user_id))


def protocol_version(version: int) -> bytes:
    """Req 6.2: ProtocolVersion."""
    return write_packet(ServerPacketID.PROTOCOL_VERSION, _INT32_FMT.pack(version))


def login_permissions(permissions: int) -> bytes:
    """Req 6.3: LoginPermissions — permission bitmask."""
    return write_packet(ServerPacketID.LOGIN_PERMISSIONS, _INT32_FMT.pack(permissions))


def notification(message: str) -> bytes:
    """Req 6.4: Notification (Announce)."""
    payload: bytes = pack(message, LittleEndian + BanchoString)
    return write_packet(ServerPacketID.ANNOUNCE, payload)


def channel_info_complete() -> bytes:
    """Req 6.9: ChannelInfoComplete — empty payload."""
    return write_packet(ServerPacketID.CHANNEL_INFO_COMPLETE)


def silence_info(remaining_seconds: int) -> bytes:
    """Req 6.10: SilenceInfo — remaining silence duration in seconds."""
    return write_packet(ServerPacketID.SILENCE_INFO, _INT32_FMT.pack(remaining_seconds))


def friends_list(friend_ids: list[int]) -> bytes:
    """Req 6.7: FriendsList — IntList of friend user IDs."""
    il = IntList(count=len(friend_ids), values=friend_ids)
    payload: bytes = pack(il)
    return write_packet(ServerPacketID.FRIENDS_LIST, payload)


def user_presence_bundle(user_ids: list[int]) -> bytes:
    """Req 6.11: UserPresenceBundle — IntList of online user IDs."""
    il = IntList(count=len(user_ids), values=user_ids)
    payload: bytes = pack(il)
    return write_packet(ServerPacketID.USER_PRESENCE_BUNDLE, payload)


# ── Task 4.2: Complex payload builders ──────────────────────────────


@cpstruct(order=LittleEndian)
class _UserPresenceData:
    """Wire format for UserPresence payload (Req 6.5)."""

    user_id: int32
    username: BanchoString
    timezone: uint8
    country_id: uint8
    permissions_mode: uint8  # permissions | (mode << 5)
    longitude: float32
    latitude: float32
    rank: int32


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
    """Wire format for UserStats payload (Req 6.6).

    Embeds StatusUpdate fields inline rather than nesting,
    since the wire format is a flat sequence.
    """

    user_id: int32
    # StatusUpdate fields (inline)
    status: uint8
    status_text: BanchoString
    beatmap_md5: BanchoString
    mods: int32
    play_mode: uint8
    beatmap_id: int32
    # Stats fields
    ranked_score: int64
    accuracy: float32
    play_count: int32
    total_score: int64
    rank: int32
    pp: uint16


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
    """Req 6.6: UserStats."""
    data = _UserStatsData(
        user_id=user_id,
        status=status,
        status_text=status_text,
        beatmap_md5=beatmap_md5,
        mods=mods,
        play_mode=play_mode,
        beatmap_id=beatmap_id,
        ranked_score=ranked_score,
        accuracy=accuracy,
        play_count=play_count,
        total_score=total_score,
        rank=rank,
        pp=pp,
    )
    payload: bytes = pack(data)
    return write_packet(ServerPacketID.USER_STATS, payload)


def channel_available(*, name: str, topic: str, user_count: int) -> bytes:
    """Req 6.8: ChannelAvailable."""
    ch = Channel(name=name, topic=topic, user_count=user_count)
    payload: bytes = pack(ch)
    return write_packet(ServerPacketID.CHANNEL_AVAILABLE, payload)


def channel_available_autojoin(*, name: str, topic: str, user_count: int) -> bytes:
    """Req 6.12: ChannelAvailableAutojoin — same payload, different PacketID."""
    ch = Channel(name=name, topic=topic, user_count=user_count)
    payload: bytes = pack(ch)
    return write_packet(ServerPacketID.CHANNEL_AVAILABLE_AUTOJOIN, payload)
