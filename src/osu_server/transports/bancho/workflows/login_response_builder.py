"""Successful login response stream construction."""

from __future__ import annotations

from typing import TYPE_CHECKING

from osu_server.domain.system_user import BANCHO_BOT_IDENTITY, SystemUserIdentity
from osu_server.infrastructure.country.codes import country_code_to_id
from osu_server.services.permission_service import PermissionService
from osu_server.transports.bancho.protocol import PROTOCOL_VERSION
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

if TYPE_CHECKING:
    from osu_server.domain.auth import LoginResponse
    from osu_server.services.channel_service import ChannelService


class LoginResponseBuilder:
    """Build the initial S2C packet stream for successful login."""

    _channel_service: ChannelService
    _bot_identity: SystemUserIdentity

    def __init__(
        self,
        *,
        channel_service: ChannelService,
        bot_identity: SystemUserIdentity | None = None,
    ) -> None:
        self._channel_service = channel_service
        self._bot_identity = bot_identity or BANCHO_BOT_IDENTITY

    async def build(self, login_response: LoginResponse) -> bytes:
        """Assemble the S2C packet stream for a successful login."""
        user = login_response.user
        session = login_response.session_data
        client_flags = PermissionService.to_client_flags(login_response.privileges)
        country_id = country_code_to_id(login_response.country)
        role_ids = list(login_response.role_ids)

        visible_channels = await self._channel_service.get_visible_channels(
            user_privileges=int(login_response.privileges),
            user_role_ids=role_ids,
        )
        autojoin_channels = await self._channel_service.get_autojoin_channels(
            user_privileges=int(login_response.privileges),
            user_role_ids=role_ids,
        )

        packets: list[bytes] = [
            login_reply(user.id),
            protocol_version(PROTOCOL_VERSION),
            login_permissions(int(client_flags)),
            user_presence(
                user_id=user.id,
                username=user.username,
                timezone=session.utc_offset + 24,
                country_id=country_id,
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
        ]

        packets.append(
            user_presence(
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
        )

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

        roster_ids = list(dict.fromkeys([self._bot_identity.user_id, user.id]))

        packets.extend(
            [
                channel_info_complete(),
                friends_list([]),
                silence_info(0),
                user_presence_bundle(roster_ids),
            ]
        )

        return b"".join(packets)


__all__ = ["LoginResponseBuilder"]
