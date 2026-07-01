"""Stable bancho online presence packet mapping."""

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
    """Build stable USER_PRESENCE for an active online session snapshot."""
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
    """指定 play mode で active session の USER_PRESENCE を構築する。

    引数:
        session: online presence に載せる active session snapshot。
        play_mode: 対象 user の current stable mode wire 値。

    戻り値:
        Bancho S2C USER_PRESENCE packet bytes。

    例外:
        独自例外は送出しない。

    制約:
        Stable client は USER_PRESENCE の mode bit と USER_STATS.mode を使って
        roster を mode filter するため、対象 user の current mode を載せる。
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
    """Stable USER_PRESENCE for server bot identity を構築する。

    引数:
        bot_identity: packet に載せる system user identity。未指定時は BanchoBot。
        play_mode: Bot を表示する stable mode wire 値。

    戻り値:
        Bancho S2C USER_PRESENCE packet bytes。

    例外:
        wire type の範囲外値は既存 packet builder の pack error として送出する。

    制約:
        Stable protocol は user を複数 mode に同時所属させられないため、呼び出し元が
        request context に合った単一 mode を指定する。未指定時は既存通り osu!。
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
