"""Polling workflow contracts and pipeline."""

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
    """Input for the Starlette-independent polling workflow."""

    token: str
    body: bytes


@dataclass(slots=True, frozen=True)
class PollingWorkflowResult:
    """Result returned by the Starlette-independent polling workflow."""

    content: bytes


class PollingWorkflow:
    """Execute the C2S dispatch and S2C drain pipeline without Starlette."""

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
        self._session_store = session_store
        self._packet_queue = packet_queue
        self._stable_user_status_store = stable_user_status_store
        self._c2s_actions = C2SActionExecutor(packet_dispatcher)
        self._session_ttl = session_ttl
        self._max_request_body_size = max_request_body_size

    async def execute(self, workflow_input: PollingWorkflowInput) -> PollingWorkflowResult:
        """Execute polling in the same order as the legacy endpoint path."""
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
