"""Worker-side runtime composition.

Builds use-cases the taskiq worker process needs: chat persistence commands
and beatmap fetch commands (metadata + .osu file).
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from osu_server.infrastructure.storage import create_blob_storage_backend
from osu_server.repositories.beatmaps.metadata_providers import (
    CompositeBeatmapMetadataProvider,
)
from osu_server.repositories.sqlalchemy.beatmap_repository import SQLAlchemyBeatmapRepository
from osu_server.repositories.sqlalchemy.blob_repository import SQLAlchemyBlobRepository
from osu_server.repositories.sqlalchemy.unit_of_work import SQLAlchemyUnitOfWorkFactory
from osu_server.services.beatmap_mirror import (
    BeatmapFileProviderService,
    MirrorMetadataProviderService,
    OsuApiMetadataProviderService,
)
from osu_server.services.blob_storage_service import BlobStorageService
from osu_server.services.commands.beatmaps import (
    FetchBeatmapFileUseCase,
    FetchBeatmapMetadataUseCase,
)
from osu_server.services.commands.chat import (
    PersistChannelMessageUseCase,
    PersistPrivateMessageUseCase,
)

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

    from osu_server.config import AppConfig


def create_worker_chat_persistence_use_cases(
    *,
    session_factory: async_sessionmaker[AsyncSession],
) -> tuple[PersistChannelMessageUseCase, PersistPrivateMessageUseCase]:
    """Build worker-side chat persistence command use-cases."""
    uow_factory = SQLAlchemyUnitOfWorkFactory(session_factory)
    return (
        PersistChannelMessageUseCase(uow_factory=uow_factory),
        PersistPrivateMessageUseCase(uow_factory=uow_factory),
    )


def create_worker_beatmap_metadata_fetch(
    *,
    session_factory: async_sessionmaker[AsyncSession],
    config: AppConfig,
) -> FetchBeatmapMetadataUseCase:
    """Build the worker-side beatmap metadata fetch command.

    Uses the real (non-test) metadata providers: official API first,
    mirror fallback second.
    """
    repo = SQLAlchemyBeatmapRepository(session_factory)
    official = OsuApiMetadataProviderService(
        client_id=config.beatmap_official_api_client_id,  # pyright: ignore[reportArgumentType]
        client_secret=config.beatmap_official_api_client_secret,  # pyright: ignore[reportArgumentType]
    )
    mirror = MirrorMetadataProviderService(
        base_urls=config.beatmap_metadata_mirror_base_urls,
    )
    metadata_provider = CompositeBeatmapMetadataProvider(official=official, mirror=mirror)
    return FetchBeatmapMetadataUseCase(repository=repo, metadata_provider=metadata_provider)


async def create_worker_beatmap_file_fetch(
    *,
    session_factory: async_sessionmaker[AsyncSession],
    config: AppConfig,
) -> FetchBeatmapFileUseCase:
    """Build the worker-side beatmap file fetch command.

    Uses the composite file provider for .osu file sources and a
    ``BlobStorageService`` backed by the configured blob storage backend.
    """
    repo = SQLAlchemyBeatmapRepository(session_factory)
    file_provider = BeatmapFileProviderService(
        osu_current_url_template=config.beatmap_osu_current_url_template,
        osu_legacy_url_template=config.beatmap_osu_legacy_url_template,
        mirror_url_templates=list(config.beatmap_community_mirror_url_templates),
    )
    blob_backend = create_blob_storage_backend(config)
    await blob_backend.validate_configuration()
    blob_repo = SQLAlchemyBlobRepository(session_factory)
    blob_storage = BlobStorageService(
        blob_repo=blob_repo,
        backend=blob_backend,
        storage_backend=config.blob_storage_backend,
    )
    return FetchBeatmapFileUseCase(
        repository=repo,
        file_provider=file_provider,
        blob_storage=blob_storage,
    )


__all__ = [
    "create_worker_beatmap_file_fetch",
    "create_worker_beatmap_metadata_fetch",
    "create_worker_chat_persistence_use_cases",
]
