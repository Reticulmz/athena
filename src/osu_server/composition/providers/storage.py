"""Shared storage providers for app and worker dependency graphs."""

from __future__ import annotations

from typing import final

from dishka import Provider, Scope

from osu_server.composition.providers._dishka import provide
from osu_server.config import AppConfig
from osu_server.infrastructure.storage.interfaces import BlobStorageBackend
from osu_server.repositories.interfaces.queries.blobs import BlobQueryRepository
from osu_server.repositories.interfaces.unit_of_work import UnitOfWorkFactory
from osu_server.services.commands.storage.blob_storage import BlobStorageService

_DISHKA_RUNTIME_HINTS = (
    AppConfig,
    BlobQueryRepository,
    BlobStorageBackend,
    UnitOfWorkFactory,
)


@final
class StorageProviderSet(Provider):
    """Providers for blob storage application services."""

    scope = Scope.APP

    @provide
    def blob_storage_service(
        self,
        blob_query_repo: BlobQueryRepository,
        uow_factory: UnitOfWorkFactory,
        backend: BlobStorageBackend,
        config: AppConfig,
    ) -> BlobStorageService:
        return BlobStorageService(
            blob_query_repo=blob_query_repo,
            uow_factory=uow_factory,
            backend=backend,
            storage_backend=config.blob_storage_backend,
        )
