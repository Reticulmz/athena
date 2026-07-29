"""channel catalogとmessage delivery targetをread-onlyに取得するqueryを定義する."""

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
    """channel catalogを読むcallerのauthorization入力を表す.

    Attributes:
        user_privileges (int): channel ACL判定に使うprivilege bitset.
        user_role_ids (tuple[int, ...]): channel ACL判定に使うrole ID列.
    """

    user_privileges: int
    user_role_ids: tuple[int, ...] = ()


@dataclass(frozen=True, slots=True)
class ChannelCatalogQueryResult:
    """閲覧可能channelとcurrent member countの結果を表す.

    Attributes:
        channels (tuple[tuple[Channel, int], ...]): channelとcurrent member countの組を並べた列.
    """

    channels: tuple[tuple[Channel, int], ...]


@dataclass(frozen=True, slots=True)
class ResolveChannelMessageDeliveryQueryInput:
    """channel message deliveryを検証するread-only入力を表す.

    Attributes:
        sender_id (int): messageを送ろうとするuserのID.
        channel_name (str): delivery targetを解決するchannel名.
        user_privileges (int): write ACL判定に使うprivilege bitset.
        user_role_ids (tuple[int, ...]): write ACL判定に使うrole ID列.
    """

    sender_id: int
    channel_name: str
    user_privileges: int
    user_role_ids: tuple[int, ...] = ()


@dataclass(frozen=True, slots=True)
class ResolveChannelMessageDeliveryQueryResult:
    """channel message deliveryのread-only検証結果を表す.

    Attributes:
        channel (Channel | None): 解決したchannel. 不存在またはmemberでない場合はNone.
        delivered_to (frozenset[int] | None): sender以外のdelivery target user ID集合.
            delivery不可の場合はNone.
    """

    channel: Channel | None
    delivered_to: frozenset[int] | None


class ListVisibleChannelsQuery:
    """userがread権限を持つchannelとmember countを取得する.

    Attributes:
        _channel_repository (ChannelQueryRepository): channelとACL overrideを読み取るrepository.
        _channel_state (ChannelStateStore): current member countを読み取るstate store.
    """

    def __init__(
        self,
        *,
        channel_repository: ChannelQueryRepository,
        channel_state: ChannelStateStore,
    ) -> None:
        """Channel catalog queryに使うrepositoryとstate storeを保持する.

        Args:
            channel_repository (ChannelQueryRepository): channelとACL overrideを読み取るrepository.
            channel_state (ChannelStateStore): current member countを読み取るstate store.
        """
        self._channel_repository: ChannelQueryRepository = channel_repository
        self._channel_state: ChannelStateStore = channel_state

    async def execute(
        self,
        input_data: ChannelCatalogQueryInput,
    ) -> ChannelCatalogQueryResult:
        """userがread権限を持つ全channelとcurrent member countを返す.

        Args:
            input_data (ChannelCatalogQueryInput): callerのprivilegeとrole IDを持つ入力.

        Returns:
            ChannelCatalogQueryResult: 可視channelとmember countを並べた結果.
        """
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
    """userがread権限を持つautojoin channelとmember countを取得する.

    Attributes:
        _channel_repository (ChannelQueryRepository): autojoin channelとACL overrideを読む
            repository.
        _channel_state (ChannelStateStore): current member countを読み取るstate store.
    """

    def __init__(
        self,
        *,
        channel_repository: ChannelQueryRepository,
        channel_state: ChannelStateStore,
    ) -> None:
        """Autojoin channel queryに使うrepositoryとstate storeを保持する.

        Args:
            channel_repository (ChannelQueryRepository): autojoin channelとACL overrideを読む
                repository.
            channel_state (ChannelStateStore): current member countを読み取るstate store.
        """
        self._channel_repository: ChannelQueryRepository = channel_repository
        self._channel_state: ChannelStateStore = channel_state

    async def execute(
        self,
        input_data: ChannelCatalogQueryInput,
    ) -> ChannelCatalogQueryResult:
        """userがread権限を持つautojoin channelとcurrent member countを返す.

        Args:
            input_data (ChannelCatalogQueryInput): callerのprivilegeとrole IDを持つ入力.

        Returns:
            ChannelCatalogQueryResult: 可視autojoin channelとmember countを並べた結果.
        """
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
    """channel messageをdeliveryできるmember targetをread-onlyに解決する.

    Attributes:
        _channel_repository (ChannelQueryRepository): channelとwrite ACL overrideを読むrepository.
        _channel_state (ChannelStateStore): channel membershipを読むstate store.
    """

    def __init__(
        self,
        *,
        channel_repository: ChannelQueryRepository,
        channel_state: ChannelStateStore,
    ) -> None:
        """Delivery target queryに使うrepositoryとstate storeを保持する.

        Args:
            channel_repository (ChannelQueryRepository): channelとwrite ACL overrideを読む
                repository.
            channel_state (ChannelStateStore): channel membershipを読むstate store.
        """
        self._channel_repository: ChannelQueryRepository = channel_repository
        self._channel_state: ChannelStateStore = channel_state

    async def execute(
        self,
        input_data: ResolveChannelMessageDeliveryQueryInput,
    ) -> ResolveChannelMessageDeliveryQueryResult:
        """senderのmembershipとwrite ACLを検証してdelivery targetを解決する.

        Args:
            input_data (ResolveChannelMessageDeliveryQueryInput): senderとchannelとauthorization
                入力.

        Returns:
            ResolveChannelMessageDeliveryQueryResult: delivery可能なchannelとsender以外の
                member集合.

        Notes:
            senderがmemberでない場合とchannelが存在しない場合とwrite権限がない場合は
            delivered_toをNoneにして拒否結果を返す.
        """
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
    """ACLでfilterしたchannelにcurrent member countを付与する.

    Args:
        channel_repository (ChannelQueryRepository): channel ACL overrideを読むrepository.
        channel_state (ChannelStateStore): channel member countを読むstate store.
        channels (list[Channel]): 可視性を判定するchannel列.
        user_privileges (int): read ACL判定に使うprivilege bitset.
        user_role_ids (tuple[int, ...]): read ACL判定に使うrole ID列.

    Returns:
        list[tuple[Channel, int]]: callerに可視なchannelとmember countの組を並べた列.
    """
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
