"""Successful login response stream construction."""

from __future__ import annotations

from typing import TYPE_CHECKING

from osu_server.domain.identity.system_users import BANCHO_BOT_IDENTITY, SystemUserIdentity
from osu_server.services.queries.chat import ChannelCatalogQueryInput
from osu_server.services.queries.identity import (
    ListActiveSessionsQueryInput,
    ListFriendIdsQueryInput,
)
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
    from osu_server.domain.identity.authentication import LoginResponse
    from osu_server.services.queries.chat import (
        ListAutojoinChannelsQuery,
        ListVisibleChannelsQuery,
    )
    from osu_server.services.queries.identity import (
        ListActiveSessionsQueryUseCase,
        ListFriendIdsQueryUseCase,
    )


class LoginResponseBuilder:
    """Build the initial S2C packet stream for successful login."""

    _visible_channels_query: ListVisibleChannelsQuery
    _autojoin_channels_query: ListAutojoinChannelsQuery
    _friend_ids_query: ListFriendIdsQueryUseCase
    _active_sessions_query: ListActiveSessionsQueryUseCase
    _bot_identity: SystemUserIdentity
    _presence_roster: StablePresenceRoster

    def __init__(
        self,
        *,
        visible_channels_query: ListVisibleChannelsQuery,
        autojoin_channels_query: ListAutojoinChannelsQuery,
        friend_ids_query: ListFriendIdsQueryUseCase,
        active_sessions_query: ListActiveSessionsQueryUseCase,
        bot_identity: SystemUserIdentity | None = None,
    ) -> None:
        self._visible_channels_query = visible_channels_query
        self._autojoin_channels_query = autojoin_channels_query
        self._friend_ids_query = friend_ids_query
        self._active_sessions_query = active_sessions_query
        self._bot_identity = bot_identity or BANCHO_BOT_IDENTITY
        self._presence_roster = StablePresenceRoster(self._bot_identity)

    async def build(self, login_response: LoginResponse) -> bytes:
        """Assemble the S2C packet stream for a successful login."""
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
        presence_roster = self._presence_roster.login_roster(
            login_response=login_response,
            active_sessions=active_sessions,
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


__all__ = ["LoginResponseBuilder"]
