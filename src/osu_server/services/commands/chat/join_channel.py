"""chat channel への参加を認可して volatile membership state を更新する use-case を提供する.

この module は read-side channel ACL を確認してから channel state store へ member を追加する.
すでに
member の request は成功として扱い、membership state を重複変更しない.
"""

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
    """channel 参加認可に必要な caller identity と authorization を表す command.

    Attributes:
        user_id (int): channel へ参加しようとする user の識別子.
        channel_name (str): 参加対象の channel name.
        user_privileges (int): `BYPASS_CHANNEL_ACL` を含む server-side privilege bitset.
        user_role_ids (tuple[int, ...]): channel ACL override と照合する role ID 群.
    """

    user_id: int
    channel_name: str
    user_privileges: int
    user_role_ids: tuple[int, ...] = ()


@dataclass(frozen=True, slots=True)
class JoinChannelResult:
    """channel 参加要求の認可結果を表す.

    Attributes:
        joined (bool): member だったか、新たに追加したかを問わず参加を許可した場合はTrue.
    """

    joined: bool


class JoinChannelUseCase:
    """read-side ACL を検証して user を channel へ参加させる use-case.

    channel 不存在または READ permission 不足では state を変更せず失敗結果を返す. caller が
    `BYPASS_CHANNEL_ACL` を持つ場合は role override を照合しない.

    Attributes:
        _channel_repository (ChannelQueryRepository):
            channel と role override を read-side で検索する repository.
        _channel_state (ChannelStateStore): channel membership を保持する volatile state store.
    """

    def __init__(
        self,
        *,
        channel_repository: ChannelQueryRepository,
        channel_state: ChannelStateStore,
    ) -> None:
        """Channel ACL と membership state を扱う依存関係を設定する.

        Args:
            channel_repository (ChannelQueryRepository):
                channel definition と ACL override を取得する repository.
            channel_state (ChannelStateStore):
                許可済み user を channel member として保存する state store.

        """
        self._channel_repository: ChannelQueryRepository = channel_repository
        self._channel_state: ChannelStateStore = channel_state

    async def execute(self, command: JoinChannelCommand) -> JoinChannelResult:
        """Command の user を channel へ参加させ、認可結果を返す.

        Args:
            command (JoinChannelCommand):
                user、channel name、ACL を判定する authorization を含む command.

        Returns:
            JoinChannelResult: すでに member、ACL が許可、または bypass privilege
            の場合は`joined=True`. channel
            不存在または READ permission 不足では`joined=False`.

        Notes:
            すでに member の request は idempotent に成功する. state store への追加は channel
            の存在と ACL 検証後だけ行う.
        """
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
