"""Stable presence roster packet policy."""

from __future__ import annotations

import struct
from dataclasses import dataclass
from typing import TYPE_CHECKING

from osu_server.domain.compatibility.stable import DEFAULT_STABLE_USER_STATUS
from osu_server.domain.compatibility.stable.mode import StableMode
from osu_server.domain.identity.system_users import BANCHO_BOT_IDENTITY
from osu_server.infrastructure.country.codes import country_code_to_id
from osu_server.transports.stable.bancho.mappers.permissions import (
    map_stable_bancho_authorization,
)
from osu_server.transports.stable.bancho.mappers.presence import (
    bot_presence_packet,
    online_session_presence_packet_for_mode,
)
from osu_server.transports.stable.bancho.mappers.user_stats import (
    stable_user_stats_packet,
)
from osu_server.transports.stable.bancho.protocol.enums import ServerPacketID
from osu_server.transports.stable.bancho.protocol.s2c.login import (
    user_presence,
    user_presence_bundle,
)
from osu_server.transports.stable.bancho.protocol.writer import write_packet

if TYPE_CHECKING:
    from collections.abc import Iterable, Iterator, Mapping

    from osu_server.domain.compatibility.stable import StableUserStatus
    from osu_server.domain.identity.authentication import LoginResponse
    from osu_server.domain.identity.system_users import SystemUserIdentity
    from osu_server.domain.scores.user_stats import UserCurrentStats
    from osu_server.services.queries.identity import OnlineSessionSnapshot

_INT32_FMT = struct.Struct("<i")
_STABLE_TIMEZONE_BASE = 24
_STABLE_DEFAULT_COUNTRY_ID = 0
_STABLE_DEFAULT_PERMISSIONS = 0
_STABLE_DEFAULT_COORDINATE = 0.0
_STABLE_DEFAULT_RANK = 0


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
        current_stats_by_user_id: Mapping[int, UserCurrentStats] | None = None,
        statuses_by_user_id: Mapping[int, StableUserStatus] | None = None,
    ) -> StableLoginPresenceRoster:
        """login 初期 presence packets と final roster bundle を返す。"""
        user = login_response.user
        session = login_response.session_data
        stats_by_user_id = current_stats_by_user_id or {}
        statuses = statuses_by_user_id or {}
        self_status = _status_for_user(user.id, statuses)
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
                    timezone=session.utc_offset + _STABLE_TIMEZONE_BASE,
                    country_id=country_code_to_id(login_response.country),
                    permissions=int(authorization_output.presence_permissions),
                    mode=self_status.play_mode,
                    longitude=_STABLE_DEFAULT_COORDINATE,
                    latitude=_STABLE_DEFAULT_COORDINATE,
                    rank=_STABLE_DEFAULT_RANK,
                ),
                stable_user_stats_packet(
                    user_id=user.id,
                    current_stats=stats_by_user_id.get(user.id),
                    play_mode=self_status.play_mode,
                    status=self_status,
                ),
                bot_presence_packet(
                    self._bot_identity,
                    play_mode=self_status.play_mode,
                ),
                *_online_session_login_packets(
                    other_active_sessions,
                    current_stats_by_user_id=stats_by_user_id,
                    statuses_by_user_id=statuses,
                ),
            ),
            bundle_packet=user_presence_bundle(roster_ids),
        )

    def connected_user_fanout(
        self,
        *,
        user_id: int,
        active_sessions: Iterable[OnlineSessionSnapshot],
        play_mode: int | None = None,
    ) -> StableLivePresenceFanout | None:
        """接続した user の USER_PRESENCE fan-out を返す。

        引数:
            user_id: 接続イベントの対象 user id。
            active_sessions: 現在 online として扱われる session snapshot 群。
            play_mode: 対象 user の current stable mode。未指定時は osu! として扱う。

        戻り値:
            配信 packet と recipient user id 群。対象 session がなければ None。

        例外:
            独自例外は送出しない。

        制約:
            Stable client の user list mode toggle は USER_PRESENCE の mode bit を
            client-side filter に使うため、要求者ではなく対象 user の mode を載せる。
        """
        sessions = tuple(active_sessions)
        connected_session = next(
            (session for session in sessions if session.user_id == user_id),
            None,
        )
        if connected_session is None:
            return None
        return StableLivePresenceFanout(
            packet=online_session_presence_packet_for_mode(
                connected_session,
                play_mode=_stable_play_mode(play_mode),
            ),
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


def _online_session_login_packets(
    sessions: Iterable[OnlineSessionSnapshot],
    *,
    current_stats_by_user_id: Mapping[int, UserCurrentStats],
    statuses_by_user_id: Mapping[int, StableUserStatus],
) -> Iterator[bytes]:
    for session in sessions:
        status = _status_for_user(session.user_id, statuses_by_user_id)
        yield online_session_presence_packet_for_mode(session, play_mode=status.play_mode)
        yield stable_user_stats_packet(
            user_id=session.user_id,
            current_stats=current_stats_by_user_id.get(session.user_id),
            play_mode=status.play_mode,
            status=status,
        )


def _status_for_user(
    user_id: int,
    statuses_by_user_id: Mapping[int, StableUserStatus],
) -> StableUserStatus:
    return statuses_by_user_id.get(user_id, DEFAULT_STABLE_USER_STATUS)


def _stable_play_mode(play_mode: int | None) -> int:
    if play_mode is None:
        return StableMode.Osu.value
    try:
        return StableMode(play_mode).value
    except ValueError:
        return StableMode.Osu.value


__all__ = ["StableLivePresenceFanout", "StableLoginPresenceRoster", "StablePresenceRoster"]
