"""Worker-side runtime composition.

Builds services the taskiq worker process needs: ChatService persistence
and beatmap fetch jobs (metadata + .osu file).
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from osu_server.infrastructure.beatmaps.file_sources import CompositeBeatmapFileProvider
from osu_server.infrastructure.messaging.memory import InMemoryEventBus
from osu_server.infrastructure.state.valkey.channel_state_store import ValkeyChannelStateStore
from osu_server.infrastructure.state.valkey.rate_limiter import ValkeyRateLimiter
from osu_server.infrastructure.storage import create_blob_storage_backend
from osu_server.jobs.beatmap_fetch import FetchBeatmapFileJob, FetchBeatmapMetadataJob
from osu_server.repositories.sqlalchemy.beatmap_repository import SQLAlchemyBeatmapRepository
from osu_server.repositories.sqlalchemy.blob_repository import SQLAlchemyBlobRepository
from osu_server.repositories.sqlalchemy.channel_repository import SQLAlchemyChannelRepository
from osu_server.repositories.sqlalchemy.chat_repository import SQLAlchemyChatRepository
from osu_server.repositories.sqlalchemy.user_repository import SQLAlchemyUserRepository
from osu_server.repositories.valkey.session_store import ValkeySessionStore
from osu_server.services.bancho_bot.command_service import CommandService
from osu_server.services.bancho_bot.commands import create_builtin_registry
from osu_server.services.beatmaps.metadata_providers import (
    CompositeBeatmapMetadataProvider,
)
from osu_server.services.beatmaps.providers import (
    MirrorMetadataProvider,
    OsuApiMetadataProvider,
)
from osu_server.services.blob_storage_service import BlobStorageService
from osu_server.services.channel_service import ChannelService
from osu_server.services.chat_service import ChatService
from osu_server.services.private_message_service import PrivateMessageService

if TYPE_CHECKING:
    from glide import GlideClient
    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

    from osu_server.config import AppConfig


def create_worker_chat_service(
    *,
    session_factory: async_sessionmaker[AsyncSession],
    valkey: GlideClient,
    config: AppConfig,
) -> ChatService:
    """Build the worker-side ChatService persistence runtime."""
    session_store = ValkeySessionStore(valkey, ttl=config.session_ttl)
    channel_repo = SQLAlchemyChannelRepository(session_factory)
    channel_state = ValkeyChannelStateStore(valkey)
    channel_service = ChannelService(
        channel_repo=channel_repo,
        channel_state=channel_state,
    )
    user_repo = SQLAlchemyUserRepository(session_factory)
    private_message_service = PrivateMessageService(
        user_repo=user_repo,
        session_store=session_store,
    )
    command_service = CommandService(create_builtin_registry())
    event_bus = InMemoryEventBus()
    rate_limiter = ValkeyRateLimiter(valkey)
    chat_repository = SQLAlchemyChatRepository(session_factory)

    return ChatService(
        channel_service=channel_service,
        private_message_service=private_message_service,
        command_service=command_service,
        session_store=session_store,
        event_bus=event_bus,
        rate_limiter=rate_limiter,
        config=config,
        chat_repository=chat_repository,
    )


def create_worker_beatmap_metadata_fetch(
    *,
    session_factory: async_sessionmaker[AsyncSession],
    config: AppConfig,
) -> FetchBeatmapMetadataJob:
    """Build the worker-side beatmap metadata fetch job.

    Uses the real (non-test) metadata providers: official API first,
    mirror fallback second.
    """
    repo = SQLAlchemyBeatmapRepository(session_factory)
    official = OsuApiMetadataProvider(
        client_id=config.beatmap_official_api_client_id,  # pyright: ignore[reportArgumentType]
        client_secret=config.beatmap_official_api_client_secret,  # pyright: ignore[reportArgumentType]
    )
    mirror = MirrorMetadataProvider()
    composite = CompositeBeatmapMetadataProvider(official=official, mirror=mirror)
    return FetchBeatmapMetadataJob(repository=repo, metadata_provider=composite)


async def create_worker_beatmap_file_fetch(
    *,
    session_factory: async_sessionmaker[AsyncSession],
    config: AppConfig,
) -> FetchBeatmapFileJob:
    """Build the worker-side beatmap file fetch job.

    Uses the composite file provider for .osu file sources and a
    ``BlobStorageService`` backed by the configured blob storage backend.
    """
    repo = SQLAlchemyBeatmapRepository(session_factory)
    file_provider = CompositeBeatmapFileProvider(
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
    return FetchBeatmapFileJob(
        repository=repo,
        file_provider=file_provider,
        blob_storage=blob_storage,
    )


__all__ = [
    "create_worker_beatmap_file_fetch",
    "create_worker_beatmap_metadata_fetch",
    "create_worker_chat_service",
]
