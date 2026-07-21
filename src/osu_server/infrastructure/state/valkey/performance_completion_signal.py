"""Valkey Pub/Sub を使う performance completion signal を提供する module."""

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
    """Performance completion payload を Valkey channel へ publish する contract.

    Notes:
        実装は publish 済み payload を durable result として扱わない.
    """

    async def publish(self, message: str, channel: str) -> int:
        """文字列 payload を指定 channel へ publish し、受信者数を返す.

        Args:
            message (str): publish する serialised payload.
            channel (str): 宛先の Valkey Pub/Sub channel 名.

        Returns:
            int: publish を受信した subscriber 数.
        """
        ...


class _ValkeyPerformanceCompletionSubscriber(Protocol):
    """Score-scoped completion channel を購読する private Pub/Sub client contract.

    Notes:
        wait ごとに生成され、終了時には unsubscribe と close を受ける.
    """

    async def subscribe(self, channels: set[str], timeout_ms: int = 0) -> None:
        """指定した channel 群の購読を開始する.

        Args:
            channels (set[str]): 購読する Valkey Pub/Sub channel 名.
            timeout_ms (int): 購読応答を待つ最大ミリ秒数。0 は client default を表す.

        Returns:
            None: 購読開始処理の完了を表す.
        """
        ...

    async def unsubscribe(
        self,
        channels: set[str] | None = None,
        timeout_ms: int = 0,
    ) -> None:
        """指定した channel 群、または全購読を解除する.

        Args:
            channels (set[str] | None): 解除する channel 名。None の場合は全購読を解除する.
            timeout_ms (int): 解除応答を待つ最大ミリ秒数。0 は client default を表す.

        Returns:
            None: 購読解除処理の完了を表す.
        """
        ...

    async def close(self, err_message: str | None = None) -> None:
        """Pub/Sub client を close する.

        Args:
            err_message (str | None): close reason として client に渡す任意の error message.

        Returns:
            None: client close 処理の完了を表す.
        """
        ...


type ValkeyPubSubClientFactory = Callable[
    [ValkeyPubSubCallback],
    Awaitable[_ValkeyPerformanceCompletionSubscriber],
]


class ValkeyPerformanceCompletionSignal:
    """Performance completion signal を Valkey Pub/Sub で配信する実装.

    Attributes:
        _publisher (ValkeyPerformanceCompletionPublisher): payload を publish する client.
        _pubsub_client_factory (ValkeyPubSubClientFactory): wait 専用 subscriber を生成する
            factory.
        _key_prefix (str): channel 名前空間を分離する prefix.
        _subscription_timeout_ms (int): subscribe と unsubscribe の client timeout ミリ秒数.

    Notes:
        channel は `{key_prefix}performance_completion:{score_id}` の score-scoped name を使う.
        payload は wake-up hint であり、受信側は durable calculation result を再照会する.
    """

    def __init__(
        self,
        publisher: ValkeyPerformanceCompletionPublisher,
        *,
        pubsub_client_factory: ValkeyPubSubClientFactory,
        key_prefix: str = "",
        subscription_timeout_ms: int = 5_000,
    ) -> None:
        """Publisher と subscriber factory を持つ signal adapter を初期化する.

        Args:
            publisher (ValkeyPerformanceCompletionPublisher): payload を publish する Valkey
                adapter.
            pubsub_client_factory (ValkeyPubSubClientFactory): callback から subscriber を生成する
                factory.
            key_prefix (str): channel 名前空間を分離する任意の prefix.
            subscription_timeout_ms (int): subscribe と unsubscribe に使う timeout ミリ秒数.

        Returns:
            None: signal adapter instance を初期化したことを表す.
        """
        self._publisher: ValkeyPerformanceCompletionPublisher = publisher
        self._pubsub_client_factory: ValkeyPubSubClientFactory = pubsub_client_factory
        self._key_prefix: str = key_prefix
        self._subscription_timeout_ms: int = subscription_timeout_ms

    async def notify(self, payload: PerformanceCompletionSignalPayload) -> None:
        """Score-scoped wake-up payload を Valkey channel へ publish する.

        Args:
            payload (PerformanceCompletionSignalPayload): 終端 calculation を識別する payload.

        Returns:
            None: publish 処理の完了を表す.

        Notes:
            calculation result の performance value は payload に含めない.
        """
        channel = performance_completion_channel(
            payload.score_id,
            key_prefix=self._key_prefix,
        )
        _ = await self._publisher.publish(_encode_payload(payload), channel)

    async def wait(self, score_id: int, timeout: timedelta) -> bool:
        """Score channel を購読して通知を期限まで待ち、観測結果を返す.

        Args:
            score_id (int): 待機対象となる正の score id.
            timeout (timedelta): 正である最大待機時間.

        Returns:
            bool: 対象 score の通知を観測した場合は True、期限切れなら False.

        Raises:
            ValueError: score_id が正でない場合、または timeout が正でない場合.

        Notes:
            成功、timeout、subscription error のいずれでも unsubscribe と close を試行する.
        """
        validate_performance_completion_timeout(timeout)
        channel = performance_completion_channel(score_id, key_prefix=self._key_prefix)
        loop = asyncio.get_running_loop()
        signal_received = asyncio.Event()

        def callback(message: PubSubMsg, context: object) -> None:
            """受信 message が対象 channel の場合に待機 event を set する.

            Args:
                message (PubSubMsg): Pub/Sub client から受け取った message.
                context (object): client が渡す callback context。adapter では使用しない.

            Returns:
                None: event scheduling 処理の完了を表す.

            Notes:
                別 channel の message は無視し、event loop thread へ安全に通知する.
            """
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
    """Completion payload を channel publish 用の compact JSON へ変換する.

    Args:
        payload (PerformanceCompletionSignalPayload): serialise する終端 calculation payload.

    Returns:
        str: calculation_id、score_id、state を持つ key sorted JSON string.
    """
    data = {
        "calculation_id": payload.calculation_id,
        "score_id": payload.score_id,
        "state": payload.state.value,
    }
    return json.dumps(data, separators=(",", ":"), sort_keys=True)


def _decode_text(value: object) -> str | None:
    """Valkey callback value を channel 比較用の text へ正規化する.

    Args:
        value (object): str、bytes、またはそれ以外の callback value.

    Returns:
        str | None: str はそのまま、bytes は UTF-8 decoded text、それ以外は None.

    Raises:
        UnicodeDecodeError: bytes value が UTF-8 として decode できない場合.
    """
    if isinstance(value, bytes):
        return value.decode("utf-8")
    if isinstance(value, str):
        return value
    return None
