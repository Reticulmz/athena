"""Successful login response stream construction."""

from __future__ import annotations

from typing import TYPE_CHECKING

from osu_server.domain.system_user import BANCHO_BOT_IDENTITY, SystemUserIdentity
from osu_server.infrastructure.country.codes import country_code_to_id
from osu_server.services.queries.chat import ChannelCatalogQueryInput
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
from osu_server.transports.stable.bancho.mappers.permissions import (
    map_stable_bancho_authorization,
)

if TYPE_CHECKING:
    from osu_server.domain.identity.authentication import LoginResponse
    from osu_server.services.queries.chat import (
        ListAutojoinChannelsQuery,
        ListVisibleChannelsQuery,
    )


class LoginResponseBuilder:
    """Build the initial S2C packet stream for successful login."""

    _visible_channels_query: ListVisibleChannelsQuery
    _autojoin_channels_query: ListAutojoinChannelsQuery
    _bot_identity: SystemUserIdentity

    def __init__(
        self,
        *,
        visible_channels_query: ListVisibleChannelsQuery,
        autojoin_channels_query: ListAutojoinChannelsQuery,
        bot_identity: SystemUserIdentity | None = None,
    ) -> None:
        self._visible_channels_query = visible_channels_query
        self._autojoin_channels_query = autojoin_channels_query
        self._bot_identity = bot_identity or BANCHO_BOT_IDENTITY

    async def build(self, login_response: LoginResponse) -> bytes:
        """Assemble the S2C packet stream for a successful login."""
        user = login_response.user
        session = login_response.session_data
        authorization_output = map_stable_bancho_authorization(login_response.privileges)
        country_id = country_code_to_id(login_response.country)
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

        packets: list[bytes] = [
            login_reply(user.id),
            protocol_version(PROTOCOL_VERSION),
            login_permissions(int(authorization_output.login_permissions)),
            user_presence(
                user_id=user.id,
                username=user.username,
                timezone=session.utc_offset + 24,
                country_id=country_id,
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
