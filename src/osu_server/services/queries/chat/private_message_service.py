"""PrivateMessageService — PM 宛先解決とオンライン判定。

パケット構築・配信はトランスポート層の責務。本サービスは宛先ユーザーの
存在確認とオンライン状態を返し、呼び出し元が S2C パケットの構築と
PacketQueue への enqueue を行う。
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
    """Result of PM delivery attempt."""

    success: bool
    target_id: int | None
    is_online: bool


class PrivateMessageService:
    """PM 宛先解決とオンライン判定。

    UserRepository でユーザーの存在を確認し、SessionStore でオンライン状態を
    判定する。実際のパケット配信はトランスポート層が担当する。
    """

    _user_repo: UserQueryRepository
    _session_store: UserSessionLookup

    def __init__(
        self,
        *,
        user_repo: UserQueryRepository,
        session_store: UserSessionLookup,
    ) -> None:
        self._user_repo = user_repo
        self._session_store = session_store

    async def deliver_message(
        self,
        *,
        target_name: str,
    ) -> PMDeliveryResult:
        """PM 宛先を解決し、オンライン状態を判定する。

        Args:
            target_name: 宛先ユーザー名 (正規化前)。

        Returns:
            PMDeliveryResult:
            - ``success=False`` — ユーザーが存在しない
            - ``success=True, is_online=True`` — オンライン
            - ``success=True, is_online=False`` — オフライン
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
        """PM 宛先を解決する。

        Args:
            target_name: 宛先ユーザー名 (正規化前)。

        Returns:
            (exists, user_id, is_online) のタプル:
            - ``(False, None, False)`` — ユーザーが存在しない
            - ``(True, user_id, True)`` — ユーザーが存在しオンライン
            - ``(True, user_id, False)`` — ユーザーが存在するがオフライン
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
