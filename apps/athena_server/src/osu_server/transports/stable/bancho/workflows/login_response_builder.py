"""Successful Stable Bancho login の初期 S2C packet stream を構築する."""

from __future__ import annotations

import logging
from collections import defaultdict
from typing import TYPE_CHECKING

from osu_server.domain.compatibility.stable.mode import StableMode
from osu_server.domain.identity.system_users import BANCHO_BOT_IDENTITY, SystemUserIdentity
from osu_server.domain.scores import Playstyle, Ruleset
from osu_server.services.queries.chat import ChannelCatalogQueryInput
from osu_server.services.queries.identity import (
    ListActiveSessionsQueryInput,
    ListFriendIdsQueryInput,
)
from osu_server.services.queries.scores import CurrentUserStatsQueryInput
from osu_server.transports.stable.bancho.mappers.permissions import (
    map_stable_bancho_authorization,
)
from osu_server.transports.stable.bancho.protocol import PROTOCOL_VERSION
from osu_server.transports.stable.bancho.protocol.s2c.login import (
    channel_available,
    channel_available_autojoin,
    channel_info_complete,
    friends_list,
    login_permissions,
    login_reply,
    protocol_version,
    silence_info,
)
from osu_server.transports.stable.bancho.workflows.presence_roster import StablePresenceRoster

if TYPE_CHECKING:
    from collections.abc import Iterable, Mapping

    from osu_server.domain.compatibility.stable import StableUserStatus
    from osu_server.domain.identity.authentication import LoginResponse
    from osu_server.domain.scores.user_stats import UserCurrentStats
    from osu_server.infrastructure.state.interfaces.stable_user_status_store import (
        StableUserStatusStore,
    )
    from osu_server.services.queries.chat import (
        ListAutojoinChannelsQuery,
        ListVisibleChannelsQuery,
    )
    from osu_server.services.queries.identity import (
        ListActiveSessionsQueryUseCase,
        ListFriendIdsQueryUseCase,
        OnlineSessionSnapshot,
    )
    from osu_server.services.queries.scores import CurrentUserStatsQuery

logger = logging.getLogger(__name__)


class LoginResponseBuilder:
    """Successful login 用の初期 S2C packet stream を構築する.

    Attributes:
        _visible_channels_query (ListVisibleChannelsQuery): visible channel query.
        _autojoin_channels_query (ListAutojoinChannelsQuery): autojoin channel query.
        _friend_ids_query (ListFriendIdsQueryUseCase): login user の friend ID query.
        _active_sessions_query (ListActiveSessionsQueryUseCase): online session query.
        _current_user_stats_query (CurrentUserStatsQuery): roster user の current stats query.
        _stable_user_status_store (StableUserStatusStore | None): optional stable status store.
        _bot_identity (SystemUserIdentity): roster に常に含める system bot identity.
        _presence_roster (StablePresenceRoster): presence と stats packet の配置を決める policy.
    """

    _visible_channels_query: ListVisibleChannelsQuery
    _autojoin_channels_query: ListAutojoinChannelsQuery
    _friend_ids_query: ListFriendIdsQueryUseCase
    _active_sessions_query: ListActiveSessionsQueryUseCase
    _current_user_stats_query: CurrentUserStatsQuery
    _stable_user_status_store: StableUserStatusStore | None
    _bot_identity: SystemUserIdentity
    _presence_roster: StablePresenceRoster

    def __init__(
        self,
        *,
        visible_channels_query: ListVisibleChannelsQuery,
        autojoin_channels_query: ListAutojoinChannelsQuery,
        friend_ids_query: ListFriendIdsQueryUseCase,
        active_sessions_query: ListActiveSessionsQueryUseCase,
        current_user_stats_query: CurrentUserStatsQuery,
        stable_user_status_store: StableUserStatusStore | None = None,
        bot_identity: SystemUserIdentity | None = None,
    ) -> None:
        """Login response を構成する query dependency と optional state store を設定する.

        Args:
            visible_channels_query (ListVisibleChannelsQuery): visible channel query.
            autojoin_channels_query (ListAutojoinChannelsQuery): autojoin channel query.
            friend_ids_query (ListFriendIdsQueryUseCase): login user の friend ID を返す query.
            active_sessions_query (ListActiveSessionsQueryUseCase): online session query.
            current_user_stats_query (CurrentUserStatsQuery): current stats query.
            stable_user_status_store (StableUserStatusStore | None): optional stable status store.
            bot_identity (SystemUserIdentity | None): bot identity. None なら BanchoBot.
        """
        self._visible_channels_query = visible_channels_query
        self._autojoin_channels_query = autojoin_channels_query
        self._friend_ids_query = friend_ids_query
        self._active_sessions_query = active_sessions_query
        self._current_user_stats_query = current_user_stats_query
        self._stable_user_status_store = stable_user_status_store
        self._bot_identity = bot_identity or BANCHO_BOT_IDENTITY
        self._presence_roster = StablePresenceRoster(self._bot_identity)

    async def build(self, login_response: LoginResponse) -> bytes:
        """Successful login 用の初期 S2C packet stream を組み立てる.

        Args:
            login_response (LoginResponse): authentication command の session と authorization.

        Returns:
            bytes: login, presence, channel, friend, roster packet を連結した stream.

        Notes:
            channel query は login user の authorization scope で実行する.
            friend query は login user の owner scope で実行する.
            leading presence packet は channel packet より前に置く.
            USER_PRESENCE_BUNDLE は completion packet の末尾に置く.
        """
        user = login_response.user
        authorization_output = map_stable_bancho_authorization(login_response.privileges)
        channel_query_input = ChannelCatalogQueryInput(
            user_privileges=int(login_response.privileges),
            user_role_ids=login_response.role_ids,
        )
        visible_channels = (
            await self._visible_channels_query.execute(channel_query_input)
        ).channels
        autojoin_channels = (
            await self._autojoin_channels_query.execute(channel_query_input)
        ).channels
        friend_ids = (
            await self._friend_ids_query.execute(ListFriendIdsQueryInput(owner_user_id=user.id))
        ).friend_user_ids
        active_sessions = (
            await self._active_sessions_query.execute(ListActiveSessionsQueryInput())
        ).sessions
        statuses_by_user_id = await self._statuses_by_user_id(
            user_id=user.id,
            active_sessions=active_sessions,
        )
        current_stats_by_user_id = await self._current_stats_by_user_id(
            user_id=user.id,
            active_sessions=active_sessions,
            statuses_by_user_id=statuses_by_user_id,
        )
        presence_roster = self._presence_roster.login_roster(
            login_response=login_response,
            active_sessions=active_sessions,
            current_stats_by_user_id=current_stats_by_user_id,
            statuses_by_user_id=statuses_by_user_id,
        )

        packets: list[bytes] = [
            login_reply(user.id),
            protocol_version(PROTOCOL_VERSION),
            login_permissions(int(authorization_output.login_permissions)),
            *presence_roster.leading_packets,
        ]

        packets.extend(
            channel_available(name=channel.name, topic=channel.topic, user_count=user_count)
            for channel, user_count in visible_channels
        )
        packets.extend(
            channel_available_autojoin(
                name=channel.name,
                topic=channel.topic,
                user_count=user_count,
            )
            for channel, user_count in autojoin_channels
        )

        packets.extend(
            [
                channel_info_complete(),
                friends_list(list(friend_ids)),
                silence_info(0),
                presence_roster.bundle_packet,
            ]
        )

        return b"".join(packets)

    async def _current_stats_by_user_id(
        self,
        *,
        user_id: int,
        active_sessions: Iterable[OnlineSessionSnapshot],
        statuses_by_user_id: Mapping[int, StableUserStatus],
    ) -> dict[int, UserCurrentStats]:
        """Roster user を stable play mode ごとに分けて current stats を取得する.

        Args:
            user_id (int): login を完了した user の ID.
            active_sessions (Iterable[OnlineSessionSnapshot]): online session snapshot.
            statuses_by_user_id (Mapping[int, StableUserStatus]): current stable status.

        Returns:
            dict[int, UserCurrentStats]: 取得に成功した user ID ごとの current stats.

        Notes:
            bot は query 対象から除く. unknown mode は osu! ruleset として扱う.
            個別 query failure は記録し, 他の mode group の result を維持する.
        """
        user_ids = _login_stats_user_ids(
            user_id=user_id,
            active_sessions=active_sessions,
            bot_user_id=self._bot_identity.user_id,
        )
        if len(user_ids) == 0:
            return {}
        stats_by_user_id: dict[int, UserCurrentStats] = {}
        play_modes_by_user_id = _play_modes_by_user_id(statuses_by_user_id)
        for play_mode, scoped_user_ids in _user_ids_by_play_mode(
            user_ids,
            play_modes_by_user_id,
        ).items():
            try:
                result = await self._current_user_stats_query.execute(
                    CurrentUserStatsQueryInput(
                        user_ids=scoped_user_ids,
                        ruleset=_ruleset_for_play_mode(play_mode),
                        playstyle=Playstyle.VANILLA,
                    )
                )
            except Exception:
                logger.exception(
                    "stable_login_current_stats_failed",
                    extra={
                        "user_id": user_id,
                        "stats_user_ids": scoped_user_ids,
                        "play_mode": play_mode,
                    },
                )
                continue
            stats_by_user_id.update(result.stats_by_user_id)
        return stats_by_user_id

    async def _statuses_by_user_id(
        self,
        *,
        user_id: int,
        active_sessions: Iterable[OnlineSessionSnapshot],
    ) -> dict[int, StableUserStatus]:
        """Login roster に必要な user の stable status を取得する.

        Args:
            user_id (int): login を完了した user の ID.
            active_sessions (Iterable[OnlineSessionSnapshot]): online session snapshot.

        Returns:
            dict[int, StableUserStatus]: store から取得できた user ID ごとの stable status.

        Notes:
            status store が未設定か read に失敗した場合は空辞書を返す.
            caller は default status を使う.
        """
        if self._stable_user_status_store is None:
            return {}
        status_user_ids = tuple(
            dict.fromkeys(
                [
                    user_id,
                    *(
                        session.user_id
                        for session in active_sessions
                        if session.user_id not in (self._bot_identity.user_id, user_id)
                    ),
                ]
            )
        )
        if len(status_user_ids) == 0:
            return {}
        try:
            return await self._stable_user_status_store.get_statuses(status_user_ids)
        except Exception:
            logger.exception(
                "stable_login_current_status_failed",
                extra={"user_id": user_id, "status_user_ids": status_user_ids},
            )
            return {}


def _login_stats_user_ids(
    *,
    user_id: int,
    active_sessions: Iterable[OnlineSessionSnapshot],
    bot_user_id: int,
) -> tuple[int, ...]:
    """Login stats query に渡す bot を除いた重複なし user ID を作る.

    Args:
        user_id (int): login を完了した user の ID.
        active_sessions (Iterable[OnlineSessionSnapshot]): login 時点で online の session snapshot.
        bot_user_id (int): query 対象から除外する system bot の ID.

    Returns:
        tuple[int, ...]: login user を先頭にした bot を含まない重複なし user ID.
    """
    return tuple(
        dict.fromkeys(
            candidate_user_id
            for candidate_user_id in (
                user_id,
                *(session.user_id for session in active_sessions),
            )
            if candidate_user_id != bot_user_id
        )
    )


def _user_ids_by_play_mode(
    user_ids: tuple[int, ...],
    play_modes_by_user_id: Mapping[int, int],
) -> dict[int, tuple[int, ...]]:
    """User ID を current stable play mode ごとにまとめる.

    Args:
        user_ids (tuple[int, ...]): stats を取得する user ID.
        play_modes_by_user_id (Mapping[int, int]): status から得た user ID ごとの play mode.

    Returns:
        dict[int, tuple[int, ...]]: normalized play mode から対象 user ID 群への対応.
    """
    grouped: dict[int, list[int]] = defaultdict(list)
    for user_id in user_ids:
        grouped[_play_mode_for_user(user_id, play_modes_by_user_id)].append(user_id)
    return {play_mode: tuple(scoped_user_ids) for play_mode, scoped_user_ids in grouped.items()}


def _play_modes_by_user_id(
    statuses_by_user_id: Mapping[int, StableUserStatus],
) -> dict[int, int]:
    """Stable status mapping から user ID ごとの play mode を取り出す.

    Args:
        statuses_by_user_id (Mapping[int, StableUserStatus]): user ID ごとの stable status.

    Returns:
        dict[int, int]: user ID から status の play mode への対応.
    """
    return {user_id: status.play_mode for user_id, status in statuses_by_user_id.items()}


def _play_mode_for_user(
    user_id: int,
    play_modes_by_user_id: Mapping[int, int],
) -> int:
    """User の stable play mode を protocol で有効な値へ正規化する.

    Args:
        user_id (int): play mode を求める user の ID.
        play_modes_by_user_id (Mapping[int, int]): status から得た user ID ごとの play mode.

    Returns:
        int: valid stable mode. 値がないか無効なら osu! mode.
    """
    play_mode = play_modes_by_user_id.get(user_id, StableMode.Osu.value)
    try:
        return StableMode(play_mode).value
    except ValueError:
        return StableMode.Osu.value


def _ruleset_for_play_mode(play_mode: int) -> Ruleset:
    """Stable play mode を score query 用の Ruleset へ変換する.

    Args:
        play_mode (int): stable protocol から得た play mode wire 値.

    Returns:
        Ruleset: valid mode に対応する ruleset. 無効値なら Ruleset.OSU.
    """
    try:
        return Ruleset(play_mode)
    except ValueError:
        return Ruleset.OSU


__all__ = ["LoginResponseBuilder"]
