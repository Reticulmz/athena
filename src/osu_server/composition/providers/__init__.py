"""Dishka provider sets for app, worker, and test composition."""

from __future__ import annotations

from osu_server.composition.providers.app import AppProviderGraph, AppProviderSet
from osu_server.composition.providers.beatmaps import BeatmapProviderSet
from osu_server.composition.providers.beatmaps_app import BeatmapAppProviderSet
from osu_server.composition.providers.chat import ChatProviderSet
from osu_server.composition.providers.chat_app import ChatAppProviderSet
from osu_server.composition.providers.container import make_app_container, make_worker_container
from osu_server.composition.providers.identity import IdentityProviderSet
from osu_server.composition.providers.infrastructure import InfrastructureProviderSet
from osu_server.composition.providers.repositories import RepositoryProviderSet
from osu_server.composition.providers.score_submission import ScoreSubmissionProviderSet
from osu_server.composition.providers.scores import ScoreProviderSet
from osu_server.composition.providers.stable_bancho import StableBanchoProviderSet
from osu_server.composition.providers.stable_web_legacy import StableWebLegacyProviderSet
from osu_server.composition.providers.storage import StorageProviderSet
from osu_server.composition.providers.test import (
    ProviderReplacement,
    TestProviderSet,
    replace_factory,
    replace_value,
)
from osu_server.composition.providers.worker import WorkerProviderGraph, WorkerProviderSet

__all__ = (
    "AppProviderGraph",
    "AppProviderSet",
    "BeatmapAppProviderSet",
    "BeatmapProviderSet",
    "ChatAppProviderSet",
    "ChatProviderSet",
    "IdentityProviderSet",
    "InfrastructureProviderSet",
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
    "make_worker_container",
    "replace_factory",
    "replace_value",
)
