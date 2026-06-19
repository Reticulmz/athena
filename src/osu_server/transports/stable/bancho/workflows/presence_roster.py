"""Stable presence roster packet policy."""

from __future__ import annotations

import struct
from dataclasses import dataclass
from typing import TYPE_CHECKING

from osu_server.domain.identity.system_users import BANCHO_BOT_IDENTITY
from osu_server.infrastructure.country.codes import country_code_to_id
from osu_server.transports.stable.bancho.mappers.permissions import (
    map_stable_bancho_authorization,
)
from osu_server.transports.stable.bancho.mappers.presence import (
    online_session_presence_packet,
)
from osu_server.transports.stable.bancho.protocol.enums import ServerPacketID
from osu_server.transports.stable.bancho.protocol.s2c.login import (
    user_presence,
    user_presence_bundle,
    user_stats,
)
from osu_server.transports.stable.bancho.protocol.writer import write_packet

if TYPE_CHECKING:
    from collections.abc import Iterable

    from osu_server.domain.identity.authentication import LoginResponse
    from osu_server.domain.identity.system_users import SystemUserIdentity
    from osu_server.services.queries.identity import OnlineSessionSnapshot

_INT32_FMT = struct.Struct("<i")


@dataclass(slots=True, frozen=True)
class StableLoginPresenceRoster:
    """Presence packets that must be split around channel/friend packets."""

    leading_packets: tuple[bytes, ...]
    bundle_packet: bytes


@dataclass(slots=True, frozen=True)
class StableLivePresenceFanout:
    """One live presence packet plus recipient user ids."""

    packet: bytes
    recipient_user_ids: tuple[int, ...]


class StablePresenceRoster:
    """Builds stable login roster and live presence fan-out packets."""

    _bot_identity: SystemUserIdentity

    def __init__(self, bot_identity: SystemUserIdentity | None = None) -> None:
        self._bot_identity = bot_identity or BANCHO_BOT_IDENTITY

    def login_roster(
        self,
        *,
        login_response: LoginResponse,
        active_sessions: Iterable[OnlineSessionSnapshot],
    ) -> StableLoginPresenceRoster:
        """Return initial login presence packets and the final roster bundle."""
        user = login_response.user
        session = login_response.session_data
        authorization_output = map_stable_bancho_authorization(login_response.privileges)
        other_active_sessions = self._other_active_sessions(
            active_sessions,
            user_id=user.id,
        )
        roster_ids = self._roster_ids(user_id=user.id, other_active_sessions=other_active_sessions)
        return StableLoginPresenceRoster(
            leading_packets=(
                user_presence(
                    user_id=user.id,
                    username=user.username,
                    timezone=session.utc_offset + 24,
                    country_id=country_code_to_id(login_response.country),
                    permissions=int(authorization_output.presence_permissions),
                    mode=0,
                    longitude=0.0,
                    latitude=0.0,
                    rank=0,
                ),
                user_stats(
                    user_id=user.id,
                    status=0,
                    status_text="",
                    beatmap_md5="",
                    mods=0,
                    play_mode=0,
                    beatmap_id=0,
                    ranked_score=0,
                    accuracy=0.0,
                    play_count=0,
                    total_score=0,
                    rank=0,
                    pp=0,
                ),
                self._bot_presence_packet(),
                *(online_session_presence_packet(session) for session in other_active_sessions),
            ),
            bundle_packet=user_presence_bundle(roster_ids),
        )

    def connected_user_fanout(
        self,
        *,
        user_id: int,
        active_sessions: Iterable[OnlineSessionSnapshot],
    ) -> StableLivePresenceFanout | None:
        """Return USER_PRESENCE fan-out for a user that just connected."""
        sessions = tuple(active_sessions)
        connected_session = next(
            (session for session in sessions if session.user_id == user_id),
            None,
        )
        if connected_session is None:
            return None
        return StableLivePresenceFanout(
            packet=online_session_presence_packet(connected_session),
            recipient_user_ids=tuple(
                session.user_id for session in sessions if session.user_id != user_id
            ),
        )

    def disconnected_user_fanout(
        self,
        *,
        user_id: int,
        active_sessions: Iterable[OnlineSessionSnapshot],
    ) -> StableLivePresenceFanout:
        """Return USER_QUIT fan-out for a user that just disconnected."""
        quit_packet = write_packet(
            ServerPacketID.USER_QUIT,
            _INT32_FMT.pack(user_id),
        )
        return StableLivePresenceFanout(
            packet=quit_packet,
            recipient_user_ids=tuple(
                session.user_id for session in active_sessions if session.user_id != user_id
            ),
        )

    def _bot_presence_packet(self) -> bytes:
        return user_presence(
            user_id=self._bot_identity.user_id,
            username=self._bot_identity.username,
            timezone=24,
            country_id=0,
            permissions=0,
            mode=0,
            longitude=0.0,
            latitude=0.0,
            rank=0,
        )

    def _other_active_sessions(
        self,
        active_sessions: Iterable[OnlineSessionSnapshot],
        *,
        user_id: int,
    ) -> tuple[OnlineSessionSnapshot, ...]:
        excluded_user_ids = {self._bot_identity.user_id, user_id}
        return tuple(
            session for session in active_sessions if session.user_id not in excluded_user_ids
        )

    def _roster_ids(
        self,
        *,
        user_id: int,
        other_active_sessions: Iterable[OnlineSessionSnapshot],
    ) -> list[int]:
        return list(
            dict.fromkeys(
                [
                    self._bot_identity.user_id,
                    user_id,
                    *(session.user_id for session in other_active_sessions),
                ]
            )
        )


__all__ = ["StableLivePresenceFanout", "StableLoginPresenceRoster", "StablePresenceRoster"]
