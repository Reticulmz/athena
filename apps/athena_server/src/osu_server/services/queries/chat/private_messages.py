"""private message宛先の存在とonline stateを読むquery use-caseを定義する."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

import structlog

from osu_server.domain.identity.users import User

if TYPE_CHECKING:
    from osu_server.repositories.interfaces.queries.users import UserQueryRepository
    from osu_server.repositories.interfaces.session_store import UserSessionLookup

logger: structlog.stdlib.BoundLogger = structlog.get_logger(__name__)  # pyright: ignore[reportAny]


@dataclass(frozen=True, slots=True)
class ResolvePrivateMessageTargetQueryInput:
    """private message宛先を解決するread-only入力を表す.

    Attributes:
        target_name (str): 正規化前の宛先user名.
    """

    target_name: str


@dataclass(frozen=True, slots=True)
class ResolvePrivateMessageTargetQueryResult:
    """private message宛先を解決したread-only結果を表す.

    Attributes:
        exists (bool): 宛先userが存在するか.
        target_id (int | None): 宛先user ID. 宛先不存在時はNone.
        is_online (bool): 宛先userがonline sessionを持つか.
    """

    exists: bool
    target_id: int | None
    is_online: bool


class ResolvePrivateMessageTargetQuery:
    """private message宛先とcurrent online stateをmutationなしで解決する.

    Attributes:
        _user_repository (UserQueryRepository): normalized usernameからuserを読むrepository.
        _session_store (UserSessionLookup): userのonline sessionを読むstore.
    """

    def __init__(
        self,
        *,
        user_repository: UserQueryRepository,
        session_store: UserSessionLookup,
    ) -> None:
        """Private message宛先queryに使うrepositoryとsession storeを保持する.

        Args:
            user_repository (UserQueryRepository): normalized usernameからuserを読むrepository.
            session_store (UserSessionLookup): userのonline sessionを読むstore.
        """
        self._user_repository: UserQueryRepository = user_repository
        self._session_store: UserSessionLookup = session_store

    async def execute(
        self,
        input_data: ResolvePrivateMessageTargetQueryInput,
    ) -> ResolvePrivateMessageTargetQueryResult:
        """宛先名を正規化してuserの存在とonline stateを解決する.

        Args:
            input_data (ResolvePrivateMessageTargetQueryInput): 正規化前の宛先user名を持つ入力.

        Returns:
            ResolvePrivateMessageTargetQueryResult: 宛先の存在とuser IDとonline stateを持つ結果.
        """
        safe_username = User.normalize_username(input_data.target_name)
        user = await self._user_repository.get_by_safe_username(safe_username)

        if user is None:
            logger.warning(
                "pm_target_not_found",
                target_name=input_data.target_name,
                safe_username=safe_username,
            )
            return ResolvePrivateMessageTargetQueryResult(
                exists=False,
                target_id=None,
                is_online=False,
            )

        session = await self._session_store.get_by_user(user.id)
        is_online = session is not None
        logger.info(
            "pm_target_resolved",
            target_name=input_data.target_name,
            target_user_id=user.id,
            is_online=is_online,
        )
        return ResolvePrivateMessageTargetQueryResult(
            exists=True,
            target_id=user.id,
            is_online=is_online,
        )
