"""Dishka provider sets for app, worker, and test composition."""

from __future__ import annotations

from importlib import import_module
from typing import TYPE_CHECKING, cast

if TYPE_CHECKING:
    from osu_server.composition.performance_cli import (
        make_performance_cli_container as make_performance_cli_container,
    )
    from osu_server.composition.providers.app import (
        AppProviderGraph as AppProviderGraph,
    )
    from osu_server.composition.providers.app import (
        AppProviderSet as AppProviderSet,
    )
    from osu_server.composition.providers.beatmaps import (
        BeatmapProviderSet as BeatmapProviderSet,
    )
    from osu_server.composition.providers.beatmaps_app import (
        BeatmapAppProviderSet as BeatmapAppProviderSet,
    )
    from osu_server.composition.providers.chat import ChatProviderSet as ChatProviderSet
    from osu_server.composition.providers.chat_app import (
        ChatAppProviderSet as ChatAppProviderSet,
    )
    from osu_server.composition.providers.container import (
        make_app_container as make_app_container,
    )
    from osu_server.composition.providers.container import (
        make_worker_container as make_worker_container,
    )
    from osu_server.composition.providers.identity import (
        IdentityProviderSet as IdentityProviderSet,
    )
    from osu_server.composition.providers.infrastructure import (
        InfrastructureProviderSet as InfrastructureProviderSet,
    )
    from osu_server.composition.providers.performance import (
        PerformanceProviderSet as PerformanceProviderSet,
    )
    from osu_server.composition.providers.performance_cli import (
        PerformanceCliProviderSet as PerformanceCliProviderSet,
    )
    from osu_server.composition.providers.repositories import (
        RepositoryProviderSet as RepositoryProviderSet,
    )
    from osu_server.composition.providers.score_submission import (
        ScoreSubmissionProviderSet as ScoreSubmissionProviderSet,
    )
    from osu_server.composition.providers.scores import (
        ScoreProviderSet as ScoreProviderSet,
    )
    from osu_server.composition.providers.stable_bancho import (
        StableBanchoProviderSet as StableBanchoProviderSet,
    )
    from osu_server.composition.providers.stable_web_legacy import (
        StableWebLegacyProviderSet as StableWebLegacyProviderSet,
    )
    from osu_server.composition.providers.storage import (
        StorageProviderSet as StorageProviderSet,
    )
    from osu_server.composition.providers.test import (
        ProviderReplacement as ProviderReplacement,
    )
    from osu_server.composition.providers.test import (
        TestProviderSet as TestProviderSet,
    )
    from osu_server.composition.providers.test import (
        replace_factory as replace_factory,
    )
    from osu_server.composition.providers.test import (
        replace_value as replace_value,
    )
    from osu_server.composition.providers.worker import (
        WorkerProviderGraph as WorkerProviderGraph,
    )
    from osu_server.composition.providers.worker import (
        WorkerProviderSet as WorkerProviderSet,
    )

__all__ = (
    "AppProviderGraph",
    "AppProviderSet",
    "BeatmapAppProviderSet",
    "BeatmapProviderSet",
    "ChatAppProviderSet",
    "ChatProviderSet",
    "IdentityProviderSet",
    "InfrastructureProviderSet",
    "PerformanceCliProviderSet",
    "PerformanceProviderSet",
    "ProviderReplacement",
    "RepositoryProviderSet",
    "ScoreProviderSet",
    "ScoreSubmissionProviderSet",
    "StableBanchoProviderSet",
    "StableWebLegacyProviderSet",
    "StorageProviderSet",
    "TestProviderSet",
    "WorkerProviderGraph",
    "WorkerProviderSet",
    "make_app_container",
    "make_performance_cli_container",
    "make_worker_container",
    "replace_factory",
    "replace_value",
)

_EXPORTS: dict[str, tuple[str, str]] = {
    "AppProviderGraph": ("osu_server.composition.providers.app", "AppProviderGraph"),
    "AppProviderSet": ("osu_server.composition.providers.app", "AppProviderSet"),
    "BeatmapAppProviderSet": (
        "osu_server.composition.providers.beatmaps_app",
        "BeatmapAppProviderSet",
    ),
    "BeatmapProviderSet": (
        "osu_server.composition.providers.beatmaps",
        "BeatmapProviderSet",
    ),
    "ChatAppProviderSet": (
        "osu_server.composition.providers.chat_app",
        "ChatAppProviderSet",
    ),
    "ChatProviderSet": ("osu_server.composition.providers.chat", "ChatProviderSet"),
    "IdentityProviderSet": (
        "osu_server.composition.providers.identity",
        "IdentityProviderSet",
    ),
    "InfrastructureProviderSet": (
        "osu_server.composition.providers.infrastructure",
        "InfrastructureProviderSet",
    ),
    "PerformanceCliProviderSet": (
        "osu_server.composition.providers.performance_cli",
        "PerformanceCliProviderSet",
    ),
    "PerformanceProviderSet": (
        "osu_server.composition.providers.performance",
        "PerformanceProviderSet",
    ),
    "ProviderReplacement": (
        "osu_server.composition.providers.test",
        "ProviderReplacement",
    ),
    "RepositoryProviderSet": (
        "osu_server.composition.providers.repositories",
        "RepositoryProviderSet",
    ),
    "ScoreProviderSet": ("osu_server.composition.providers.scores", "ScoreProviderSet"),
    "ScoreSubmissionProviderSet": (
        "osu_server.composition.providers.score_submission",
        "ScoreSubmissionProviderSet",
    ),
    "StableBanchoProviderSet": (
        "osu_server.composition.providers.stable_bancho",
        "StableBanchoProviderSet",
    ),
    "StableWebLegacyProviderSet": (
        "osu_server.composition.providers.stable_web_legacy",
        "StableWebLegacyProviderSet",
    ),
    "StorageProviderSet": (
        "osu_server.composition.providers.storage",
        "StorageProviderSet",
    ),
    "TestProviderSet": ("osu_server.composition.providers.test", "TestProviderSet"),
    "WorkerProviderGraph": (
        "osu_server.composition.providers.worker",
        "WorkerProviderGraph",
    ),
    "WorkerProviderSet": ("osu_server.composition.providers.worker", "WorkerProviderSet"),
    "make_app_container": (
        "osu_server.composition.providers.container",
        "make_app_container",
    ),
    "make_performance_cli_container": (
        "osu_server.composition.performance_cli",
        "make_performance_cli_container",
    ),
    "make_worker_container": (
        "osu_server.composition.providers.container",
        "make_worker_container",
    ),
    "replace_factory": ("osu_server.composition.providers.test", "replace_factory"),
    "replace_value": ("osu_server.composition.providers.test", "replace_value"),
}


def __getattr__(name: str) -> object:
    """Resolve package-level exports without importing every provider eagerly."""
    try:
        module_name, attribute_name = _EXPORTS[name]
    except KeyError as exc:
        msg = f"module {__name__!r} has no attribute {name!r}"
        raise AttributeError(msg) from exc

    module = import_module(module_name)
    value = cast("object", getattr(module, attribute_name))
    return _cache_export(name, value)


def _cache_export(name: str, value: object) -> object:
    globals()[name] = value
    return value
