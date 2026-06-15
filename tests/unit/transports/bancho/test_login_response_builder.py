"""Tests for LoginResponseBuilder — S2C packet stream construction."""

from __future__ import annotations

import struct
from datetime import UTC, datetime
from typing import TYPE_CHECKING, cast, final

from osu_server.domain.chat.channels import Channel, ChannelType
from osu_server.domain.identity.authentication import LoginResponse
from osu_server.domain.identity.authorization import Privileges
from osu_server.domain.identity.sessions import SessionData
from osu_server.domain.identity.users import User
from osu_server.domain.system_user import BANCHO_BOT_IDENTITY
from osu_server.infrastructure.country.codes import country_code_to_id
from osu_server.services.queries.chat import ChannelCatalogQueryResult
from osu_server.transports.stable.bancho.mappers.permissions import (
    map_stable_bancho_authorization,
)
from osu_server.transports.stable.bancho.protocol import PROTOCOL_VERSION
from osu_server.transports.stable.bancho.protocol.enums import ServerPacketID
from osu_server.transports.stable.bancho.protocol.s2c.login import (
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
    from osu_server.services.queries.chat import (
        ListAutojoinChannelsQuery,
        ListVisibleChannelsQuery,
    )

# -- packet header parsing ----------------------------------------------------

_HEADER_FMT = struct.Struct("<HBI")


def _extract_packet_ids(data: bytes) -> list[int]:
    """Extract ServerPacketID values in order from a bancho S2C byte stream."""
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
    """Channel catalog query stub returning pre-configured channel lists.

    Protocol-conformant stub per type-safety-policy: avoids untyped
    AsyncMock while keeping LoginResponseBuilder tests focused on
    packet stream assembly rather than channel ACL logic.
    """

    _channels: list[tuple[Channel, int]]

    def __init__(
        self,
        channels: list[tuple[Channel, int]] | None = None,
    ) -> None:
        self._channels = channels or []

    async def execute(self, _input_data: object) -> ChannelCatalogQueryResult:
        return ChannelCatalogQueryResult(channels=tuple(self._channels))


# -- helpers -----------------------------------------------------------------


def _make_channel(
    *,
    channel_id: int = 1,
    name: str = "#test",
    topic: str = "Test Channel",
    auto_join: bool = False,
) -> Channel:
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


def _make_builder(
    *,
    visible: list[tuple[Channel, int]] | None = None,
    autojoin: list[tuple[Channel, int]] | None = None,
) -> LoginResponseBuilder:
    return LoginResponseBuilder(
        visible_channels_query=cast(
            "ListVisibleChannelsQuery",
            cast("object", _FakeChannelCatalogQuery(visible)),
        ),
        autojoin_channels_query=cast(
            "ListAutojoinChannelsQuery",
            cast("object", _FakeChannelCatalogQuery(autojoin)),
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
    """Verify LoginResponseBuilder.build() produces correct S2C packet order.

    Requirements: 1.1, 1.2, 1.4, 2.4, 3.1, 3.2
    """

    # -- BanchoBot presence & roster tests ---------------------------------

    async def test_banchobot_presence_packet_content(self) -> None:
        """BanchoBot USER_PRESENCE uses deterministic defaults and
        BANCHO_BOT_IDENTITY fields."""
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

    async def test_banchobot_presence_before_bundle(self) -> None:
        """BanchoBot USER_PRESENCE appears earlier in the stream than
        USER_PRESENCE_BUNDLE."""
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
        """USER_PRESENCE_BUNDLE contains BANCHO_BOT_IDENTITY.user_id and
        connecting user ID, duplicate-free."""
        user_id = 42
        builder = _make_builder()
        result = await builder.build(_login_response(user_id=user_id))

        expected = user_presence_bundle([BANCHO_BOT_IDENTITY.user_id, user_id])
        assert expected in result

    async def test_presence_bundle_no_duplicate_when_user_is_banchobot_id(
        self,
    ) -> None:
        """When connecting user has the same ID as BanchoBot, the bundle
        contains that ID only once."""
        bot_id = BANCHO_BOT_IDENTITY.user_id
        builder = _make_builder()
        result = await builder.build(_login_response(user_id=bot_id))

        # Bundle must contain bot_id exactly once
        expected = user_presence_bundle([bot_id])
        assert expected in result

    # -- existing packet order tests ---------------------------------------

    async def test_login_and_presence_permissions_use_stable_bancho_mapper(
        self,
    ) -> None:
        """LoginPermissions and self UserPresence use stable compatibility output."""
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
        """Initial and completion packets in exact order when no channels exist."""
        builder = _make_builder()
        result = await builder.build(_login_response())

        assert _extract_packet_ids(result) == [*_INITIAL_PACKETS, *_COMPLETION_PACKETS]

    async def test_visible_channels_inserted_between_user_stats_and_channel_info_complete(
        self,
    ) -> None:
        """CHANNEL_AVAILABLE appears after USER_STATS, before CHANNEL_INFO_COMPLETE."""
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
        """CHANNEL_AVAILABLE_AUTOJOIN sits between last CHANNEL_AVAILABLE
        and CHANNEL_INFO_COMPLETE."""
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
        """Multiple visible then multiple autojoin channels each maintain their
        insertion order within their respective block."""
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
        """Same LoginResponse produces identical stream; different responses
        produce same packet order but different content."""
        builder = _make_builder()
        lr1 = _login_response(user_id=1, username="Alice")
        lr2 = _login_response(user_id=2, username="Bob")

        result1 = await builder.build(lr1)
        result2 = await builder.build(lr2)

        # Same packet order regardless of which LoginResponse is used
        assert _extract_packet_ids(result1) == _extract_packet_ids(result2)
        # Different payloads (user_id differs in login_reply, user_presence, etc.)
        assert result1 != result2
