"""private message宛先の存在とonline stateをread-onlyに解決するserviceを定義する.

packet構築とdeliveryはtransport layerの責務である. このserviceは宛先userの存在とonline
stateだけを返しcallerがS2C packet構築とPacketQueueへのenqueueを行う.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

import structlog

from osu_server.domain.identity.users import User

if TYPE_CHECKING:
    from osu_server.repositories.interfaces.queries.users import UserQueryRepository
    from osu_server.repositories.interfaces.session_store import UserSessionLookup

logger: structlog.stdlib.BoundLogger = structlog.get_logger(__name__)  # pyright: ignore[reportAny]


@dataclass(slots=True)
class PMDeliveryResult:
    """private message宛先解決の結果を表す.

    Attributes:
        success (bool): 宛先userが存在しdelivery判定を完了したか.
        target_id (int | None): 解決した宛先user ID. 宛先不存在時はNone.
        is_online (bool): 解決した宛先userがonline sessionを持つか.
    """

    success: bool
    target_id: int | None
    is_online: bool


class PrivateMessageService:
    """private message宛先の存在とonline stateをread-onlyに解決する.

    Attributes:
        _user_repo (UserQueryRepository): normalized usernameからuserを読むrepository.
        _session_store (UserSessionLookup): userのonline sessionを読むstore.

    Notes:
        packet deliveryはtransport layerが担当しこのserviceはpacketを構築またはenqueueしない.
    """

    _user_repo: UserQueryRepository
    _session_store: UserSessionLookup

    def __init__(
        self,
        *,
        user_repo: UserQueryRepository,
        session_store: UserSessionLookup,
    ) -> None:
        """Private message宛先解決に使うrepositoryとsession storeを保持する.

        Args:
            user_repo (UserQueryRepository): normalized usernameからuserを読むrepository.
            session_store (UserSessionLookup): userのonline sessionを読むstore.
        """
        self._user_repo = user_repo
        self._session_store = session_store

    async def deliver_message(
        self,
        *,
        target_name: str,
    ) -> PMDeliveryResult:
        """Private message宛先を解決してonline stateを判定する.

        Args:
            target_name (str): 正規化前の宛先user名.

        Returns:
            PMDeliveryResult: 宛先不存在または解決済みuser IDとonline stateを持つ結果.
        """
        safe_username = User.normalize_username(target_name)
        user = await self._user_repo.get_by_safe_username(safe_username)

        if user is None:
            logger.warning(
                "pm_target_not_found",
                target_name=target_name,
                safe_username=safe_username,
            )
            return PMDeliveryResult(success=False, target_id=None, is_online=False)

        session = await self._session_store.get_by_user(user.id)
        is_online = session is not None

        logger.info(
            "pm_target_resolved",
            target_name=target_name,
            target_user_id=user.id,
            is_online=is_online,
        )
        return PMDeliveryResult(success=True, target_id=user.id, is_online=is_online)

    async def resolve_target(
        self,
        target_name: str,
    ) -> tuple[bool, int | None, bool]:
        """Private message宛先をlegacy tuple形式で解決する.

        Args:
            target_name (str): 正規化前の宛先user名.

        Returns:
            tuple[bool, int | None, bool]: 宛先の存在とuser IDとonline stateの順のtuple.
        """
        safe_username = User.normalize_username(target_name)
        user = await self._user_repo.get_by_safe_username(safe_username)

        if user is None:
            logger.warning(
                "pm_target_not_found",
                target_name=target_name,
                safe_username=safe_username,
            )
            return (False, None, False)

        session = await self._session_store.get_by_user(user.id)
        is_online = session is not None

        logger.info(
            "pm_target_resolved",
            target_name=target_name,
            target_user_id=user.id,
            is_online=is_online,
        )
        return (True, user.id, is_online)
