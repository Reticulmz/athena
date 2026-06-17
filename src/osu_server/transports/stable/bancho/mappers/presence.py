"""Stable bancho online presence packet mapping."""

from __future__ import annotations

from typing import TYPE_CHECKING

from osu_server.domain.identity.authorization import Privileges
from osu_server.infrastructure.country.codes import country_code_to_id
from osu_server.transports.stable.bancho.mappers.permissions import (
    map_stable_bancho_authorization,
)
from osu_server.transports.stable.bancho.protocol.s2c.login import user_presence

if TYPE_CHECKING:
    from osu_server.services.queries.identity import OnlineSessionSnapshot


def online_session_presence_packet(session: OnlineSessionSnapshot) -> bytes:
    """Build stable USER_PRESENCE for an active online session snapshot."""
    authorization_output = map_stable_bancho_authorization(Privileges(session.privileges))
    return user_presence(
        user_id=session.user_id,
        username=session.username,
        timezone=session.utc_offset + 24,
        country_id=country_code_to_id(session.country),
        permissions=int(authorization_output.presence_permissions),
        mode=0,
        longitude=0.0,
        latitude=0.0,
        rank=0,
    )


__all__ = ["online_session_presence_packet"]
