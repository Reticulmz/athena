"""Chat channel query use-cases."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

import structlog

from osu_server.domain.chat.policies import ChannelPermission, has_channel_permission
from osu_server.domain.identity.authorization import Privileges, has_privilege

if TYPE_CHECKING:
    from osu_server.domain.chat.channels import Channel
    from osu_server.infrastructure.state.interfaces.channel_state_store import (
        ChannelStateStore,
    )
    from osu_server.repositories.interfaces.queries.channels import ChannelQueryRepository

logger: structlog.stdlib.BoundLogger = structlog.get_logger(__name__)  # pyright: ignore[reportAny]


@dataclass(frozen=True, slots=True)
class ChannelCatalogQueryInput:
    """Authorization data for a channel catalog read."""

    user_privileges: int
    user_role_ids: tuple[int, ...] = ()


@dataclass(frozen=True, slots=True)
class ChannelCatalogQueryResult:
    """Visible channel rows with current member counts."""

    channels: tuple[tuple[Channel, int], ...]


@dataclass(frozen=True, slots=True)
class ResolveChannelMessageDeliveryQueryInput:
    """Read input for validating channel message delivery."""

    sender_id: int
    channel_name: str
    user_privileges: int
    user_role_ids: tuple[int, ...] = ()


@dataclass(frozen=True, slots=True)
class ResolveChannelMessageDeliveryQueryResult:
    """Read result for channel message delivery."""

    channel: Channel | None
    delivered_to: frozenset[int] | None


class ListVisibleChannelsQuery:
    """Read channels visible to a user."""

    def __init__(
        self,
        *,
        channel_repository: ChannelQueryRepository,
        channel_state: ChannelStateStore,
    ) -> None:
        self._channel_repository: ChannelQueryRepository = channel_repository
        self._channel_state: ChannelStateStore = channel_state

    async def execute(
        self,
        input_data: ChannelCatalogQueryInput,
    ) -> ChannelCatalogQueryResult:
        channels = await self._channel_repository.get_all()
        visible = await _filter_channels_with_count(
            channel_repository=self._channel_repository,
            channel_state=self._channel_state,
            channels=channels,
            user_privileges=input_data.user_privileges,
            user_role_ids=input_data.user_role_ids,
        )
        return ChannelCatalogQueryResult(channels=tuple(visible))


class ListAutojoinChannelsQuery:
    """Read auto-join channels visible to a user."""

    def __init__(
        self,
        *,
        channel_repository: ChannelQueryRepository,
        channel_state: ChannelStateStore,
    ) -> None:
        self._channel_repository: ChannelQueryRepository = channel_repository
        self._channel_state: ChannelStateStore = channel_state

    async def execute(
        self,
        input_data: ChannelCatalogQueryInput,
    ) -> ChannelCatalogQueryResult:
        channels = await self._channel_repository.get_auto_join()
        visible = await _filter_channels_with_count(
            channel_repository=self._channel_repository,
            channel_state=self._channel_state,
            channels=channels,
            user_privileges=input_data.user_privileges,
            user_role_ids=input_data.user_role_ids,
        )
        return ChannelCatalogQueryResult(channels=tuple(visible))


class ResolveChannelMessageDeliveryQuery:
    """Read current channel delivery targets and rate-limit metadata."""

    def __init__(
        self,
        *,
        channel_repository: ChannelQueryRepository,
        channel_state: ChannelStateStore,
    ) -> None:
        self._channel_repository: ChannelQueryRepository = channel_repository
        self._channel_state: ChannelStateStore = channel_state

    async def execute(
        self,
        input_data: ResolveChannelMessageDeliveryQueryInput,
    ) -> ResolveChannelMessageDeliveryQueryResult:
        if not await self._channel_state.is_member(
            input_data.channel_name,
            input_data.sender_id,
        ):
            logger.warning(
                "deliver_rejected",
                sender_id=input_data.sender_id,
                channel=input_data.channel_name,
                reason="not_a_member",
            )
            return ResolveChannelMessageDeliveryQueryResult(
                channel=None,
                delivered_to=None,
            )

        channel = await self._channel_repository.get_by_name(input_data.channel_name)
        if channel is None:
            if not has_privilege(input_data.user_privileges, Privileges.BYPASS_CHANNEL_ACL):
                logger.warning(
                    "deliver_rejected",
                    sender_id=input_data.sender_id,
                    channel=input_data.channel_name,
                    reason="channel_not_found",
                )
                return ResolveChannelMessageDeliveryQueryResult(
                    channel=None,
                    delivered_to=None,
                )
        else:
            overrides = await self._channel_repository.get_overrides_for_channel(channel.id)
            if not has_channel_permission(
                user_privileges=input_data.user_privileges,
                user_role_ids=input_data.user_role_ids,
                overrides=overrides,
                permission=ChannelPermission.WRITE,
            ):
                logger.warning(
                    "deliver_rejected",
                    sender_id=input_data.sender_id,
                    channel=input_data.channel_name,
                    reason="write_permission_denied",
                )
                return ResolveChannelMessageDeliveryQueryResult(
                    channel=channel,
                    delivered_to=None,
                )

        members = await self._channel_state.get_members(input_data.channel_name)
        targets = frozenset(members - {input_data.sender_id})
        logger.info(
            "delivery_targets_resolved",
            sender_id=input_data.sender_id,
            channel=input_data.channel_name,
            recipient_count=len(targets),
        )
        return ResolveChannelMessageDeliveryQueryResult(
            channel=channel,
            delivered_to=targets,
        )


async def _filter_channels_with_count(
    *,
    channel_repository: ChannelQueryRepository,
    channel_state: ChannelStateStore,
    channels: list[Channel],
    user_privileges: int,
    user_role_ids: tuple[int, ...],
) -> list[tuple[Channel, int]]:
    if has_privilege(user_privileges, Privileges.BYPASS_CHANNEL_ACL):
        visible = channels
    else:
        channel_ids = [channel.id for channel in channels]
        overrides_map = await channel_repository.get_overrides_for_channels(channel_ids)
        visible = [
            channel
            for channel in channels
            if has_channel_permission(
                user_privileges=user_privileges,
                user_role_ids=user_role_ids,
                overrides=overrides_map.get(channel.id, []),
                permission=ChannelPermission.READ,
            )
        ]

    result: list[tuple[Channel, int]] = []
    for channel in visible:
        count = await channel_state.get_member_count(channel.name)
        result.append((channel, count))
    return result
