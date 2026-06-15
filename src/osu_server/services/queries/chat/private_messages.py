"""Chat private-message query use-cases."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

import structlog

from osu_server.domain.identity.users import User

if TYPE_CHECKING:
    from osu_server.repositories.interfaces.queries.users import UserQueryRepository
    from osu_server.repositories.interfaces.session_store import SessionStore

logger: structlog.stdlib.BoundLogger = structlog.get_logger(__name__)  # pyright: ignore[reportAny]


@dataclass(frozen=True, slots=True)
class ResolvePrivateMessageTargetQueryInput:
    """Private-message target lookup input."""

    target_name: str


@dataclass(frozen=True, slots=True)
class ResolvePrivateMessageTargetQueryResult:
    """Private-message target lookup result."""

    exists: bool
    target_id: int | None
    is_online: bool


class ResolvePrivateMessageTargetQuery:
    """Resolve a PM target and current online state without mutation."""

    def __init__(
        self,
        *,
        user_repository: UserQueryRepository,
        session_store: SessionStore,
    ) -> None:
        self._user_repository: UserQueryRepository = user_repository
        self._session_store: SessionStore = session_store

    async def execute(
        self,
        input_data: ResolvePrivateMessageTargetQueryInput,
    ) -> ResolvePrivateMessageTargetQueryResult:
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
