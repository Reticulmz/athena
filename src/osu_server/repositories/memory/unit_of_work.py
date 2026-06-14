"""In-memory command Unit of Work implementation."""

from __future__ import annotations

from typing import TYPE_CHECKING, Self, cast

from osu_server.repositories.memory.commands import (
    InMemoryBeatmapCommandRepository,
    InMemoryBlobCommandRepository,
    InMemoryChannelCommandRepository,
    InMemoryCommandRepositoryState,
    InMemoryReplayCommandRepository,
    InMemoryRoleCommandRepository,
    InMemoryScoreCommandRepository,
    InMemoryScoreSubmissionCommandRepository,
    InMemoryUserCommandRepository,
)

if TYPE_CHECKING:
    from collections.abc import MutableMapping, MutableSet
    from contextlib import AbstractAsyncContextManager
    from types import TracebackType

    from osu_server.domain.identity.roles import Role
    from osu_server.repositories.interfaces.unit_of_work import UnitOfWork


def _replace_mapping[K, V](
    current: MutableMapping[K, V],
    value: MutableMapping[K, V],
) -> None:
    current.clear()
    current.update(value)


def _replace_set[T](current: MutableSet[T], value: MutableSet[T]) -> None:
    current.clear()
    for item in value:
        current.add(item)


class InMemoryUnitOfWorkFactory:
    """Factory that opens isolated in-memory command UoW scopes."""

    def __init__(self, state: InMemoryCommandRepositoryState | None = None) -> None:
        self._state: InMemoryCommandRepositoryState = state or InMemoryCommandRepositoryState()

    def __call__(self) -> AbstractAsyncContextManager[UnitOfWork]:
        return cast("AbstractAsyncContextManager[UnitOfWork]", InMemoryUnitOfWork(self))

    def snapshot(self) -> InMemoryCommandRepositoryState:
        return self._state.clone()

    def commit_state(self, state: InMemoryCommandRepositoryState) -> None:
        committed = state.clone()
        _replace_mapping(self._state.users_by_id, committed.users_by_id)
        _replace_mapping(
            self._state.user_id_by_safe_username,
            committed.user_id_by_safe_username,
        )
        _replace_mapping(self._state.user_id_by_email, committed.user_id_by_email)
        _replace_set(self._state.disallowed_usernames, committed.disallowed_usernames)
        self._state.next_user_id = committed.next_user_id

        _replace_mapping(self._state.roles_by_id, committed.roles_by_id)
        _replace_mapping(self._state.role_id_by_name, committed.role_id_by_name)
        _replace_mapping(self._state.role_ids_by_user_id, committed.role_ids_by_user_id)

        _replace_mapping(self._state.channels_by_id, committed.channels_by_id)
        _replace_mapping(self._state.channel_id_by_name, committed.channel_id_by_name)
        _replace_mapping(
            self._state.channel_overrides_by_channel_id,
            committed.channel_overrides_by_channel_id,
        )
        self._state.next_channel_id = committed.next_channel_id

        _replace_mapping(self._state.scores_by_id, committed.scores_by_id)
        _replace_mapping(
            self._state.score_id_by_online_checksum,
            committed.score_id_by_online_checksum,
        )
        self._state.next_score_id = committed.next_score_id

        _replace_mapping(self._state.submissions_by_id, committed.submissions_by_id)
        _replace_mapping(
            self._state.submission_id_by_fingerprint,
            committed.submission_id_by_fingerprint,
        )
        self._state.next_submission_id = committed.next_submission_id

        _replace_mapping(self._state.replays_by_id, committed.replays_by_id)
        _replace_mapping(self._state.replay_id_by_checksum, committed.replay_id_by_checksum)
        self._state.next_replay_id = committed.next_replay_id

        _replace_mapping(self._state.blobs_by_id, committed.blobs_by_id)
        _replace_mapping(self._state.blob_id_by_sha256, committed.blob_id_by_sha256)
        self._state.next_blob_id = committed.next_blob_id

        _replace_mapping(self._state.beatmapsets_by_id, committed.beatmapsets_by_id)
        _replace_mapping(self._state.beatmaps_by_id, committed.beatmaps_by_id)
        _replace_mapping(self._state.beatmap_id_by_checksum, committed.beatmap_id_by_checksum)
        _replace_mapping(self._state.attachments_by_key, committed.attachments_by_key)
        _replace_mapping(
            self._state.attachment_keys_by_beatmap_id,
            committed.attachment_keys_by_beatmap_id,
        )
        _replace_mapping(self._state.fetch_states_by_target, committed.fetch_states_by_target)

    def seed_roles(self, roles: list[Role]) -> None:
        """Seed roles into factory state (test helper)."""
        for role in roles:
            self._state.roles_by_id[role.id] = role
            self._state.role_id_by_name[role.name] = role.id


class InMemoryUnitOfWork:
    """In-memory command transaction boundary with commit/rollback semantics."""

    users: InMemoryUserCommandRepository
    roles: InMemoryRoleCommandRepository
    channels: InMemoryChannelCommandRepository
    scores: InMemoryScoreCommandRepository
    submissions: InMemoryScoreSubmissionCommandRepository
    replays: InMemoryReplayCommandRepository
    blobs: InMemoryBlobCommandRepository
    beatmaps: InMemoryBeatmapCommandRepository

    def __init__(self, factory: InMemoryUnitOfWorkFactory) -> None:
        self._factory: InMemoryUnitOfWorkFactory = factory
        self._state: InMemoryCommandRepositoryState = factory.snapshot()
        self._committed: bool = False
        self._bind_repositories()

    async def __aenter__(self) -> Self:
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        _exc: BaseException | None,
        _traceback: TracebackType | None,
    ) -> None:
        if exc_type is not None or not self._committed:
            await self.rollback()

    async def commit(self) -> None:
        self._factory.commit_state(self._state)
        self._committed = True

    async def rollback(self) -> None:
        self._state = self._factory.snapshot()
        self._committed = False
        self._bind_repositories()

    def _bind_repositories(self) -> None:
        self.users = InMemoryUserCommandRepository(self._state)
        self.roles = InMemoryRoleCommandRepository(self._state)
        self.channels = InMemoryChannelCommandRepository(self._state)
        self.scores = InMemoryScoreCommandRepository(self._state)
        self.submissions = InMemoryScoreSubmissionCommandRepository(self._state)
        self.replays = InMemoryReplayCommandRepository(self._state)
        self.blobs = InMemoryBlobCommandRepository(self._state)
        self.beatmaps = InMemoryBeatmapCommandRepository(self._state)
