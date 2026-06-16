"""Container factories for app and worker composition."""

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
    """Build the app dependency graph with explicit provider overrides."""
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
    """Build the worker dependency graph with explicit provider overrides."""
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
