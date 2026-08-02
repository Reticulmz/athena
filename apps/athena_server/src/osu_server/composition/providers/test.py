"""test専用のDishka provider replacement helperを提供する."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, TypeVar, final

from dishka import Provider, Scope
from taskiq import AsyncBroker, InMemoryBroker

from osu_server.composition.providers.repository_adapters import (
    InMemoryRepositoryAdapterFamily,
)
from osu_server.domain.beatmaps import BeatmapMetadataProvider
from osu_server.infrastructure.beatmaps import InMemoryBeatmapMetadataProvider
from osu_server.infrastructure.security.hibp import HIBPClient
from osu_server.infrastructure.state.interfaces.channel_state_store import ChannelStateStore
from osu_server.infrastructure.state.interfaces.packet_queue import PacketQueue
from osu_server.infrastructure.state.interfaces.performance_completion_signal import (
    PerformanceCompletionSignal,
)
from osu_server.infrastructure.state.interfaces.rate_limiter import RateLimiter
from osu_server.infrastructure.state.interfaces.replay_download_accounting_gate import (
    ReplayDownloadAccountingGate,
)
from osu_server.infrastructure.state.interfaces.stable_user_status_store import (
    StableUserStatusStore,
)
from osu_server.infrastructure.state.memory.channel_state_store import InMemoryChannelStateStore
from osu_server.infrastructure.state.memory.packet_queue import InMemoryPacketQueue
from osu_server.infrastructure.state.memory.performance_completion_signal import (
    InMemoryPerformanceCompletionSignal,
)
from osu_server.infrastructure.state.memory.rate_limiter import InMemoryRateLimiter
from osu_server.infrastructure.state.memory.replay_download_accounting_gate import (
    InMemoryReplayDownloadAccountingGate,
)
from osu_server.infrastructure.state.memory.stable_user_status_store import (
    InMemoryStableUserStatusStore,
)
from osu_server.infrastructure.storage.interfaces import BlobStorageBackend
from osu_server.infrastructure.storage.local import LocalBlobStorageBackend
from osu_server.jobs import register_all_jobs
from osu_server.repositories.interfaces.session_store import SessionStore
from osu_server.repositories.memory.session_store import InMemorySessionStore

if TYPE_CHECKING:
    from collections.abc import Callable
    from pathlib import Path

T_co = TypeVar("T_co", covariant=True)


@dataclass(frozen=True, slots=True)
class ProviderReplacement[T_co]:
    """一つのtest provider replacementを型付きで表す.

    Attributes:
        provides (type[T_co]): override対象としてDishkaへ公開するdependency型.
        factory (Callable[[], T_co]): replacement instanceを返す引数なしfactory.
        scope (Scope): replacementをcacheするDishka scope.
    """

    provides: type[T_co]
    factory: Callable[[], T_co]
    scope: Scope = Scope.APP


@final
class TestProviderSet(Provider):
    """testでruntime providerを明示的にoverrideするprovider setを表す.

    Attributes:
        __test__ (bool): pytestがこのsupport classをtest classとして収集しないためのflag.
    """

    __test__: bool = False

    def __init__(self, *replacements: ProviderReplacement[object]) -> None:
        """指定されたreplacement factoryをそれぞれのDishka scopeで登録する.

        Args:
            *replacements (ProviderReplacement[object]): runtime dependencyを置換する型付き
                factory定義.

        Notes:
            各replacementは ``override=True`` で登録され,同じ型を提供する標準providerを
            test内で置換する.
        """
        super().__init__(scope=Scope.APP)
        for replacement in replacements:
            _ = self.provide(
                replacement.factory,
                provides=replacement.provides,
                scope=replacement.scope,
                override=True,
            )


def replace_value[T](
    provides: type[T],
    value: T,
    *,
    scope: Scope = Scope.APP,
) -> ProviderReplacement[T]:
    """既存の型付きtest valueを返すdependency replacementを作成する.

    Args:
        provides (type[T]): replacementとして公開するdependency型.
        value (T): dependency解決時に返す既存のtest instance.
        scope (Scope): valueをcacheするDishka scope.

    Returns:
        ProviderReplacement[T]: ``value`` を返すfactoryを持つoverride定義.
    """

    def factory():
        """captureしたtest valueをDishkaへ返す.

        Returns:
            T: outer functionへ渡された同一の ``value`` instance.
        """
        return value

    return ProviderReplacement(provides=provides, factory=factory, scope=scope)


def replace_factory[T](
    provides: type[T],
    factory: Callable[[], T],
    *,
    scope: Scope = Scope.APP,
) -> ProviderReplacement[T]:
    """型付きtest factoryを使うdependency replacementを作成する.

    Args:
        provides (type[T]): replacementとして公開するdependency型.
        factory (Callable[[], T]): dependency解決時にinstanceを生成する引数なしfactory.
        scope (Scope): factory結果をcacheするDishka scope.

    Returns:
        ProviderReplacement[T]: 渡された ``factory`` を保持するoverride定義.
    """
    return ProviderReplacement(provides=provides, factory=factory, scope=scope)


def make_in_memory_broker() -> AsyncBroker:
    """Redisを使わずに全Athena jobを登録したin-memory Taskiq brokerを作成する.

    Returns:
        AsyncBroker: registered jobを解決できる ``InMemoryBroker`` instance.

    Notes:
        job registrationはproduction brokerと同じ ``register_all_jobs`` を通して行う.
    """
    broker: AsyncBroker = InMemoryBroker()
    register_all_jobs(broker)
    return broker


class PassingHIBPClient:
    """passwordをcompromisedと判定しないHIBP test doubleを表す."""

    async def is_password_compromised(self, password: str) -> bool:
        """任意のpasswordに対してcompromisedではない結果を返す.

        Args:
            password (str): HIBP照会対象として渡されるpassword.

        Returns:
            bool: 常に ``False`` を返し,network accessを行わない.
        """
        _ = password
        return False


def make_in_memory_runtime_provider_set(
    *,
    blob_root: str | Path = ".data/test-blobs",
    packet_queue_max_size: int = 4096,
) -> TestProviderSet:
    """完全なin-memory app/runtime graph用provider overrideを構成する.

    Args:
        blob_root (str | Path): local test blob backendがfileを保存するroot path.
        packet_queue_max_size (int): in-memory packet queueに保持できる最大packet数.

    Returns:
        TestProviderSet: broker,repository,state,storage,HIBP,beatmap metadataを置換する
            provider set.

    Notes:
        test graphはnetwork serviceとproduction persistence adapterを使用せず,明示的なin-memory
        implementationをAPP scopeで登録する.
    """
    repository_adapters = InMemoryRepositoryAdapterFamily()

    return TestProviderSet(
        replace_value(AsyncBroker, make_in_memory_broker(), scope=Scope.APP),
        replace_value(HIBPClient, PassingHIBPClient(), scope=Scope.APP),
        replace_value(
            PacketQueue,
            InMemoryPacketQueue(max_size=packet_queue_max_size),
            scope=Scope.APP,
        ),
        replace_value(ChannelStateStore, InMemoryChannelStateStore(), scope=Scope.APP),
        replace_value(RateLimiter, InMemoryRateLimiter(), scope=Scope.APP),
        replace_value(
            ReplayDownloadAccountingGate,
            InMemoryReplayDownloadAccountingGate(),
            scope=Scope.APP,
        ),
        replace_value(StableUserStatusStore, InMemoryStableUserStatusStore(), scope=Scope.APP),
        replace_value(
            PerformanceCompletionSignal,
            InMemoryPerformanceCompletionSignal(),
            scope=Scope.APP,
        ),
        replace_value(SessionStore, InMemorySessionStore(), scope=Scope.APP),
        replace_value(
            BlobStorageBackend,
            LocalBlobStorageBackend(blob_root),
            scope=Scope.APP,
        ),
        *(
            replace_value(replacement.provides, replacement.value, scope=Scope.APP)
            for replacement in repository_adapters.replacements()
        ),
        replace_value(
            BeatmapMetadataProvider,
            InMemoryBeatmapMetadataProvider(),
        ),
    )
