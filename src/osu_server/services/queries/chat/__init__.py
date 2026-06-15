"""Chat query use-case package."""

from osu_server.services.queries.chat.channels import (
    ChannelCatalogQueryInput,
    ChannelCatalogQueryResult,
    ListAutojoinChannelsQuery,
    ListVisibleChannelsQuery,
    ResolveChannelMessageDeliveryQuery,
    ResolveChannelMessageDeliveryQueryInput,
    ResolveChannelMessageDeliveryQueryResult,
)
from osu_server.services.queries.chat.messages import (
    ChatHistoryQueryResult,
    ListChannelMessagesQuery,
    ListChannelMessagesQueryInput,
    ListPrivateMessagesQuery,
    ListPrivateMessagesQueryInput,
)
from osu_server.services.queries.chat.private_message_service import (
    PMDeliveryResult,
    PrivateMessageService,
)
from osu_server.services.queries.chat.private_messages import (
    ResolvePrivateMessageTargetQuery,
    ResolvePrivateMessageTargetQueryInput,
    ResolvePrivateMessageTargetQueryResult,
)

__all__ = [
    "ChannelCatalogQueryInput",
    "ChannelCatalogQueryResult",
    "ChatHistoryQueryResult",
    "ListAutojoinChannelsQuery",
    "ListChannelMessagesQuery",
    "ListChannelMessagesQueryInput",
    "ListPrivateMessagesQuery",
    "ListPrivateMessagesQueryInput",
    "ListVisibleChannelsQuery",
    "PMDeliveryResult",
    "PrivateMessageService",
    "ResolveChannelMessageDeliveryQuery",
    "ResolveChannelMessageDeliveryQueryInput",
    "ResolveChannelMessageDeliveryQueryResult",
    "ResolvePrivateMessageTargetQuery",
    "ResolvePrivateMessageTargetQueryInput",
    "ResolvePrivateMessageTargetQueryResult",
]
