"""LoginResponseBuilderが構築するinitial S2C packet stream contractを検証する."""

from __future__ import annotations

import struct
from datetime import UTC, datetime
from decimal import Decimal
from typing import TYPE_CHECKING, cast, final

from osu_server.domain.chat.channels import Channel, ChannelType
from osu_server.domain.compatibility.stable import StableUserStatus
from osu_server.domain.identity.authentication import LoginResponse
from osu_server.domain.identity.authorization import Privileges
from osu_server.domain.identity.sessions import SessionData
from osu_server.domain.identity.system_users import BANCHO_BOT_IDENTITY
from osu_server.domain.identity.users import User
from osu_server.domain.scores import Playstyle, Ruleset
from osu_server.domain.scores.user_stats import UserCurrentStats
from osu_server.infrastructure.country.codes import country_code_to_id
from osu_server.services.queries.chat import ChannelCatalogQueryResult
from osu_server.services.queries.identity import (
    ListActiveSessionsQueryInput,
    ListActiveSessionsQueryResult,
    ListFriendIdsQueryInput,
    ListFriendIdsQueryResult,
    OnlineSessionSnapshot,
)
from osu_server.services.queries.scores import (
    CurrentUserStatsQueryInput,
    CurrentUserStatsQueryResult,
)
from osu_server.transports.stable.bancho.mappers.permissions import (
    map_stable_bancho_authorization,
)
from osu_server.transports.stable.bancho.protocol import PROTOCOL_VERSION
from osu_server.transports.stable.bancho.protocol.enums import ServerPacketID
from osu_server.transports.stable.bancho.protocol.s2c.login import (
    friends_list,
    login_permissions,
    login_reply,
    protocol_version,
    user_presence,
    user_presence_bundle,
    user_stats,
)
from osu_server.transports.stable.bancho.workflows.login_response_builder import (
    LoginResponseBuilder,
)

if TYPE_CHECKING:
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
    )
    from osu_server.services.queries.scores import CurrentUserStatsQuery

# -- packet header parsing ----------------------------------------------------

_HEADER_FMT = struct.Struct("<HBI")


def _extract_packet_ids(data: bytes) -> list[int]:
    """Bancho S2C byte streamからwire順のServerPacketIDを取得する.

    Args:
        data (bytes): 7 byte headerとpayloadを連結したS2C packet stream.

    Returns:
        list[int]: stream内packetのServerPacketIDをwire順に並べた一覧.
    """
    ids: list[int] = []
    offset = 0
    while offset < len(data):
        pid, _, plen = cast(
            "tuple[int, int, int]",
            _HEADER_FMT.unpack(data[offset : offset + 7]),
        )
        ids.append(pid)
        offset += 7 + plen
    return ids


# -- typed stubs for channel catalog query use-cases --------------------------


@final
class _FakeChannelCatalogQuery:
    """設定済みchannel一覧を返すprotocol準拠ChannelCatalogQuery stubを提供する.

    Attributes:
        _channels (list[tuple[Channel, int]]): executeが返すchannelとuser countの順序.

    Notes:
        untyped AsyncMockを使わずpacket stream assemblyだけを検証できるようにする.
    """

    _channels: list[tuple[Channel, int]]

    def __init__(
        self,
        channels: list[tuple[Channel, int]] | None = None,
    ) -> None:
        """executeが返すchannel一覧を設定する.

        Args:
            channels (list[tuple[Channel, int]] | None): channelとuser countの一覧.
                Noneならempty一覧を使う.
        """
        self._channels = channels or []

    async def execute(self, _input_data: object) -> ChannelCatalogQueryResult:
        """Channel query inputを受け取り設定済み一覧を返す.

        Args:
            _input_data (object): protocol充足のため受け取るchannel catalog input.

        Returns:
            ChannelCatalogQueryResult: 設定済みchannel一覧を保持するresult.
        """
        return ChannelCatalogQueryResult(channels=tuple(self._channels))


@final
class _FakeFriendIdsQuery:
    """friend ID query inputを記録して設定済みfriend一覧を返すstubを提供する.

    Attributes:
        calls (list[int]): executeへ渡されたowner user IDの順序.
    """

    def __init__(self, friend_ids: tuple[int, ...] = ()) -> None:
        """executeが返すfriend user ID一覧を設定する.

        Args:
            friend_ids (tuple[int, ...]): login userのfriendとして返すID一覧.
        """
        self._friend_ids = friend_ids
        self.calls: list[int] = []

    async def execute(
        self,
        input_data: ListFriendIdsQueryInput,
    ) -> ListFriendIdsQueryResult:
        """Owner scopeを記録して設定済みfriend ID resultを返す.

        Args:
            input_data (ListFriendIdsQueryInput): friend ownerを指定するquery input.

        Returns:
            ListFriendIdsQueryResult: 設定済みfriend user IDを含むresult.
        """
        owner_user_id = input_data.owner_user_id
        assert isinstance(owner_user_id, int)
        self.calls.append(owner_user_id)
        return ListFriendIdsQueryResult(friend_user_ids=self._friend_ids)


@final
class _FakeActiveSessionsQuery:
    """設定済みonline session snapshotを返すactive session query stubを提供する."""

    def __init__(self, sessions: tuple[OnlineSessionSnapshot, ...] = ()) -> None:
        """executeが返すonline session snapshotを設定する.

        Args:
            sessions (tuple[OnlineSessionSnapshot, ...]): login rosterに含めるactive session一覧.
        """
        self._sessions = sessions

    async def execute(
        self,
        input_data: ListActiveSessionsQueryInput,
    ) -> ListActiveSessionsQueryResult:
        """Active session query inputを検証して設定済みsession resultを返す.

        Args:
            input_data (ListActiveSessionsQueryInput): active session取得を表すquery input.

        Returns:
            ListActiveSessionsQueryResult: 設定済みonline sessionを含むresult.
        """
        assert isinstance(input_data, ListActiveSessionsQueryInput)
        return ListActiveSessionsQueryResult(sessions=self._sessions)


@final
class _FakeCurrentUserStatsQuery:
    """current stats query inputを記録し設定済みstatsまたはerrorを返すstubを提供する.

    Attributes:
        calls (list[tuple[int, ...]]): queryごとのuser ID tupleの順序.
        inputs (list[CurrentUserStatsQueryInput]): executeへ渡された完全なquery inputの順序.
    """

    def __init__(
        self,
        *,
        stats: tuple[UserCurrentStats, ...] = (),
        error: Exception | None = None,
    ) -> None:
        """Return statsとoptional failureを設定する.

        Args:
            stats (tuple[UserCurrentStats, ...]): 成功時に返すcurrent stats一覧.
            error (Exception | None): 設定時にexecuteが送出するerror.
        """
        self._stats = stats
        self._error = error
        self.calls: list[tuple[int, ...]] = []
        self.inputs: list[CurrentUserStatsQueryInput] = []

    async def execute(
        self,
        input_data: CurrentUserStatsQueryInput,
    ) -> CurrentUserStatsQueryResult:
        """Query inputを記録して設定済みstatsを返すか設定済みerrorを送出する.

        Args:
            input_data (CurrentUserStatsQueryInput): user, ruleset, playstyleを指定するquery input.

        Returns:
            CurrentUserStatsQueryResult: 設定済みcurrent statsを持つresult.

        Raises:
            Exception: errorが設定されている場合.
        """
        self.calls.append(input_data.user_ids)
        self.inputs.append(input_data)
        if self._error is not None:
            raise self._error
        return CurrentUserStatsQueryResult(stats=self._stats)


@final
class _FakeStableUserStatusStore:
    """stable statusとplay modeをin-memoryで保持するStatusStore fakeを提供する.

    Attributes:
        requests (list[tuple[int, ...]]): get_statusesへ渡されたuser ID tupleの順序.
    """

    def __init__(self, statuses: dict[int, StableUserStatus] | None = None) -> None:
        """optionalな初期stable status mappingを設定する.

        Args:
            statuses (dict[int, StableUserStatus] | None): user IDごとの初期status.
                Noneならempty mappingを使う.
        """
        self._statuses = statuses or {}
        self.requests: list[tuple[int, ...]] = []

    async def set_status(self, user_id: int, status: StableUserStatus) -> None:
        """userのstable statusを置き換える.

        Args:
            user_id (int): statusを設定するstable userのID.
            status (StableUserStatus): 保存するcurrent stable status.

        Returns:
            None: in-memory statusを更新して完了し, 呼び出し側へ値を返さない.
        """
        self._statuses[user_id] = status

    async def get_statuses(
        self,
        user_ids: tuple[int, ...],
    ) -> dict[int, StableUserStatus]:
        """要求されたuser IDのうち保存済みstatusだけを返す.

        Args:
            user_ids (tuple[int, ...]): statusを取得するstable user ID一覧.

        Returns:
            dict[int, StableUserStatus]: 保存済みstatusを持つuser IDだけのmapping.
        """
        self.requests.append(user_ids)
        return {
            user_id: status
            for user_id in user_ids
            if (status := self._statuses.get(user_id)) is not None
        }

    async def set_play_mode(self, user_id: int, play_mode: int) -> None:
        """保存済みstatusがあるuserのplay modeを置き換える.

        Args:
            user_id (int): play modeを更新するstable userのID.
            play_mode (int): statusへ設定するstable play mode wire値.

        Returns:
            None: statusが存在する場合にplay modeを更新して完了する.
        """
        current = self._statuses.get(user_id)
        if current is not None:
            self._statuses[user_id] = current.with_play_mode(play_mode)

    async def get_play_mode(self, user_id: int) -> int | None:
        """保存済みstatusからuserのplay modeを取得する.

        Args:
            user_id (int): play modeを取得するstable userのID.

        Returns:
            int | None: 保存済みplay mode. statusがなければNone.
        """
        status = self._statuses.get(user_id)
        return None if status is None else status.play_mode

    async def get_play_modes(self, user_ids: tuple[int, ...]) -> dict[int, int]:
        """要求されたuser IDの保存済みplay modeをmappingで返す.

        Args:
            user_ids (tuple[int, ...]): play modeを取得するstable user ID一覧.

        Returns:
            dict[int, int]: statusを持つuser IDだけのplay mode mapping.
        """
        return {
            user_id: status.play_mode
            for user_id in user_ids
            if (status := self._statuses.get(user_id)) is not None
        }

    async def refresh_ttl(self, user_id: int, ttl: int) -> None:
        """protocol充足のためTTL refresh requestを受け取る.

        Args:
            user_id (int): TTLをrefreshするstable userのID.
            ttl (int): refreshを要求するTTL秒数.

        Returns:
            None: in-memory fakeではTTLを保持せずに完了し, 呼び出し側へ値を返さない.
        """
        _ = (user_id, ttl)


# -- helpers -----------------------------------------------------------------


def _make_channel(
    *,
    channel_id: int = 1,
    name: str = "#test",
    topic: str = "Test Channel",
    auto_join: bool = False,
) -> Channel:
    """LoginResponseBuilder test用のpublic Channelを作る.

    Args:
        channel_id (int): channel identifier.
        name (str): stable clientへ表示するchannel名.
        topic (str): stable clientへ表示するchannel topic.
        auto_join (bool): autojoin channelとして送るか.

    Returns:
        Channel: 固定timestampとpublic typeを持つchannel fixture.
    """
    return Channel(
        id=channel_id,
        name=name,
        topic=topic,
        channel_type=ChannelType.PUBLIC,
        auto_join=auto_join,
        rate_limit_messages=None,
        rate_limit_window=None,
        created_at=datetime(2024, 1, 1, tzinfo=UTC),
        updated_at=datetime(2024, 1, 1, tzinfo=UTC),
    )


def _login_response(
    *,
    user_id: int = 42,
    username: str = "TestUser",
    country: str = "JP",
    privileges: Privileges = Privileges.NORMAL,
    role_ids: tuple[int, ...] = (1,),
) -> LoginResponse:
    """LoginResponseBuilderへ渡すsuccessful LoginResponseを作る.

    Args:
        user_id (int): authenticated userのID.
        username (str): authenticated userの表示名.
        country (str): userとsessionへ設定するcountry code.
        privileges (Privileges): stable authorizationへ変換するprivilege集合.
        role_ids (tuple[int, ...]): channel catalog scopeへ渡すrole ID一覧.

    Returns:
        LoginResponse: token, user, privilege, session dataを持つsuccessful response fixture.
    """
    user = User(
        id=user_id,
        username=username,
        safe_username=username.lower(),
        email="test@example.com",
        password_hash="hash",
        country=country,
        created_at=datetime(2024, 1, 1, tzinfo=UTC),
        updated_at=datetime(2024, 1, 1, tzinfo=UTC),
    )
    return LoginResponse(
        token="test-token",
        user=user,
        privileges=privileges,
        role_ids=role_ids,
        country=country,
        session_data=SessionData(
            user_id=user.id,
            username=user.username,
            privileges=int(privileges),
            country=country,
            osu_version="20231111",
            utc_offset=9,
            display_city=False,
            client_hashes="hash",
            pm_private=False,
        ),
    )


def _online_session(
    *,
    user_id: int,
    username: str,
    country: str = "JP",
    privileges: int = 1,
    utc_offset: int = 9,
) -> OnlineSessionSnapshot:
    """Login rosterへ含めるonline session snapshotを作る.

    Args:
        user_id (int): online userのID.
        username (str): online userの表示名.
        country (str): presenceのcountry IDへ変換するcountry code.
        privileges (int): presence permissionへ変換するprivilege bit値.
        utc_offset (int): presence timezoneへ加算するUTC offset.

    Returns:
        OnlineSessionSnapshot: LoginResponseBuilderがroster packetを作るためのsnapshot.
    """
    return OnlineSessionSnapshot(
        user_id=user_id,
        username=username,
        privileges=privileges,
        country=country,
        utc_offset=utc_offset,
    )


def _make_builder(
    *,
    visible: list[tuple[Channel, int]] | None = None,
    autojoin: list[tuple[Channel, int]] | None = None,
    friend_ids: tuple[int, ...] = (),
    active_sessions: tuple[OnlineSessionSnapshot, ...] = (),
    current_stats_query: _FakeCurrentUserStatsQuery | None = None,
    stable_user_status_store: _FakeStableUserStatusStore | None = None,
) -> LoginResponseBuilder:
    """Typed query fakeを注入したLoginResponseBuilderを構築する.

    Args:
        visible (list[tuple[Channel, int]] | None): visible channelとuser countの順序.
        autojoin (list[tuple[Channel, int]] | None): autojoin channelとuser countの順序.
        friend_ids (tuple[int, ...]): login userのfriend user ID一覧.
        active_sessions (tuple[OnlineSessionSnapshot, ...]): rosterへ含めるonline session一覧.
        current_stats_query (_FakeCurrentUserStatsQuery | None): optional stats query fake.
        stable_user_status_store (_FakeStableUserStatusStore | None): optional stable status
            store fake.

    Returns:
        LoginResponseBuilder: initial S2C packet streamを構築するbuilder.
    """
    stats_query = current_stats_query or _FakeCurrentUserStatsQuery()
    return LoginResponseBuilder(
        visible_channels_query=cast(
            "ListVisibleChannelsQuery",
            cast("object", _FakeChannelCatalogQuery(visible)),
        ),
        autojoin_channels_query=cast(
            "ListAutojoinChannelsQuery",
            cast("object", _FakeChannelCatalogQuery(autojoin)),
        ),
        friend_ids_query=cast(
            "ListFriendIdsQueryUseCase",
            cast("object", _FakeFriendIdsQuery(friend_ids)),
        ),
        active_sessions_query=cast(
            "ListActiveSessionsQueryUseCase",
            cast("object", _FakeActiveSessionsQuery(active_sessions)),
        ),
        current_user_stats_query=cast(
            "CurrentUserStatsQuery",
            cast("object", stats_query),
        ),
        stable_user_status_store=cast(
            "StableUserStatusStore | None",
            stable_user_status_store,
        ),
    )


# -- base expected order constants --------------------------------------------

_INITIAL_PACKETS = [
    ServerPacketID.LOGIN_REPLY,
    ServerPacketID.PROTOCOL_VERSION,
    ServerPacketID.LOGIN_PERMISSIONS,
    ServerPacketID.USER_PRESENCE,  # connecting user
    ServerPacketID.USER_STATS,
    ServerPacketID.USER_PRESENCE,  # BanchoBot
]

_COMPLETION_PACKETS = [
    ServerPacketID.CHANNEL_INFO_COMPLETE,
    ServerPacketID.FRIENDS_LIST,
    ServerPacketID.SILENCE_INFO,
    ServerPacketID.USER_PRESENCE_BUNDLE,
]


# -- tests -------------------------------------------------------------------


class TestLoginResponseBuilder:
    """LoginResponseBuilder.buildが作るroster, stats, channel packet順を検証する."""

    # -- BanchoBot presence & roster tests ---------------------------------

    async def test_banchobot_presence_packet_content(self) -> None:
        """BanchoBot USER_PRESENCEがidentity fieldとdeterministic defaultを使う契約を検証する.

        Returns:
            None: expected BanchoBot presence packetがstreamにあることを確認して完了する.
        """
        builder = _make_builder()
        result = await builder.build(_login_response())

        expected = user_presence(
            user_id=BANCHO_BOT_IDENTITY.user_id,
            username=BANCHO_BOT_IDENTITY.username,
            timezone=24,
            country_id=0,
            permissions=0,
            mode=0,
            longitude=0.0,
            latitude=0.0,
            rank=0,
        )
        assert expected in result

    async def test_banchobot_presence_uses_login_user_current_mode(self) -> None:
        """BanchoBot presenceがlogin userの保存済みcurrent modeを使う契約を検証する.

        Returns:
            None: status store requestとmode付きBanchoBot presenceを確認して完了する.
        """
        status_store = _FakeStableUserStatusStore(
            {
                42: StableUserStatus(
                    status=0,
                    status_text="",
                    beatmap_md5="",
                    mods=0,
                    play_mode=Ruleset.MANIA.value,
                    beatmap_id=0,
                )
            }
        )
        builder = _make_builder(stable_user_status_store=status_store)
        result = await builder.build(_login_response(user_id=42))

        expected = user_presence(
            user_id=BANCHO_BOT_IDENTITY.user_id,
            username=BANCHO_BOT_IDENTITY.username,
            timezone=24,
            country_id=0,
            permissions=0,
            mode=Ruleset.MANIA.value,
            longitude=0.0,
            latitude=0.0,
            rank=0,
        )
        assert status_store.requests == [(42,)]
        assert expected in result

    async def test_banchobot_presence_before_bundle(self) -> None:
        """BanchoBot USER_PRESENCEがUSER_PRESENCE_BUNDLEより前に置かれる契約を検証する.

        Returns:
            None: packet ID列のpresence位置とbundle位置を検証して完了し, 呼び出し側へ値を返さない.
        """
        builder = _make_builder()
        result = await builder.build(_login_response())

        ids = _extract_packet_ids(result)

        # Find last USER_PRESENCE (BanchoBot) position
        presence_positions = [
            i for i, pid in enumerate(ids) if pid == ServerPacketID.USER_PRESENCE
        ]
        assert len(presence_positions) >= 2, (
            f"Expected at least 2 USER_PRESENCE packets, got {len(presence_positions)}"
        )
        banchobot_presence_pos = presence_positions[-1]

        # Find USER_PRESENCE_BUNDLE position (should be last packet)
        try:
            bundle_pos = ids.index(ServerPacketID.USER_PRESENCE_BUNDLE)
        except ValueError:
            bundle_pos = -1

        assert bundle_pos > banchobot_presence_pos, (
            f"USER_PRESENCE_BUNDLE (pos {bundle_pos}) must appear after "
            f"BanchoBot USER_PRESENCE (pos {banchobot_presence_pos})"
        )

    async def test_presence_bundle_includes_banchobot_and_user(self) -> None:
        """USER_PRESENCE_BUNDLEがBanchoBotと接続userを重複なく含む契約を検証する.

        Returns:
            None: expected bundle packetのstream内存在を検証して完了し, 呼び出し側へ値を返さない.
        """
        user_id = 42
        builder = _make_builder()
        result = await builder.build(_login_response(user_id=user_id))

        expected = user_presence_bundle([BANCHO_BOT_IDENTITY.user_id, user_id])
        assert expected in result

    async def test_presence_bundle_no_duplicate_when_user_is_banchobot_id(
        self,
    ) -> None:
        """接続userがBanchoBot IDの場合にbundleがそのIDを1回だけ含む契約を検証する.

        Returns:
            None: duplicate-free single ID bundleを検証して完了し, 呼び出し側へ値を返さない.
        """
        bot_id = BANCHO_BOT_IDENTITY.user_id
        builder = _make_builder()
        result = await builder.build(_login_response(user_id=bot_id))

        # Bundle must contain bot_id exactly once
        expected = user_presence_bundle([bot_id])
        assert expected in result

    async def test_online_session_presence_packets_are_included(self) -> None:
        """Online roster userのUSER_PRESENCEとbundle entryをstreamへ含める契約を検証する.

        Returns:
            None: country, timezone, permissionを持つpresenceとbundleを確認して完了する.
        """
        online_user = _online_session(
            user_id=100,
            username="OnlineUser",
            country="US",
            utc_offset=-5,
        )
        authorization_output = map_stable_bancho_authorization(Privileges.NORMAL)
        builder = _make_builder(active_sessions=(online_user,))

        result = await builder.build(_login_response(user_id=42))

        assert (
            user_presence(
                user_id=100,
                username="OnlineUser",
                timezone=19,
                country_id=country_code_to_id("US"),
                permissions=int(authorization_output.presence_permissions),
                mode=0,
                longitude=0.0,
                latitude=0.0,
                rank=0,
            )
            in result
        )
        assert user_presence_bundle([BANCHO_BOT_IDENTITY.user_id, 42, 100]) in result

    async def test_online_session_presence_skips_self_and_banchobot_duplicates(
        self,
    ) -> None:
        """Online rosterがselfとBanchoBotのduplicate presenceを除外する契約を検証する.

        Returns:
            None: duplicate-free bundleとexpected presence countを確認して完了する.
        """
        user_id = 42
        other_user = _online_session(user_id=100, username="OnlineUser")
        builder = _make_builder(
            active_sessions=(
                _online_session(user_id=user_id, username="TestUser"),
                _online_session(
                    user_id=BANCHO_BOT_IDENTITY.user_id,
                    username=BANCHO_BOT_IDENTITY.username,
                ),
                other_user,
            )
        )

        result = await builder.build(_login_response(user_id=user_id))

        assert user_presence_bundle([BANCHO_BOT_IDENTITY.user_id, user_id, 100]) in result
        ids = _extract_packet_ids(result)
        assert ids.count(ServerPacketID.USER_PRESENCE) == 3

    async def test_friends_list_uses_owner_scoped_friend_query(self) -> None:
        """Friends listがlogin user owner scopeで返されたfriend IDを使う契約を検証する.

        Returns:
            None: configured friend listの存在とempty list不在を確認して完了する.
        """
        builder = _make_builder(friend_ids=(10, 20))

        result = await builder.build(_login_response(user_id=42))

        assert friends_list([10, 20]) in result
        assert friends_list([]) not in result

    async def test_friends_list_does_not_synthesize_banchobot(self) -> None:
        """Empty friend query resultへBanchoBotを自動追加しない契約を検証する.

        Returns:
            None: empty friends listとBanchoBot入りlist不在を確認して完了する.
        """
        builder = _make_builder(friend_ids=())

        result = await builder.build(_login_response())

        assert friends_list([]) in result
        assert friends_list([BANCHO_BOT_IDENTITY.user_id]) not in result

    async def test_logged_in_user_stats_uses_current_stats_values(self) -> None:
        """Login userのcurrent stats値をUSER_STATS packetへ反映する契約を検証する.

        Returns:
            None: stats query scopeとrounded ppを含むpacketを確認して完了する.
        """
        stats_query = _FakeCurrentUserStatsQuery(
            stats=(
                UserCurrentStats(
                    user_id=42,
                    pp=Decimal("122.5"),
                    accuracy=0.9876,
                    global_rank=12,
                    play_count=34,
                    ranked_score=123_456_789,
                    total_score=9_876_543_210,
                    play_time_seconds=3600,
                ),
            )
        )
        builder = _make_builder(current_stats_query=stats_query)

        result = await builder.build(_login_response(user_id=42))

        assert stats_query.calls == [(42,)]
        assert (
            user_stats(
                user_id=42,
                status=0,
                status_text="",
                beatmap_md5="",
                mods=0,
                play_mode=0,
                beatmap_id=0,
                ranked_score=123_456_789,
                accuracy=0.9876,
                play_count=34,
                total_score=9_876_543_210,
                rank=12,
                pp=123,
            )
            in result
        )

    async def test_login_stats_read_failure_falls_back_to_default_stats(self) -> None:
        """Login stats query failure時にdefault USER_STATSをstreamへ残す契約を検証する.

        Returns:
            None: query callとzero default stats packetを検証して完了し, 呼び出し側へ値を返さない.
        """
        stats_query = _FakeCurrentUserStatsQuery(error=RuntimeError("stats unavailable"))
        builder = _make_builder(current_stats_query=stats_query)

        result = await builder.build(_login_response(user_id=42))

        assert stats_query.calls == [(42,)]
        assert (
            user_stats(
                user_id=42,
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
            )
            in result
        )

    async def test_online_roster_users_get_user_stats_packets(self) -> None:
        """Online roster userにもcurrent statsを持つUSER_STATS packetを送る契約を検証する.

        Returns:
            None: login userとroster userのquery scopeおよびroster stats packetを
            確認して完了する.
        """
        stats_query = _FakeCurrentUserStatsQuery(
            stats=(UserCurrentStats(user_id=100, pp=Decimal("50"), global_rank=20),)
        )
        builder = _make_builder(
            active_sessions=(_online_session(user_id=100, username="OnlineUser"),),
            current_stats_query=stats_query,
        )

        result = await builder.build(_login_response(user_id=42))

        assert stats_query.calls == [(42, 100)]
        assert (
            user_stats(
                user_id=100,
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
                rank=20,
                pp=50,
            )
            in result
        )

    async def test_online_roster_users_use_current_status_mode_on_login(self) -> None:
        """Online roster userが保存済みstatusとplay modeをpresenceとstatsへ反映する契約を検証する.

        Returns:
            None: mode別stats query, status request, mode付きpacket群を確認して完了する.
        """
        stats_query = _FakeCurrentUserStatsQuery(
            stats=(
                UserCurrentStats(user_id=42, pp=Decimal("10"), global_rank=30),
                UserCurrentStats(user_id=100, pp=Decimal("50"), global_rank=20),
            )
        )
        status_store = _FakeStableUserStatusStore(
            {
                100: StableUserStatus(
                    status=2,
                    status_text="playing mania",
                    beatmap_md5="a" * 32,
                    mods=64,
                    play_mode=Ruleset.MANIA.value,
                    beatmap_id=1234,
                )
            }
        )
        online_user = _online_session(user_id=100, username="OnlineUser")
        builder = _make_builder(
            active_sessions=(online_user,),
            current_stats_query=stats_query,
            stable_user_status_store=status_store,
        )

        result = await builder.build(_login_response(user_id=42))

        assert status_store.requests == [(42, 100)]
        assert stats_query.inputs == [
            CurrentUserStatsQueryInput(
                user_ids=(42,),
                ruleset=Ruleset.OSU,
                playstyle=Playstyle.VANILLA,
            ),
            CurrentUserStatsQueryInput(
                user_ids=(100,),
                ruleset=Ruleset.MANIA,
                playstyle=Playstyle.VANILLA,
            ),
        ]
        assert (
            user_presence(
                user_id=100,
                username="OnlineUser",
                timezone=33,
                country_id=country_code_to_id("JP"),
                permissions=int(
                    map_stable_bancho_authorization(Privileges.NORMAL).presence_permissions
                ),
                mode=3,
                longitude=0.0,
                latitude=0.0,
                rank=0,
            )
            in result
        )
        assert (
            user_stats(
                user_id=100,
                status=2,
                status_text="playing mania",
                beatmap_md5="a" * 32,
                mods=64,
                play_mode=3,
                beatmap_id=1234,
                ranked_score=0,
                accuracy=0.0,
                play_count=0,
                total_score=0,
                rank=20,
                pp=50,
            )
            in result
        )

    # -- existing packet order tests ---------------------------------------

    async def test_login_and_presence_permissions_use_stable_bancho_mapper(
        self,
    ) -> None:
        """LOGIN_PERMISSIONSとself USER_PRESENCEがstable compatibility mapperを使う契約を検証する.

        Returns:
            None: authorization outputを持つstream prefixを確認して完了する.
        """
        login_response = _login_response(
            privileges=Privileges.ADMIN | Privileges.DEVELOPER | Privileges.UNRESTRICTED
        )
        authorization_output = map_stable_bancho_authorization(login_response.privileges)
        builder = _make_builder()

        result = await builder.build(login_response)

        expected_self_prefix = b"".join(
            [
                login_reply(login_response.user.id),
                protocol_version(PROTOCOL_VERSION),
                login_permissions(int(authorization_output.login_permissions)),
                user_presence(
                    user_id=login_response.user.id,
                    username=login_response.user.username,
                    timezone=login_response.session_data.utc_offset + 24,
                    country_id=country_code_to_id(login_response.country),
                    permissions=int(authorization_output.presence_permissions),
                    mode=0,
                    longitude=0.0,
                    latitude=0.0,
                    rank=0,
                ),
                user_stats(
                    user_id=login_response.user.id,
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
            ]
        )
        assert result.startswith(expected_self_prefix)

    async def test_packet_order_without_channels(self) -> None:
        """channelがない場合にinitialとcompletion packetをexact orderで並べる契約を検証する.

        Returns:
            None: packet ID列が既定initialとcompletion順序に一致することを確認して完了する.
        """
        builder = _make_builder()
        result = await builder.build(_login_response())

        assert _extract_packet_ids(result) == [*_INITIAL_PACKETS, *_COMPLETION_PACKETS]

    async def test_visible_channels_inserted_between_user_stats_and_channel_info_complete(
        self,
    ) -> None:
        """Visible CHANNEL_AVAILABLEをUSER_STATS後かつcompletion前へ挿入する契約を検証する.

        Returns:
            None: 2 channelを含むexact packet ID順序を検証して完了し, 呼び出し側へ値を返さない.
        """
        ch_osu = _make_channel(channel_id=1, name="#osu", topic="General")
        ch_announce = _make_channel(channel_id=2, name="#announce", topic="News")
        builder = _make_builder(visible=[(ch_osu, 5), (ch_announce, 3)])

        result = await builder.build(_login_response())
        ids = _extract_packet_ids(result)

        assert ids == [
            *_INITIAL_PACKETS,
            ServerPacketID.CHANNEL_AVAILABLE,
            ServerPacketID.CHANNEL_AVAILABLE,
            *_COMPLETION_PACKETS,
        ]

    async def test_autojoin_channels_after_visible_before_channel_info_complete(
        self,
    ) -> None:
        """CHANNEL_AVAILABLE_AUTOJOINをvisible block後かつcompletion前へ置く契約を検証する.

        Returns:
            None: visibleとautojoin channelを含むexact packet ID順序を確認して完了する.
        """
        ch_visible = _make_channel(channel_id=1, name="#osu", topic="General")
        ch_autojoin = _make_channel(channel_id=2, name="#lobby", topic="Lobby", auto_join=True)
        builder = _make_builder(
            visible=[(ch_visible, 5)],
            autojoin=[(ch_autojoin, 2)],
        )

        result = await builder.build(_login_response())
        ids = _extract_packet_ids(result)

        assert ids == [
            *_INITIAL_PACKETS,
            ServerPacketID.CHANNEL_AVAILABLE,
            ServerPacketID.CHANNEL_AVAILABLE_AUTOJOIN,
            *_COMPLETION_PACKETS,
        ]

    async def test_multiple_visible_and_autojoin_channels_preserve_relative_order(
        self,
    ) -> None:
        """複数visible channelと複数autojoin channelの相対順序を維持する契約を検証する.

        Returns:
            None: 各channel block内のexact packet ID順序を検証して完了し, 呼び出し側へ値を返さない.
        """
        ch_v1 = _make_channel(channel_id=1, name="#osu", topic="General")
        ch_v2 = _make_channel(channel_id=2, name="#announce", topic="News")
        ch_a1 = _make_channel(channel_id=3, name="#lobby", topic="Lobby", auto_join=True)
        ch_a2 = _make_channel(channel_id=4, name="#help", topic="Help", auto_join=True)
        builder = _make_builder(
            visible=[(ch_v1, 1), (ch_v2, 2)],
            autojoin=[(ch_a1, 3), (ch_a2, 4)],
        )

        result = await builder.build(_login_response())
        ids = _extract_packet_ids(result)

        assert ids == [
            *_INITIAL_PACKETS,
            ServerPacketID.CHANNEL_AVAILABLE,
            ServerPacketID.CHANNEL_AVAILABLE,
            ServerPacketID.CHANNEL_AVAILABLE_AUTOJOIN,
            ServerPacketID.CHANNEL_AVAILABLE_AUTOJOIN,
            *_COMPLETION_PACKETS,
        ]

    async def test_stream_depends_only_on_login_response_not_on_auth_state(
        self,
    ) -> None:
        """LoginResponseだけがstream contentを決め, user差はpacket orderを変えない契約を検証する.

        Returns:
            None: 同一packet ID順序と異なるpayload contentを確認して完了する.
        """
        builder = _make_builder()
        lr1 = _login_response(user_id=1, username="Alice")
        lr2 = _login_response(user_id=2, username="Bob")

        result1 = await builder.build(lr1)
        result2 = await builder.build(lr2)

        # Same packet order regardless of which LoginResponse is used
        assert _extract_packet_ids(result1) == _extract_packet_ids(result2)
        # Different payloads (user_id differs in login_reply, user_presence, etc.)
        assert result1 != result2
