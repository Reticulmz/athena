"""Online session と system bot を Stable Bancho presence packet へ変換する."""

from __future__ import annotations

from typing import TYPE_CHECKING

from osu_server.domain.identity.authorization import Privileges
from osu_server.domain.identity.system_users import BANCHO_BOT_IDENTITY, SystemUserIdentity
from osu_server.infrastructure.country.codes import country_code_to_id
from osu_server.transports.stable.bancho.mappers.permissions import (
    map_stable_bancho_authorization,
)
from osu_server.transports.stable.bancho.protocol.s2c.login import user_presence

if TYPE_CHECKING:
    from osu_server.services.queries.identity import OnlineSessionSnapshot

_STABLE_TIMEZONE_BASE = 24
_STABLE_DEFAULT_COUNTRY_ID = 0
_STABLE_DEFAULT_PERMISSIONS = 0
_STABLE_DEFAULT_MODE = 0
_STABLE_DEFAULT_COORDINATE = 0.0
_STABLE_DEFAULT_RANK = 0


def online_session_presence_packet(session: OnlineSessionSnapshot) -> bytes:
    """指定した online session snapshot の default mode USER_PRESENCE packet を構築する.

    Args:
        session (OnlineSessionSnapshot): presence に変換する active session snapshot.

    Returns:
        bytes: default stable mode を持つ USER_PRESENCE packet.
    """
    authorization_output = map_stable_bancho_authorization(Privileges(session.privileges))
    return user_presence(
        user_id=session.user_id,
        username=session.username,
        timezone=session.utc_offset + _STABLE_TIMEZONE_BASE,
        country_id=country_code_to_id(session.country),
        permissions=int(authorization_output.presence_permissions),
        mode=_STABLE_DEFAULT_MODE,
        longitude=_STABLE_DEFAULT_COORDINATE,
        latitude=_STABLE_DEFAULT_COORDINATE,
        rank=_STABLE_DEFAULT_RANK,
    )


def online_session_presence_packet_for_mode(
    session: OnlineSessionSnapshot,
    *,
    play_mode: int,
) -> bytes:
    """指定 stable mode の online session USER_PRESENCE packet を構築する.

    Args:
        session (OnlineSessionSnapshot): presence に変換する active session snapshot.
        play_mode (int): 対象 user の current stable mode wire 値.

    Returns:
        bytes: play_mode を含む USER_PRESENCE packet.

    Notes:
        stable client は USER_PRESENCE と USER_STATS の mode で roster を filter するため,
        request 元ではなく対象 user の current mode を指定する.
    """
    authorization_output = map_stable_bancho_authorization(Privileges(session.privileges))
    return user_presence(
        user_id=session.user_id,
        username=session.username,
        timezone=session.utc_offset + _STABLE_TIMEZONE_BASE,
        country_id=country_code_to_id(session.country),
        permissions=int(authorization_output.presence_permissions),
        mode=play_mode,
        longitude=_STABLE_DEFAULT_COORDINATE,
        latitude=_STABLE_DEFAULT_COORDINATE,
        rank=_STABLE_DEFAULT_RANK,
    )


def bot_presence_packet(
    bot_identity: SystemUserIdentity | None = None,
    *,
    play_mode: int = _STABLE_DEFAULT_MODE,
) -> bytes:
    """指定した system bot identity の USER_PRESENCE packet を構築する.

    Args:
        bot_identity (SystemUserIdentity | None): system bot. None なら BanchoBot.
        play_mode (int): bot を表示する stable mode wire 値.

    Returns:
        bytes: system bot を表す USER_PRESENCE packet.

    Notes:
        stable protocol では user を複数 mode に同時所属させられない.
        呼び出し側は request context に合う単一 mode を指定する. 省略時は osu! mode を使う.
    """
    bot = bot_identity or BANCHO_BOT_IDENTITY
    return user_presence(
        user_id=bot.user_id,
        username=bot.username,
        timezone=_STABLE_TIMEZONE_BASE,
        country_id=_STABLE_DEFAULT_COUNTRY_ID,
        permissions=_STABLE_DEFAULT_PERMISSIONS,
        mode=play_mode,
        longitude=_STABLE_DEFAULT_COORDINATE,
        latitude=_STABLE_DEFAULT_COORDINATE,
        rank=_STABLE_DEFAULT_RANK,
    )


__all__ = [
    "bot_presence_packet",
    "online_session_presence_packet",
    "online_session_presence_packet_for_mode",
]
