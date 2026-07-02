"""C2S (client-to-server) packet payload definitions."""

from osu_server.transports.stable.bancho.protocol.c2s.chat import (
    ChannelNamePayload,
    ChatMessagePayload,
    channel_name_payload,
    message_payload,
    parse_channel_name_payload,
    parse_message_payload,
)
from osu_server.transports.stable.bancho.protocol.c2s.friends import (
    FriendOnlyDmsPayload,
    FriendUserIdPayload,
    friend_only_dms_payload,
    friend_user_id_payload,
    parse_friend_only_dms_payload,
    parse_friend_user_id_payload,
)
from osu_server.transports.stable.bancho.protocol.c2s.presence import (
    PresenceRequestAllReservedPayload,
    PresenceRequestPayload,
    parse_presence_request_all_payload,
    parse_presence_request_payload,
    presence_request_payload,
)
from osu_server.transports.stable.bancho.protocol.c2s.stats import (
    StatsRequestPayload,
    parse_stats_request_payload,
    stats_request_payload,
)
from osu_server.transports.stable.bancho.protocol.c2s.status import (
    StatusChangePayload,
    parse_status_change_payload,
    status_change_payload,
)

__all__ = (
    "ChannelNamePayload",
    "ChatMessagePayload",
    "FriendOnlyDmsPayload",
    "FriendUserIdPayload",
    "PresenceRequestAllReservedPayload",
    "PresenceRequestPayload",
    "StatsRequestPayload",
    "StatusChangePayload",
    "channel_name_payload",
    "friend_only_dms_payload",
    "friend_user_id_payload",
    "message_payload",
    "parse_channel_name_payload",
    "parse_friend_only_dms_payload",
    "parse_friend_user_id_payload",
    "parse_message_payload",
    "parse_presence_request_all_payload",
    "parse_presence_request_payload",
    "parse_stats_request_payload",
    "parse_status_change_payload",
    "presence_request_payload",
    "stats_request_payload",
    "status_change_payload",
)
