"""Stable Bancho polling request の C2S dispatch と S2C drain を実行する."""

from __future__ import annotations

import time
from dataclasses import dataclass
from typing import TYPE_CHECKING, cast

import structlog

from osu_server.domain.identity.authentication import LoginResult
from osu_server.transports.stable.bancho.protocol.s2c.login import login_reply
from osu_server.transports.stable.bancho.workflows.c2s_actions import C2SActionExecutor

if TYPE_CHECKING:
    from osu_server.infrastructure.state.interfaces.packet_queue import PacketQueue
    from osu_server.infrastructure.state.interfaces.stable_user_status_store import (
        StableUserStatusStore,
    )
    from osu_server.repositories.interfaces.session_store import PollingSessionRuntime
    from osu_server.transports.stable.bancho.dispatch import PacketDispatcher

logger = cast("structlog.stdlib.BoundLogger", structlog.get_logger(__name__))


@dataclass(slots=True, frozen=True)
class PollingWorkflowInput:
    """Starlette に依存しない polling workflow の入力を表す.

    Attributes:
        token (str): osu-token header から取得した session token.
        body (bytes): client が送った C2S packet stream.
    """

    token: str
    body: bytes


@dataclass(slots=True, frozen=True)
class PollingWorkflowResult:
    """Starlette に依存しない polling workflow の response を表す.

    Attributes:
        content (bytes): client へ返す S2C packet stream.
    """

    content: bytes


class PollingWorkflow:
    """Starlette 非依存で C2S dispatch と S2C queue drain を実行する.

    Attributes:
        _session_store (PollingSessionRuntime): session を取得して TTL を更新する store.
        _packet_queue (PacketQueue): user ごとの S2C packet を drain して TTL を更新する queue.
        _stable_user_status_store (StableUserStatusStore | None): optional status TTL store.
        _c2s_actions (C2SActionExecutor): raw C2S packet stream を dispatch する executor.
        _session_ttl (int): session と queue に設定する TTL 秒数.
        _max_request_body_size (int): C2S body として受け入れる最大 bytes 数.
    """

    _session_store: PollingSessionRuntime
    _packet_queue: PacketQueue
    _stable_user_status_store: StableUserStatusStore | None
    _c2s_actions: C2SActionExecutor
    _session_ttl: int
    _max_request_body_size: int

    def __init__(
        self,
        *,
        session_store: PollingSessionRuntime,
        packet_queue: PacketQueue,
        packet_dispatcher: PacketDispatcher,
        stable_user_status_store: StableUserStatusStore | None = None,
        session_ttl: int = 300,
        max_request_body_size: int = 1_048_576,
    ) -> None:
        """Polling pipeline の state dependency と request limit を設定する.

        Args:
            session_store (PollingSessionRuntime): token から user session を取得する store.
            packet_queue (PacketQueue): user ごとの outbound packet queue.
            packet_dispatcher (PacketDispatcher): inbound C2S packet を dispatch する registry.
            stable_user_status_store (StableUserStatusStore | None): optional status TTL store.
            session_ttl (int): session, queue, status に適用する TTL 秒数.
            max_request_body_size (int): 処理する C2S request body の最大 bytes 数.
        """
        self._session_store = session_store
        self._packet_queue = packet_queue
        self._stable_user_status_store = stable_user_status_store
        self._c2s_actions = C2SActionExecutor(packet_dispatcher)
        self._session_ttl = session_ttl
        self._max_request_body_size = max_request_body_size

    async def execute(self, workflow_input: PollingWorkflowInput) -> PollingWorkflowResult:
        """Legacy endpoint と同じ順序で polling request を実行する.

        Args:
            workflow_input (PollingWorkflowInput): token と C2S request body を持つ polling 入力.

        Returns:
            PollingWorkflowResult: auth failure, empty response, または S2C bytes.

        Notes:
            oversized body は session lookup 前に空 response で拒否する.
            無効 token は authentication failed packet を返す.
            valid session では TTL refresh 後に C2S dispatch と S2C queue drain を行う.
        """
        start = time.monotonic()
        body = workflow_input.body

        if len(body) > self._max_request_body_size:
            logger.warning(
                "polling_body_too_large",
                size=len(body),
                limit=self._max_request_body_size,
            )
            return PollingWorkflowResult(content=b"")

        session = await self._session_store.get(workflow_input.token)
        if session is None:
            return PollingWorkflowResult(content=login_reply(LoginResult.AUTHENTICATION_FAILED))

        user_id = session.user_id
        _ = await self._session_store.refresh(workflow_input.token)
        await self._packet_queue.refresh_ttl(user_id, self._session_ttl)
        if self._stable_user_status_store is not None:
            await self._stable_user_status_store.refresh_ttl(user_id, self._session_ttl)

        c2s_result = await self._c2s_actions.execute(body=body, user_id=user_id)

        response_data = await self._packet_queue.dequeue_all(user_id)
        await self._packet_queue.refresh_ttl(user_id, self._session_ttl)
        if self._stable_user_status_store is not None:
            await self._stable_user_status_store.refresh_ttl(user_id, self._session_ttl)

        elapsed_ms = (time.monotonic() - start) * 1000
        logger.info(
            "polling_complete",
            c2s_count=c2s_result.packet_count,
            s2c_bytes=len(response_data),
            elapsed_ms=round(elapsed_ms, 2),
        )

        return PollingWorkflowResult(content=response_data)


__all__ = [
    "PollingWorkflow",
    "PollingWorkflowInput",
    "PollingWorkflowResult",
]
