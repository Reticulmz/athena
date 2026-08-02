"""app/worker graphで共有するblob storage service providerを定義する.

physical storage backend, blob metadata query, command transactionを組み合わせ,
transportとuse caseがbackend実装を直接知らずにblobを扱えるようにする.
"""

from __future__ import annotations

from typing import final

from dishka import Provider, Scope

from osu_server.composition.providers._dishka import provide
from osu_server.config import AppConfig
from osu_server.domain.storage.blobs import BlobStorageBackendKind
from osu_server.infrastructure.storage.interfaces import BlobStorageBackend
from osu_server.repositories.interfaces.queries.blobs import BlobQueryRepository
from osu_server.repositories.interfaces.unit_of_work import UnitOfWorkFactory
from osu_server.services.commands.storage.blob_storage import (
    BlobContentUnavailableError,
    BlobStorageService,
)
from osu_server.services.queries.storage import BlobByteReader, BlobByteReaderAdapter

_DISHKA_RUNTIME_HINTS = (
    AppConfig,
    BlobByteReader,
    BlobQueryRepository,
    BlobStorageBackend,
    UnitOfWorkFactory,
)


@final
class StorageProviderSet(Provider):
    """blob storage application serviceとread adapterを提供する.

    Attributes:
        scope (Scope): app/worker processの生存期間と一致するDishka scope.
    """

    scope = Scope.APP

    @provide
    def blob_storage_service(
        self,
        blob_query_repo: BlobQueryRepository,
        uow_factory: UnitOfWorkFactory,
        backend: BlobStorageBackend,
        config: AppConfig,
    ) -> BlobStorageService:
        """Blob metadataとphysical backendを統合するcommand serviceを提供する.

        Args:
            blob_query_repo (BlobQueryRepository): blob metadataを読み取るquery repository.
            uow_factory (UnitOfWorkFactory): blob metadata mutationをcommitするtransaction factory.
            backend (BlobStorageBackend): configuration検証済みのphysical blob storage adapter.
            config (AppConfig): storage backend kindを含むruntime設定.

        Returns:
            BlobStorageService: physical contentとdurable metadataを一貫して扱うservice.

        Raises:
            ValueError: config.blob_storage_backendがBlobStorageBackendKindとして無効な場合.
        """
        return BlobStorageService(
            blob_query_repo=blob_query_repo,
            uow_factory=uow_factory,
            backend=backend,
            storage_backend=BlobStorageBackendKind(config.blob_storage_backend),
        )

    @provide
    def blob_byte_reader(self, blob_storage_service: BlobStorageService) -> BlobByteReader:
        """transport向けblob byte reader adapterを提供する.

        Args:
            blob_storage_service (BlobStorageService): blob contentとmetadataを統合するservice.

        Returns:
            BlobByteReader: blob byteを返し, content unavailable時はBlobBytesUnavailableErrorを
                伝播または送出するadapter.
        """
        return BlobByteReaderAdapter(
            blob_storage_service,
            unavailable_exception_types=(BlobContentUnavailableError,),
        )
