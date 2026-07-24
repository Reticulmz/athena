"""performance completion signalのmemoryとValkey契約を検証する."""

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
    """発行済みmessageを検査できるpublisher test doubleの最小契約.

    Attributes:
        published_messages (list[PublishedMessage]): 順序を保って検査するpublish呼出履歴.
    """

    published_messages: list[PublishedMessage]


@dataclass(frozen=True, slots=True)
class PublishedMessage:
    """fake publisherが記録するpublish呼出の値.

    Attributes:
        message (str): publishされたJSON payload文字列.
        channel (str): messageの送信先channel名.
    """

    message: str
    channel: str


@dataclass(slots=True)
class SignalHarness:
    """実装差を隠してsignal testへ共通操作を提供するharness.

    Attributes:
        signal (PerformanceCompletionSignal): waitとnotifyを検証する実装.
        publisher (_Publisher | None): Valkey publish記録を検査するためのfake.
        ready (Callable[[], Awaitable[None]] | None): waiter購読完了を待つ操作.
    """

    signal: PerformanceCompletionSignal
    publisher: _Publisher | None = None
    ready: Callable[[], Awaitable[None]] | None = None


@dataclass(slots=True)
class FakeValkeyBroker:
    """channel別callbackを同期配送するin-memory pubsub broker.

    Attributes:
        subscribers (dict[str, list[_PubSubCallback]]): channelごとの登録callback.
    """

    subscribers: dict[str, list[_PubSubCallback]] = field(default_factory=dict)

    def subscribe(self, channel: str, callback: _PubSubCallback) -> None:
        """callbackをchannelへ登録する.

        Args:
            channel (str): callbackを受け取るpubsub channel.
            callback (_PubSubCallback): publish時に同期実行するcallback.

        Returns:
            None: callback登録だけを完了し値を返さない.
        """
        self.subscribers.setdefault(channel, []).append(callback)

    def unsubscribe(self, channel: str, callback: _PubSubCallback) -> None:
        """登録済みcallbackをchannelから除去する.

        Args:
            channel (str): callbackを除去するpubsub channel.
            callback (_PubSubCallback): 除去対象のcallback.

        Returns:
            None: 除去後に値を返さない.
        """
        callbacks = self.subscribers.get(channel)
        if callbacks is None:
            return
        callbacks[:] = [existing for existing in callbacks if existing is not callback]
        if not callbacks:
            del self.subscribers[channel]

    def publish(self, message: str, channel: str) -> int:
        """channelの全callbackへmessageを配送し配送数を返す.

        Args:
            message (str): subscriberへ渡すpayload文字列.
            channel (str): 配送先pubsub channel.

        Returns:
            int: 呼出したcallbackの件数.
        """
        callbacks = tuple(self.subscribers.get(channel, ()))
        for callback in callbacks:
            callback(PubSubMsg(message=message, channel=channel, pattern=None), None)
        return len(callbacks)


@dataclass(slots=True)
class FakeValkeyPublisher:
    """publish内容を記録してbrokerへ配送するasync publisher fake.

    Attributes:
        broker (FakeValkeyBroker): messageを配送するin-memory broker.
        published_messages (list[PublishedMessage]): 順序を保って記録したpublish呼出.
    """

    broker: FakeValkeyBroker
    published_messages: list[PublishedMessage] = field(default_factory=list)

    async def publish(self, message: str, channel: str) -> int:
        """発行内容を記録しbrokerのsubscriberへ配送する.

        Args:
            message (str): 記録して配送するpayload文字列.
            channel (str): 配送先pubsub channel.

        Returns:
            int: brokerが配送したsubscriber数.
        """
        self.published_messages.append(PublishedMessage(message=message, channel=channel))
        return self.broker.publish(message, channel)


@dataclass(slots=True)
class FakeValkeyPubSubClient:
    """subscribe lifecycleを観測できるValkey pubsub client fake.

    Attributes:
        broker (FakeValkeyBroker): callbackを登録するbroker.
        callback (_PubSubCallback): 受信messageを処理するcallback.
        subscribed (asyncio.Event): subscription完了を通知するevent.
        closed (bool): close済みかを示すflag.
        unsubscribed_channels (list[set[str] | None]): unsubscribe引数の呼出履歴.
        _channels (set[str]): このclientが現在購読するchannel集合.
    """

    broker: FakeValkeyBroker
    callback: _PubSubCallback
    subscribed: asyncio.Event
    closed: bool = False
    unsubscribed_channels: list[set[str] | None] = field(default_factory=list)
    _channels: set[str] = field(default_factory=set)

    async def subscribe(self, channels: set[str], timeout_ms: int = 0) -> None:
        """指定channelをbrokerへ登録し購読完了を通知する.

        Args:
            channels (set[str]): 購読するchannel集合.
            timeout_ms (int): API互換のtimeout値でfakeでは使用しない.

        Returns:
            None: 登録後に値を返さない.
        """
        _ = timeout_ms
        for channel in channels:
            self.broker.subscribe(channel, self.callback)
        self._channels.update(channels)
        self.subscribed.set()

    async def unsubscribe(self, channels: set[str] | None = None, timeout_ms: int = 0) -> None:
        """指定または全購読channelをbrokerから解除する.

        Args:
            channels (set[str] | None): 解除対象でNoneなら全登録channel.
            timeout_ms (int): API互換のtimeout値でfakeでは使用しない.

        Returns:
            None: 解除後に値を返さない.
        """
        _ = timeout_ms
        self.unsubscribed_channels.append(channels)
        selected = set(self._channels if channels is None else channels)
        for channel in selected:
            self.broker.unsubscribe(channel, self.callback)
        self._channels.difference_update(selected)

    async def close(self, err_message: str | None = None) -> None:
        """clientをclosed状態へ遷移させる.

        Args:
            err_message (str | None): API互換の終了理由でfakeでは使用しない.

        Returns:
            None: 状態更新後に値を返さない.
        """
        _ = err_message
        self.closed = True


@dataclass(slots=True)
class FakeValkeyHarnessBuilder:
    """Valkey signal用fake clientを構築し購読状態を共有するbuilder.

    Attributes:
        broker (FakeValkeyBroker): 構築clientが共有するbroker.
        subscribed (asyncio.Event): 最初のsubscribe完了を示すevent.
        clients (list[FakeValkeyPubSubClient]): 作成済みclientの順序付き履歴.
    """

    broker: FakeValkeyBroker = field(default_factory=FakeValkeyBroker)
    subscribed: asyncio.Event = field(default_factory=asyncio.Event)
    clients: list[FakeValkeyPubSubClient] = field(default_factory=list)

    async def create_client(self, callback: _PubSubCallback) -> FakeValkeyPubSubClient:
        """callback用pubsub clientを生成して履歴へ追加する.

        Args:
            callback (_PubSubCallback): 生成clientがbrokerへ登録する受信callback.

        Returns:
            FakeValkeyPubSubClient: lifecycleを観測できる新しいfake client.
        """
        client = FakeValkeyPubSubClient(self.broker, callback, self.subscribed)
        self.clients.append(client)
        return client

    async def wait_until_subscribed(self) -> None:
        """clientがsubscribeを完了するまで最大1秒待つ.

        Returns:
            None: 購読完了を確認して値を返さない.

        Raises:
            TimeoutError: 1秒以内に購読eventが設定されない場合.
        """
        _ = await asyncio.wait_for(self.subscribed.wait(), timeout=1.0)


async def _yield_to_waiter() -> None:
    """Memory waiter taskへevent loopの実行機会を一度譲る.

    Returns:
        None: schedulerへ制御を譲った後に値を返さない.
    """
    await asyncio.sleep(0)


def _memory_harness() -> SignalHarness:
    """waiter同期用yield操作を備えるmemory signal harnessを構築する.

    Returns:
        SignalHarness: memory実装を検証するharness.
    """
    return SignalHarness(
        signal=InMemoryPerformanceCompletionSignal(),
        ready=_yield_to_waiter,
    )


def _valkey_harness() -> SignalHarness:
    """Fake brokerとpublisherを備えるValkey signal harnessを構築する.

    Returns:
        SignalHarness: Valkey実装とpublish履歴を検証するharness.
    """
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
    """parameterized実装に対応したsignal harnessを各testへ提供する.

    Args:
        request (pytest.FixtureRequest): memoryまたはvalkeyのparameterを持つpytest request.

    Returns:
        SignalHarness: 選択実装のwaitとnotifyを呼べるharness.
    """
    param = cast("str", request.param)
    if param == "memory":
        return _memory_harness()
    return _valkey_harness()


def _terminal_payload() -> PerformanceCompletionSignalPayload:
    """Score 42のcompleted notification payloadを生成する.

    Returns:
        PerformanceCompletionSignalPayload: terminal stateを持つ検証用payload.
    """
    return PerformanceCompletionSignalPayload(
        score_id=42,
        calculation_id=7,
        state=PerformanceCalculationState.COMPLETED,
    )


async def _wait_until_ready(harness: SignalHarness) -> None:
    """harnessが提供するならwaiter購読完了まで待機する.

    Args:
        harness (SignalHarness): 任意のready操作を持つsignal harness.

    Returns:
        None: ready操作完了後に値を返さない.
    """
    if harness.ready is None:
        return
    await harness.ready()


async def test_wait_observes_notify_after_waiter_setup(signal_harness: SignalHarness) -> None:
    """waiterを準備後にterminal payloadを通知したときwaitがTrueで完了することを確認する.

    Args:
        signal_harness (SignalHarness): memoryまたはValkey実装を選んだsignal test harness.

    Returns:
        None: 検証を完了し値を返さない.
    """
    wait_task = asyncio.create_task(
        signal_harness.signal.wait(score_id=42, timeout=timedelta(seconds=1))
    )
    await _wait_until_ready(signal_harness)

    await signal_harness.signal.notify(_terminal_payload())

    assert await wait_task is True


async def test_wait_times_out_without_stored_lost_signal(signal_harness: SignalHarness) -> None:
    """waiter準備前の通知を保持しない実装で後続waitがtimeoutしFalseを返すことを確認する.

    Args:
        signal_harness (SignalHarness): memoryまたはValkey実装を選んだsignal test harness.

    Returns:
        None: 検証を完了し値を返さない.
    """
    await signal_harness.signal.notify(_terminal_payload())

    observed = await signal_harness.signal.wait(score_id=42, timeout=timedelta(milliseconds=20))

    assert observed is False


async def test_score_scope_isolated_between_waiters(signal_harness: SignalHarness) -> None:
    """Score 42だけを通知したとき同scoreのwaiterだけがTrueとなることを確認する.

    Args:
        signal_harness (SignalHarness): memoryまたはValkey実装を選んだsignal test harness.

    Returns:
        None: 検証を完了し値を返さない.
    """
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
    """Calculating stateでpayloadを生成したときterminal制約のValueErrorを送出することを確認する.

    Returns:
        None: 検証を完了し値を返さない.
    """
    with pytest.raises(ValueError, match="terminal"):
        _ = PerformanceCompletionSignalPayload(
            score_id=42,
            calculation_id=7,
            state=PerformanceCalculationState.CALCULATING,
        )


def test_channel_key_is_score_scoped_and_prefixable() -> None:
    """Score IDと任意prefixから一意なcompletion channel名を生成することを確認する.

    Returns:
        None: 検証を完了し値を返さない.
    """
    assert performance_completion_channel(score_id=42) == "performance_completion:42"
    assert performance_completion_channel(score_id=42, key_prefix="test:") == (
        "test:performance_completion:42"
    )


async def test_valkey_publish_payload_excludes_performance_values() -> None:
    """unavailable通知時にValkey payloadが識別子とstateだけを含むことを確認する.

    Returns:
        None: 検証を完了し値を返さない.
    """
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
    """Valkey waitがtimeoutしたときchannel解除とclient closeを必ず行うことを確認する.

    Returns:
        None: 検証を完了し値を返さない.
    """
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
