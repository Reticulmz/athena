"""Stable Bancho login roster と live presence fan-out packet の policy を提供する."""

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
    """login stream 内で channel と friend packet の前後に分ける presence roster を表す.

    Attributes:
        leading_packets (tuple[bytes, ...]): channel packet より前に置く presence と stats packet.
        bundle_packet (bytes): completion packet の末尾に置く USER_PRESENCE_BUNDLE packet.
    """

    leading_packets: tuple[bytes, ...]
    bundle_packet: bytes


@dataclass(slots=True, frozen=True)
class StableLivePresenceFanout:
    """live presence packet と配信対象 user ID を表す.

    Attributes:
        packet (bytes): enqueue する USER_PRESENCE または USER_QUIT packet.
        recipient_user_ids (tuple[int, ...]): packet を配信する online user の ID.
    """

    packet: bytes
    recipient_user_ids: tuple[int, ...]


class StablePresenceRoster:
    """stable login roster と live presence fan-out packet を構築する.

    Attributes:
        _bot_identity (SystemUserIdentity): roster に常に含める system bot identity.
    """

    _bot_identity: SystemUserIdentity

    def __init__(self, bot_identity: SystemUserIdentity | None = None) -> None:
        """Roster に使用する system bot identity を設定する.

        Args:
            bot_identity (SystemUserIdentity | None): roster に含める bot. None なら BanchoBot.
        """
        self._bot_identity = bot_identity or BANCHO_BOT_IDENTITY

    def login_roster(
        self,
        *,
        login_response: LoginResponse,
        active_sessions: Iterable[OnlineSessionSnapshot],
        current_stats_by_user_id: Mapping[int, UserCurrentStats] | None = None,
        statuses_by_user_id: Mapping[int, StableUserStatus] | None = None,
    ) -> StableLoginPresenceRoster:
        """Login 初期 presence packet と final roster bundle を構築する.

        Args:
            login_response (LoginResponse): successful login の session と authorization.
            active_sessions (Iterable[OnlineSessionSnapshot]): online session snapshot.
            current_stats_by_user_id (Mapping[int, UserCurrentStats] | None): stats.
            statuses_by_user_id (Mapping[int, StableUserStatus] | None): stable status mapping.

        Returns:
            StableLoginPresenceRoster: stream の前半 packet と最後の roster bundle.

        Notes:
            login user と bot の packet を先頭に置く.
            active session 内の login user と bot は重複させない.
            USER_PRESENCE_BUNDLE は source order を保った重複なしの roster にする.
        """
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
        """接続した user の USER_PRESENCE fan-out を構築する.

        Args:
            user_id (int): connection event の対象 user ID.
            active_sessions (Iterable[OnlineSessionSnapshot]): 現在 online の session snapshot.
            play_mode (int | None): 対象 user の current stable mode. None なら osu! mode.

        Returns:
            StableLivePresenceFanout | None: recipient を持つ packet. 対象 session がなければ None.

        Notes:
            stable client の user list mode filter は USER_PRESENCE の mode を使う.
            request 元ではなく接続した対象 user の mode を packet に載せる.
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
        """切断直後の user を通知する USER_QUIT fan-out を構築する.

        Args:
            user_id (int): disconnect event の対象 user ID.
            active_sessions (Iterable[OnlineSessionSnapshot]): 現在 online の session snapshot.

        Returns:
            StableLivePresenceFanout: 対象 user を除く recipient 向け USER_QUIT packet.
        """
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
        """Login user と system bot を除いた active session を返す.

        Args:
            active_sessions (Iterable[OnlineSessionSnapshot]): online session snapshot.
            user_id (int): roster から除外する login user の ID.

        Returns:
            tuple[OnlineSessionSnapshot, ...]: bot と login user を含まない session snapshot.
        """
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
        """bot, login user, other session の順で重複なし roster ID を作る.

        Args:
            user_id (int): login を完了した user の ID.
            other_active_sessions (Iterable[OnlineSessionSnapshot]): other online session.

        Returns:
            list[int]: USER_PRESENCE_BUNDLE に渡す source order を保った user ID.
        """
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
    """Online session ごとの USER_PRESENCE と USER_STATS packet を順に生成する.

    Args:
        sessions (Iterable[OnlineSessionSnapshot]): packet に変換する online session snapshot.
        current_stats_by_user_id (Mapping[int, UserCurrentStats]): user ID ごとの current stats.
        statuses_by_user_id (Mapping[int, StableUserStatus]): user ID ごとの stable status.

    Yields:
        bytes: 各 session の USER_PRESENCE の後に続く USER_STATS packet.
    """
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
    """User の stable status を取得し未登録時は default を返す.

    Args:
        user_id (int): status を求める user の ID.
        statuses_by_user_id (Mapping[int, StableUserStatus]): user ID ごとの stable status.

    Returns:
        StableUserStatus: 登録済み status. 未登録なら DEFAULT_STABLE_USER_STATUS.
    """
    return statuses_by_user_id.get(user_id, DEFAULT_STABLE_USER_STATUS)


def _stable_play_mode(play_mode: int | None) -> int:
    """Optional stable play mode を protocol で有効な値へ正規化する.

    Args:
        play_mode (int | None): status または caller から得た stable mode wire 値.

    Returns:
        int: valid stable mode. None または無効値なら osu! mode.
    """
    if play_mode is None:
        return StableMode.Osu.value
    try:
        return StableMode(play_mode).value
    except ValueError:
        return StableMode.Osu.value


__all__ = ["StableLivePresenceFanout", "StableLoginPresenceRoster", "StablePresenceRoster"]
