"""appとworkerのDishka containerを構成するfactoryを提供する."""

from __future__ import annotations

from typing import TYPE_CHECKING

from dishka import make_async_container

from osu_server.composition.providers.app import AppProviderSet
from osu_server.composition.providers.beatmaps import BeatmapProviderSet
from osu_server.composition.providers.beatmaps_app import BeatmapAppProviderSet
from osu_server.composition.providers.chat import ChatProviderSet
from osu_server.composition.providers.chat_app import ChatAppProviderSet
from osu_server.composition.providers.identity import IdentityProviderSet
from osu_server.composition.providers.infrastructure import InfrastructureProviderSet
from osu_server.composition.providers.performance import PerformanceProviderSet
from osu_server.composition.providers.repositories import RepositoryProviderSet
from osu_server.composition.providers.score_submission import ScoreSubmissionProviderSet
from osu_server.composition.providers.scores import ScoreProviderSet
from osu_server.composition.providers.stable_bancho import StableBanchoProviderSet
from osu_server.composition.providers.stable_web_legacy import StableWebLegacyProviderSet
from osu_server.composition.providers.storage import StorageProviderSet
from osu_server.composition.providers.worker import WorkerProviderSet

if TYPE_CHECKING:
    from collections.abc import Iterable

    from dishka import AsyncContainer, Provider

    from osu_server.config import AppConfig


def make_app_container(
    config: AppConfig,
    overrides: Iterable[Provider] = (),
) -> AsyncContainer:
    """App process用の完全なdependency graphを構成する.

    Args:
        config (AppConfig): infrastructure providerへ渡す実行時設定.
        overrides (Iterable[Provider]): 標準provider setの後に追加する明示的なoverride.

    Returns:
        AsyncContainer: stable transportを含むapp process用の非同期Dishka container.

    Notes:
        ``overrides`` は標準provider setの後に渡し、testなどが明示した置換を優先できる.
    """
    return make_async_container(
        InfrastructureProviderSet(config),
        RepositoryProviderSet(),
        StorageProviderSet(),
        BeatmapProviderSet(),
        ChatProviderSet(),
        ScoreProviderSet(),
        PerformanceProviderSet(),
        AppProviderSet(),
        IdentityProviderSet(),
        ChatAppProviderSet(),
        BeatmapAppProviderSet(),
        ScoreSubmissionProviderSet(),
        StableBanchoProviderSet(),
        StableWebLegacyProviderSet(),
        *overrides,
    )


def make_worker_container(
    config: AppConfig,
    overrides: Iterable[Provider] = (),
) -> AsyncContainer:
    """Worker process用の共有dependency graphを構成する.

    Args:
        config (AppConfig): infrastructure providerへ渡す実行時設定.
        overrides (Iterable[Provider]): 標準provider setの後に追加する明示的なoverride.

    Returns:
        AsyncContainer: background job実行に必要な共有providerを持つ非同期Dishka container.

    Notes:
        app専用transport providerは登録せず、worker用provider setだけを追加する.
    """
    return make_async_container(
        InfrastructureProviderSet(config),
        RepositoryProviderSet(),
        StorageProviderSet(),
        BeatmapProviderSet(),
        ChatProviderSet(),
        ScoreProviderSet(),
        PerformanceProviderSet(),
        WorkerProviderSet(),
        *overrides,
    )
