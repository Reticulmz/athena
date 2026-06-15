"""Join chat channel command use-case."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

import structlog

from osu_server.domain.chat.policies import ChannelPermission, has_channel_permission
from osu_server.domain.identity.authorization import Privileges, has_privilege

if TYPE_CHECKING:
    from osu_server.infrastructure.state.interfaces.channel_state_store import (
        ChannelStateStore,
    )
    from osu_server.repositories.interfaces.queries.channels import ChannelQueryRepository

logger: structlog.stdlib.BoundLogger = structlog.get_logger(__name__)  # pyright: ignore[reportAny]


@dataclass(frozen=True, slots=True)
class JoinChannelCommand:
    """Command to join a channel."""

    user_id: int
    channel_name: str
    user_privileges: int
    user_role_ids: tuple[int, ...] = ()


@dataclass(frozen=True, slots=True)
class JoinChannelResult:
    """Result of a channel join attempt."""

    joined: bool


class JoinChannelUseCase:
    """Join a user to a channel after read-side ACL validation."""

    def __init__(
        self,
        *,
        channel_repository: ChannelQueryRepository,
        channel_state: ChannelStateStore,
    ) -> None:
        self._channel_repository: ChannelQueryRepository = channel_repository
        self._channel_state: ChannelStateStore = channel_state

    async def execute(self, command: JoinChannelCommand) -> JoinChannelResult:
        if await self._channel_state.is_member(command.channel_name, command.user_id):
            logger.debug(
                "join_idempotent",
                user_id=command.user_id,
                channel=command.channel_name,
            )
            return JoinChannelResult(joined=True)

        channel = await self._channel_repository.get_by_name(command.channel_name)
        if channel is None:
            logger.warning(
                "join_failed",
                user_id=command.user_id,
                channel=command.channel_name,
                reason="channel_not_found",
            )
            return JoinChannelResult(joined=False)

        if not has_privilege(command.user_privileges, Privileges.BYPASS_CHANNEL_ACL):
            overrides = await self._channel_repository.get_overrides_for_channel(channel.id)
            if not has_channel_permission(
                user_privileges=command.user_privileges,
                user_role_ids=command.user_role_ids,
                overrides=overrides,
                permission=ChannelPermission.READ,
            ):
                logger.warning(
                    "join_failed",
                    user_id=command.user_id,
                    channel=command.channel_name,
                    reason="permission_denied",
                )
                return JoinChannelResult(joined=False)

        await self._channel_state.add_member(command.channel_name, command.user_id)
        logger.info("join_success", user_id=command.user_id, channel=command.channel_name)
        return JoinChannelResult(joined=True)
