"""C2S (client-to-server) packet payload definitions."""

from osu_server.transports.stable.bancho.protocol.c2s.chat import (
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
from osu_server.transports.stable.bancho.protocol.c2s.status import (
    parse_status_change_payload,
    status_change_payload,
)

__all__ = (
    "FriendOnlyDmsPayload",
    "FriendUserIdPayload",
    "channel_name_payload",
    "friend_only_dms_payload",
    "friend_user_id_payload",
    "message_payload",
    "parse_channel_name_payload",
    "parse_friend_only_dms_payload",
    "parse_friend_user_id_payload",
    "parse_message_payload",
    "parse_status_change_payload",
    "status_change_payload",
)
