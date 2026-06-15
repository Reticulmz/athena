"""Polling workflow contracts and pipeline."""

from __future__ import annotations

import time
from dataclasses import dataclass
from typing import TYPE_CHECKING

import structlog

from osu_server.domain.identity.authentication import LoginResult
from osu_server.transports.stable.bancho.protocol.errors import PacketReadError
from osu_server.transports.stable.bancho.protocol.reader import read_packets
from osu_server.transports.stable.bancho.protocol.s2c.login import login_reply

if TYPE_CHECKING:
    from osu_server.infrastructure.state.interfaces.packet_queue import PacketQueue
    from osu_server.repositories.interfaces.session_store import SessionStore
    from osu_server.transports.stable.bancho.dispatch import PacketDispatcher

logger: structlog.stdlib.BoundLogger = structlog.get_logger(__name__)  # pyright: ignore[reportAny]


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

    _session_store: SessionStore
    _packet_queue: PacketQueue
    _packet_dispatcher: PacketDispatcher
    _session_ttl: int
    _max_request_body_size: int

    def __init__(
        self,
        *,
        session_store: SessionStore,
        packet_queue: PacketQueue,
        packet_dispatcher: PacketDispatcher,
        session_ttl: int = 300,
        max_request_body_size: int = 1_048_576,
    ) -> None:
        self._session_store = session_store
        self._packet_queue = packet_queue
        self._packet_dispatcher = packet_dispatcher
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

        c2s_count = 0
        if body:
            try:
                packets = read_packets(body)
            except PacketReadError:
                logger.error("c2s_parse_error", exc_info=True)
                packets = []

            for packet_id, payload in packets:
                c2s_count += 1
                try:
                    await self._packet_dispatcher.dispatch(packet_id, payload, user_id)
                except Exception:
                    logger.error(
                        "c2s_handler_error",
                        packet=packet_id.name,
                        payload_size=len(payload),
                        exc_info=True,
                    )

        response_data = await self._packet_queue.dequeue_all(user_id)
        await self._packet_queue.refresh_ttl(user_id, self._session_ttl)

        elapsed_ms = (time.monotonic() - start) * 1000
        logger.info(
            "polling_complete",
            c2s_count=c2s_count,
            s2c_bytes=len(response_data),
            elapsed_ms=round(elapsed_ms, 2),
        )

        return PollingWorkflowResult(content=response_data)


__all__ = [
    "PollingWorkflow",
    "PollingWorkflowInput",
    "PollingWorkflowResult",
]
