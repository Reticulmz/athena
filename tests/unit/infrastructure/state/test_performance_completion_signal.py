"""Contract tests for performance completion signals."""

from __future__ import annotations

import asyncio
import json
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from datetime import timedelta
from typing import Protocol, cast

import pytest
from glide_shared.commands.core_options import PubSubMsg

from osu_server.domain.scores.performance import PerformanceCalculationState
from osu_server.infrastructure.state.interfaces.performance_completion_signal import (
    PerformanceCompletionSignal,
    PerformanceCompletionSignalPayload,
    performance_completion_channel,
)
from osu_server.infrastructure.state.memory.performance_completion_signal import (
    InMemoryPerformanceCompletionSignal,
)
from osu_server.infrastructure.state.valkey.performance_completion_signal import (
    ValkeyPerformanceCompletionSignal,
)

type _PubSubCallback = Callable[[PubSubMsg, object], None]


class _Publisher(Protocol):
    published_messages: list[PublishedMessage]


@dataclass(frozen=True, slots=True)
class PublishedMessage:
    message: str
    channel: str


@dataclass(slots=True)
class SignalHarness:
    signal: PerformanceCompletionSignal
    publisher: _Publisher | None = None
    ready: Callable[[], Awaitable[None]] | None = None


@dataclass(slots=True)
class FakeValkeyBroker:
    subscribers: dict[str, list[_PubSubCallback]] = field(default_factory=dict)

    def subscribe(self, channel: str, callback: _PubSubCallback) -> None:
        self.subscribers.setdefault(channel, []).append(callback)

    def unsubscribe(self, channel: str, callback: _PubSubCallback) -> None:
        callbacks = self.subscribers.get(channel)
        if callbacks is None:
            return
        callbacks[:] = [existing for existing in callbacks if existing is not callback]
        if not callbacks:
            del self.subscribers[channel]

    def publish(self, message: str, channel: str) -> int:
        callbacks = tuple(self.subscribers.get(channel, ()))
        for callback in callbacks:
            callback(PubSubMsg(message=message, channel=channel, pattern=None), None)
        return len(callbacks)


@dataclass(slots=True)
class FakeValkeyPublisher:
    broker: FakeValkeyBroker
    published_messages: list[PublishedMessage] = field(default_factory=list)

    async def publish(self, message: str, channel: str) -> int:
        self.published_messages.append(PublishedMessage(message=message, channel=channel))
        return self.broker.publish(message, channel)


@dataclass(slots=True)
class FakeValkeyPubSubClient:
    broker: FakeValkeyBroker
    callback: _PubSubCallback
    subscribed: asyncio.Event
    closed: bool = False
    unsubscribed_channels: list[set[str] | None] = field(default_factory=list)
    _channels: set[str] = field(default_factory=set)

    async def subscribe(self, channels: set[str], timeout_ms: int = 0) -> None:
        _ = timeout_ms
        for channel in channels:
            self.broker.subscribe(channel, self.callback)
        self._channels.update(channels)
        self.subscribed.set()

    async def unsubscribe(self, channels: set[str] | None = None, timeout_ms: int = 0) -> None:
        _ = timeout_ms
        self.unsubscribed_channels.append(channels)
        selected = set(self._channels if channels is None else channels)
        for channel in selected:
            self.broker.unsubscribe(channel, self.callback)
        self._channels.difference_update(selected)

    async def close(self, err_message: str | None = None) -> None:
        _ = err_message
        self.closed = True


@dataclass(slots=True)
class FakeValkeyHarnessBuilder:
    broker: FakeValkeyBroker = field(default_factory=FakeValkeyBroker)
    subscribed: asyncio.Event = field(default_factory=asyncio.Event)
    clients: list[FakeValkeyPubSubClient] = field(default_factory=list)

    async def create_client(self, callback: _PubSubCallback) -> FakeValkeyPubSubClient:
        client = FakeValkeyPubSubClient(self.broker, callback, self.subscribed)
        self.clients.append(client)
        return client

    async def wait_until_subscribed(self) -> None:
        _ = await asyncio.wait_for(self.subscribed.wait(), timeout=1.0)


async def _yield_to_waiter() -> None:
    await asyncio.sleep(0)


def _memory_harness() -> SignalHarness:
    return SignalHarness(
        signal=InMemoryPerformanceCompletionSignal(),
        ready=_yield_to_waiter,
    )


def _valkey_harness() -> SignalHarness:
    builder = FakeValkeyHarnessBuilder()
    publisher = FakeValkeyPublisher(builder.broker)
    signal = ValkeyPerformanceCompletionSignal(
        publisher,
        pubsub_client_factory=builder.create_client,
        key_prefix="test:",
    )
    return SignalHarness(
        signal=signal,
        publisher=publisher,
        ready=builder.wait_until_subscribed,
    )


@pytest.fixture(params=("memory", "valkey"))
def signal_harness(request: pytest.FixtureRequest) -> SignalHarness:
    param = cast("str", request.param)
    if param == "memory":
        return _memory_harness()
    return _valkey_harness()


def _terminal_payload() -> PerformanceCompletionSignalPayload:
    return PerformanceCompletionSignalPayload(
        score_id=42,
        calculation_id=7,
        state=PerformanceCalculationState.COMPLETED,
    )


async def _wait_until_ready(harness: SignalHarness) -> None:
    if harness.ready is None:
        return
    await harness.ready()


async def test_wait_observes_notify_after_waiter_setup(signal_harness: SignalHarness) -> None:
    wait_task = asyncio.create_task(
        signal_harness.signal.wait(score_id=42, timeout=timedelta(seconds=1))
    )
    await _wait_until_ready(signal_harness)

    await signal_harness.signal.notify(_terminal_payload())

    assert await wait_task is True


async def test_wait_times_out_without_stored_lost_signal(signal_harness: SignalHarness) -> None:
    await signal_harness.signal.notify(_terminal_payload())

    observed = await signal_harness.signal.wait(score_id=42, timeout=timedelta(milliseconds=20))

    assert observed is False


async def test_score_scope_isolated_between_waiters(signal_harness: SignalHarness) -> None:
    target_wait = asyncio.create_task(
        signal_harness.signal.wait(score_id=42, timeout=timedelta(seconds=1))
    )
    other_wait = asyncio.create_task(
        signal_harness.signal.wait(score_id=43, timeout=timedelta(milliseconds=20))
    )
    await _wait_until_ready(signal_harness)

    await signal_harness.signal.notify(_terminal_payload())

    assert await target_wait is True
    assert await other_wait is False


def test_payload_rejects_non_terminal_state() -> None:
    with pytest.raises(ValueError, match="terminal"):
        _ = PerformanceCompletionSignalPayload(
            score_id=42,
            calculation_id=7,
            state=PerformanceCalculationState.CALCULATING,
        )


def test_channel_key_is_score_scoped_and_prefixable() -> None:
    assert performance_completion_channel(score_id=42) == "performance_completion:42"
    assert performance_completion_channel(score_id=42, key_prefix="test:") == (
        "test:performance_completion:42"
    )


async def test_valkey_publish_payload_excludes_performance_values() -> None:
    harness = _valkey_harness()

    await harness.signal.notify(
        PerformanceCompletionSignalPayload(
            score_id=42,
            calculation_id=7,
            state=PerformanceCalculationState.UNAVAILABLE,
        )
    )

    assert harness.publisher is not None
    [published] = harness.publisher.published_messages
    assert published.channel == "test:performance_completion:42"
    raw_payload = cast("dict[str, object]", json.loads(published.message))
    assert raw_payload == {
        "score_id": 42,
        "calculation_id": 7,
        "state": "unavailable",
    }
    assert "pp" not in raw_payload
    assert "star_rating" not in raw_payload
    assert "diagnostics" not in raw_payload


async def test_valkey_wait_unsubscribes_and_closes_after_timeout() -> None:
    builder = FakeValkeyHarnessBuilder()
    publisher = FakeValkeyPublisher(builder.broker)
    signal = ValkeyPerformanceCompletionSignal(
        publisher,
        pubsub_client_factory=builder.create_client,
        key_prefix="test:",
    )

    observed = await signal.wait(score_id=42, timeout=timedelta(milliseconds=20))

    assert observed is False
    [client] = builder.clients
    assert client.unsubscribed_channels == [{"test:performance_completion:42"}]
    assert client.closed is True
    assert builder.broker.subscribers == {}
