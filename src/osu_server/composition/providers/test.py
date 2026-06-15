"""Test-only provider replacement helpers."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, TypeVar, final

from dishka import Provider, Scope

from osu_server.domain.beatmaps import BeatmapMetadataProvider
from osu_server.infrastructure.security.hibp import HIBPClient
from osu_server.infrastructure.state.interfaces.channel_state_store import ChannelStateStore
from osu_server.infrastructure.state.interfaces.packet_queue import PacketQueue
from osu_server.infrastructure.state.interfaces.rate_limiter import RateLimiter
from osu_server.infrastructure.state.memory.channel_state_store import InMemoryChannelStateStore
from osu_server.infrastructure.state.memory.packet_queue import InMemoryPacketQueue
from osu_server.infrastructure.state.memory.rate_limiter import InMemoryRateLimiter
from osu_server.infrastructure.storage.interfaces import BlobStorageBackend
from osu_server.infrastructure.storage.local import LocalBlobStorageBackend
from osu_server.repositories.interfaces.beatmap_repository import BeatmapRepository
from osu_server.repositories.interfaces.blob_repository import BlobRepository
from osu_server.repositories.interfaces.channel_repository import ChannelRepository
from osu_server.repositories.interfaces.queries.beatmap_score_listing import (
    BeatmapScoreListingQueryRepository,
)
from osu_server.repositories.interfaces.queries.beatmaps import BeatmapQueryRepository
from osu_server.repositories.interfaces.queries.channels import ChannelQueryRepository
from osu_server.repositories.interfaces.queries.chat import ChatHistoryQueryRepository
from osu_server.repositories.interfaces.queries.roles import RoleQueryRepository
from osu_server.repositories.interfaces.queries.users import UserQueryRepository
from osu_server.repositories.interfaces.replay_repository import ReplayRepository
from osu_server.repositories.interfaces.role_repository import RoleRepository
from osu_server.repositories.interfaces.score_repository import ScoreRepository
from osu_server.repositories.interfaces.session_store import SessionStore
from osu_server.repositories.interfaces.submission_repository import ScoreSubmissionRepository
from osu_server.repositories.interfaces.unit_of_work import UnitOfWorkFactory
from osu_server.repositories.interfaces.user_repository import UserRepository
from osu_server.repositories.memory.beatmap_repository import InMemoryBeatmapRepository
from osu_server.repositories.memory.blob_repository import InMemoryBlobRepository
from osu_server.repositories.memory.channel_repository import InMemoryChannelRepository
from osu_server.repositories.memory.commands.state import InMemoryCommandRepositoryState
from osu_server.repositories.memory.queries.beatmap_score_listing import (
    InMemoryBeatmapScoreListingQueryRepository,
)
from osu_server.repositories.memory.queries.beatmaps import InMemoryBeatmapQueryRepository
from osu_server.repositories.memory.queries.channels import InMemoryChannelQueryRepository
from osu_server.repositories.memory.queries.chat import InMemoryChatHistoryQueryRepository
from osu_server.repositories.memory.queries.roles import InMemoryRoleQueryRepository
from osu_server.repositories.memory.queries.users import InMemoryUserQueryRepository
from osu_server.repositories.memory.replay_repository import InMemoryReplayRepository
from osu_server.repositories.memory.role_repository import InMemoryRoleRepository
from osu_server.repositories.memory.score_repository import InMemoryScoreRepository
from osu_server.repositories.memory.session_store import InMemorySessionStore
from osu_server.repositories.memory.submission_repository import InMemoryScoreSubmissionRepository
from osu_server.repositories.memory.unit_of_work import InMemoryUnitOfWorkFactory
from osu_server.repositories.memory.user_repository import InMemoryUserRepository
from osu_server.services.beatmap_mirror import InMemoryBeatmapMetadataProvider

if TYPE_CHECKING:
    from collections.abc import Callable
    from pathlib import Path

T_co = TypeVar("T_co", covariant=True)


@dataclass(frozen=True, slots=True)
class ProviderReplacement[T_co]:
    """Typed description of one test provider replacement."""

    provides: type[T_co]
    factory: Callable[[], T_co]
    scope: Scope = Scope.APP


@final
class TestProviderSet(Provider):
    """Provider set that replaces runtime providers for tests."""

    __test__: bool = False

    def __init__(self, *replacements: ProviderReplacement[object]) -> None:
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
    """Replace a dependency with one existing typed test value."""

    def factory():
        return value

    return ProviderReplacement(provides=provides, factory=factory, scope=scope)


def replace_factory[T](
    provides: type[T],
    factory: Callable[[], T],
    *,
    scope: Scope = Scope.APP,
) -> ProviderReplacement[T]:
    """Replace a dependency with a typed test factory."""
    return ProviderReplacement(provides=provides, factory=factory, scope=scope)


class PassingHIBPClient:
    """HIBP test double that never marks a password as compromised."""

    async def is_password_compromised(self, password: str) -> bool:
        _ = password
        return False


def make_in_memory_runtime_provider_set(
    *,
    blob_root: str | Path = ".data/test-blobs",
    packet_queue_max_size: int = 4096,
) -> TestProviderSet:
    """Return provider overrides for a full in-memory app/runtime graph."""
    command_state = InMemoryCommandRepositoryState()
    uow_factory = InMemoryUnitOfWorkFactory(command_state)

    user_repository = InMemoryUserRepository(state=command_state)
    role_repository = InMemoryRoleRepository(state=command_state)
    channel_repository = InMemoryChannelRepository(state=command_state)
    beatmap_repository = InMemoryBeatmapRepository()
    blob_repository = InMemoryBlobRepository()
    score_repository = InMemoryScoreRepository()
    replay_repository = InMemoryReplayRepository()
    submission_repository = InMemoryScoreSubmissionRepository()

    beatmap_query_repository = InMemoryBeatmapQueryRepository(beatmap_repository)

    return TestProviderSet(
        replace_value(HIBPClient, PassingHIBPClient(), scope=Scope.APP),
        replace_value(
            PacketQueue,
            InMemoryPacketQueue(max_size=packet_queue_max_size),
            scope=Scope.APP,
        ),
        replace_value(ChannelStateStore, InMemoryChannelStateStore(), scope=Scope.APP),
        replace_value(RateLimiter, InMemoryRateLimiter(), scope=Scope.APP),
        replace_value(SessionStore, InMemorySessionStore(), scope=Scope.APP),
        replace_value(
            BlobStorageBackend,
            LocalBlobStorageBackend(blob_root),
            scope=Scope.APP,
        ),
        replace_value(UnitOfWorkFactory, uow_factory, scope=Scope.APP),
        replace_value(UserRepository, user_repository, scope=Scope.APP),
        replace_value(RoleRepository, role_repository, scope=Scope.APP),
        replace_value(ChannelRepository, channel_repository, scope=Scope.APP),
        replace_value(BeatmapRepository, beatmap_repository, scope=Scope.APP),
        replace_value(BlobRepository, blob_repository, scope=Scope.APP),
        replace_value(ScoreRepository, score_repository, scope=Scope.APP),
        replace_value(ReplayRepository, replay_repository, scope=Scope.APP),
        replace_value(ScoreSubmissionRepository, submission_repository, scope=Scope.APP),
        replace_value(UserQueryRepository, InMemoryUserQueryRepository(uow_factory)),
        replace_value(RoleQueryRepository, InMemoryRoleQueryRepository(uow_factory)),
        replace_value(ChannelQueryRepository, InMemoryChannelQueryRepository(uow_factory)),
        replace_value(ChatHistoryQueryRepository, InMemoryChatHistoryQueryRepository(uow_factory)),
        replace_value(BeatmapQueryRepository, beatmap_query_repository),
        replace_value(
            BeatmapScoreListingQueryRepository,
            InMemoryBeatmapScoreListingQueryRepository(beatmap_query_repository),
        ),
        replace_value(
            BeatmapMetadataProvider,
            InMemoryBeatmapMetadataProvider(),
        ),
    )
