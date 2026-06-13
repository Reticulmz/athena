"""Dishka provider sets for app, worker, and test composition."""

from __future__ import annotations

from osu_server.composition.providers.app import AppProviderGraph, AppProviderSet
from osu_server.composition.providers.common import CommonProviderSet
from osu_server.composition.providers.container import make_app_container, make_worker_container
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
    "CommonProviderSet",
    "ProviderReplacement",
    "TestProviderSet",
    "WorkerProviderGraph",
    "WorkerProviderSet",
    "make_app_container",
    "make_worker_container",
    "replace_factory",
    "replace_value",
)
