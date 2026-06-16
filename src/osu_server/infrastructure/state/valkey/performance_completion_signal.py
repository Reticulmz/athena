"""Valkey-backed performance completion signal."""

from __future__ import annotations

import asyncio
import json
from collections.abc import Awaitable, Callable
from typing import TYPE_CHECKING, Protocol, runtime_checkable

from glide_shared.commands.core_options import PubSubMsg

from osu_server.infrastructure.state.interfaces.performance_completion_signal import (
    PerformanceCompletionSignalPayload,
    performance_completion_channel,
    validate_performance_completion_timeout,
)

if TYPE_CHECKING:
    from datetime import timedelta

type ValkeyPubSubCallback = Callable[[PubSubMsg, object], None]


@runtime_checkable
class ValkeyPerformanceCompletionPublisher(Protocol):
    async def publish(self, message: str, channel: str) -> int: ...


class _ValkeyPerformanceCompletionSubscriber(Protocol):
    async def subscribe(self, channels: set[str], timeout_ms: int = 0) -> None: ...

    async def unsubscribe(
        self,
        channels: set[str] | None = None,
        timeout_ms: int = 0,
    ) -> None: ...

    async def close(self, err_message: str | None = None) -> None: ...


type ValkeyPubSubClientFactory = Callable[
    [ValkeyPubSubCallback],
    Awaitable[_ValkeyPerformanceCompletionSubscriber],
]


class ValkeyPerformanceCompletionSignal:
    """Performance completion signal delivered through Valkey Pub/Sub."""

    def __init__(
        self,
        publisher: ValkeyPerformanceCompletionPublisher,
        *,
        pubsub_client_factory: ValkeyPubSubClientFactory,
        key_prefix: str = "",
        subscription_timeout_ms: int = 5_000,
    ) -> None:
        self._publisher: ValkeyPerformanceCompletionPublisher = publisher
        self._pubsub_client_factory: ValkeyPubSubClientFactory = pubsub_client_factory
        self._key_prefix: str = key_prefix
        self._subscription_timeout_ms: int = subscription_timeout_ms

    async def notify(self, payload: PerformanceCompletionSignalPayload) -> None:
        """Publish a score-scoped wake-up payload without performance values."""
        channel = performance_completion_channel(
            payload.score_id,
            key_prefix=self._key_prefix,
        )
        _ = await self._publisher.publish(_encode_payload(payload), channel)

    async def wait(self, score_id: int, timeout: timedelta) -> bool:
        """Subscribe to the score channel and return whether a signal arrived."""
        validate_performance_completion_timeout(timeout)
        channel = performance_completion_channel(score_id, key_prefix=self._key_prefix)
        loop = asyncio.get_running_loop()
        signal_received = asyncio.Event()

        def callback(message: PubSubMsg, context: object) -> None:
            _ = context
            if _decode_text(message.channel) == channel:
                _ = loop.call_soon_threadsafe(signal_received.set)

        client = await self._pubsub_client_factory(callback)
        try:
            await client.subscribe({channel}, timeout_ms=self._subscription_timeout_ms)
            try:
                _ = await asyncio.wait_for(
                    signal_received.wait(),
                    timeout=timeout.total_seconds(),
                )
            except TimeoutError:
                return False
            return True
        finally:
            try:
                await client.unsubscribe({channel}, timeout_ms=self._subscription_timeout_ms)
            finally:
                await client.close()


def _encode_payload(payload: PerformanceCompletionSignalPayload) -> str:
    data = {
        "calculation_id": payload.calculation_id,
        "score_id": payload.score_id,
        "state": payload.state.value,
    }
    return json.dumps(data, separators=(",", ":"), sort_keys=True)


def _decode_text(value: object) -> str | None:
    if isinstance(value, bytes):
        return value.decode("utf-8")
    if isinstance(value, str):
        return value
    return None
