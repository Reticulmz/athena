"""Tests for successful login response stream construction."""

import struct
from typing import cast

from osu_server.domain.auth import LoginResponse
from osu_server.domain.role import Privileges
from osu_server.domain.session import SessionData
from osu_server.infrastructure.country.codes import country_code_to_id
from osu_server.infrastructure.state.memory.channel_state_store import InMemoryChannelStateStore
from osu_server.repositories.memory.channel_repository import InMemoryChannelRepository
from osu_server.services.channel_service import ChannelService
from osu_server.services.permission_service import PermissionService
from osu_server.transports.bancho.protocol.enums import ServerPacketID
from osu_server.transports.bancho.protocol.s2c.login import (
    channel_available,
    channel_available_autojoin,
    channel_info_complete,
    friends_list,
    login_permissions,
    login_reply,
    protocol_version,
    silence_info,
    user_presence,
    user_presence_bundle,
    user_stats,
)
from osu_server.transports.bancho.workflows import LoginResponseBuilder
from tests.factories.domain import make_channel, make_channel_role_override, make_user


async def _make_channel_service() -> ChannelService:
    channel_repo = InMemoryChannelRepository()
    channel_state = InMemoryChannelStateStore()

    osu_channel = await channel_repo.create(
        make_channel(id=1, name="#osu", topic="General discussion", auto_join=True)
    )
    announce_channel = await channel_repo.create(
        make_channel(id=2, name="#announce", topic="Announcements", auto_join=False)
    )
    channel_repo.seed_override(make_channel_role_override(channel_id=osu_channel.id, role_id=7))
    channel_repo.seed_override(
        make_channel_role_override(channel_id=announce_channel.id, role_id=7)
    )
    await channel_state.add_member("#osu", 101)
    await channel_state.add_member("#announce", 201)
    await channel_state.add_member("#announce", 202)

    return ChannelService(channel_repo=channel_repo, channel_state=channel_state)


def _login_response() -> LoginResponse:
    user = make_user(id=42, username="BuilderUser", country="JP")
    privileges = Privileges.NORMAL | Privileges.SUPPORTER
    return LoginResponse(
        token="token",
        user=user,
        privileges=privileges,
        role_ids=(7,),
        country="JP",
        session_data=SessionData(
            user_id=user.id,
            username=user.username,
            privileges=int(privileges),
            country="JP",
            osu_version="20231111",
            utc_offset=9,
            display_city=False,
            client_hashes="hashes",
            pm_private=False,
        ),
    )


def _packet_ids(stream: bytes) -> list[ServerPacketID]:
    ids: list[ServerPacketID] = []
    offset = 0
    while offset < len(stream):
        packet_id, compressed, payload_size = cast(
            "tuple[int, int, int]", struct.unpack_from("<HBI", stream, offset)
        )
        assert compressed == 0
        ids.append(ServerPacketID(packet_id))
        offset += 7 + payload_size
    assert offset == len(stream)
    return ids


class TestLoginResponseBuilder:
    async def test_builds_successful_login_packet_stream_in_stable_order(self) -> None:
        builder = LoginResponseBuilder(channel_service=await _make_channel_service())
        login_response = _login_response()

        stream = await builder.build(login_response)

        assert _packet_ids(stream) == [
            ServerPacketID.LOGIN_REPLY,
            ServerPacketID.PROTOCOL_VERSION,
            ServerPacketID.LOGIN_PERMISSIONS,
            ServerPacketID.USER_PRESENCE,
            ServerPacketID.USER_STATS,
            ServerPacketID.CHANNEL_AVAILABLE,
            ServerPacketID.CHANNEL_AVAILABLE,
            ServerPacketID.CHANNEL_AVAILABLE_AUTOJOIN,
            ServerPacketID.CHANNEL_INFO_COMPLETE,
            ServerPacketID.FRIENDS_LIST,
            ServerPacketID.SILENCE_INFO,
            ServerPacketID.USER_PRESENCE_BUNDLE,
        ]

    async def test_builds_byte_compatible_successful_login_packet_stream(self) -> None:
        builder = LoginResponseBuilder(channel_service=await _make_channel_service())
        login_response = _login_response()
        user = login_response.user
        client_flags = PermissionService.to_client_flags(login_response.privileges)

        stream = await builder.build(login_response)

        assert stream == b"".join(
            [
                login_reply(user.id),
                protocol_version(19),
                login_permissions(int(client_flags)),
                user_presence(
                    user_id=user.id,
                    username=user.username,
                    timezone=login_response.session_data.utc_offset + 24,
                    country_id=country_code_to_id(login_response.country),
                    permissions=int(client_flags),
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
                channel_available(
                    name="#osu",
                    topic="General discussion",
                    user_count=1,
                ),
                channel_available(
                    name="#announce",
                    topic="Announcements",
                    user_count=2,
                ),
                channel_available_autojoin(
                    name="#osu",
                    topic="General discussion",
                    user_count=1,
                ),
                channel_info_complete(),
                friends_list([]),
                silence_info(0),
                user_presence_bundle([user.id]),
            ]
        )
