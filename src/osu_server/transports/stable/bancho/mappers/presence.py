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


def bot_presence_packet(bot_identity: SystemUserIdentity | None = None) -> bytes:
    """Build stable USER_PRESENCE for the server bot identity."""
    bot = bot_identity or BANCHO_BOT_IDENTITY
    return user_presence(
        user_id=bot.user_id,
        username=bot.username,
        timezone=_STABLE_TIMEZONE_BASE,
        country_id=_STABLE_DEFAULT_COUNTRY_ID,
        permissions=_STABLE_DEFAULT_PERMISSIONS,
        mode=_STABLE_DEFAULT_MODE,
        longitude=_STABLE_DEFAULT_COORDINATE,
        latitude=_STABLE_DEFAULT_COORDINATE,
        rank=_STABLE_DEFAULT_RANK,
    )


__all__ = ["bot_presence_packet", "online_session_presence_packet"]
