"""Tests for channel command and query repository memory adapters."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from osu_server.domain.chat.channels import Channel, ChannelType
from osu_server.repositories.interfaces.commands.channels import ChannelCommandRepository
from osu_server.repositories.memory.commands.channels import InMemoryChannelCommandRepository
from osu_server.repositories.memory.commands.state import InMemoryCommandRepositoryState
from osu_server.repositories.memory.queries.channels import InMemoryChannelQueryRepository
from osu_server.repositories.memory.unit_of_work import InMemoryUnitOfWorkFactory


def _make_channel(
    *,
    id: int = 0,  # noqa: A002
    name: str = "#osu",
    topic: str = "General discussion",
    channel_type: ChannelType = ChannelType.PUBLIC,
    auto_join: bool = False,
    rate_limit_messages: int | None = None,
    rate_limit_window: int | None = None,
) -> Channel:
    """Create a Channel with sensible defaults for testing."""
    now = datetime.now(UTC)
    return Channel(
        id=id,
        name=name,
        topic=topic,
        channel_type=channel_type,
        auto_join=auto_join,
        rate_limit_messages=rate_limit_messages,
        rate_limit_window=rate_limit_window,
        created_at=now,
        updated_at=now,
    )


@pytest.fixture
def command_state() -> InMemoryCommandRepositoryState:
    return InMemoryCommandRepositoryState()


@pytest.fixture
def repo(command_state: InMemoryCommandRepositoryState) -> InMemoryChannelCommandRepository:
    return InMemoryChannelCommandRepository(command_state)


@pytest.fixture
def query_repo(command_state: InMemoryCommandRepositoryState) -> InMemoryChannelQueryRepository:
    return InMemoryChannelQueryRepository(InMemoryUnitOfWorkFactory(command_state))


class TestProtocolConformance:
    """InMemoryChannelCommandRepository satisfies ChannelCommandRepository."""

    def test_is_instance_of_protocol(self, repo: InMemoryChannelCommandRepository) -> None:
        assert isinstance(repo, ChannelCommandRepository)


class TestCreate:
    """create() stores a channel and returns it with an auto-generated id."""

    async def test_returns_channel_with_generated_id(
        self, repo: InMemoryChannelCommandRepository
    ) -> None:
        channel = _make_channel()

        created = await repo.create(channel)

        assert created.id > 0
        assert created.name == "#osu"
        assert created.topic == "General discussion"

    async def test_preserves_all_fields(self, repo: InMemoryChannelCommandRepository) -> None:
        channel = _make_channel(
            name="#staff",
            topic="Staff only",
            auto_join=True,
            rate_limit_messages=5,
            rate_limit_window=10,
        )

        created = await repo.create(channel)

        assert created.name == "#staff"
        assert created.topic == "Staff only"
        assert created.channel_type == ChannelType.PUBLIC
        assert created.auto_join is True
        assert created.rate_limit_messages == 5
        assert created.rate_limit_window == 10

    async def test_auto_increment_ids(self, repo: InMemoryChannelCommandRepository) -> None:
        ch_a = await repo.create(_make_channel(name="#osu"))
        ch_b = await repo.create(_make_channel(name="#announce"))

        assert ch_a.id == 1
        assert ch_b.id == 2

    async def test_duplicate_name_raises(self, repo: InMemoryChannelCommandRepository) -> None:
        _ = await repo.create(_make_channel(name="#osu"))

        with pytest.raises(ValueError, match="channel name already exists"):
            _ = await repo.create(_make_channel(name="#osu"))


class TestGetByName:
    """get_by_name() retrieves a channel by its name."""

    async def test_found(
        self,
        repo: InMemoryChannelCommandRepository,
        query_repo: InMemoryChannelQueryRepository,
    ) -> None:
        _ = await repo.create(_make_channel(name="#osu"))

        result = await query_repo.get_by_name("#osu")

        assert result is not None
        assert result.name == "#osu"

    async def test_not_found_returns_none(
        self, query_repo: InMemoryChannelQueryRepository
    ) -> None:
        result = await query_repo.get_by_name("#nonexistent")

        assert result is None


class TestGetAll:
    """get_all() returns only PUBLIC channels."""

    async def test_returns_public_channels(
        self,
        repo: InMemoryChannelCommandRepository,
        query_repo: InMemoryChannelQueryRepository,
    ) -> None:
        _ = await repo.create(_make_channel(name="#osu"))
        _ = await repo.create(_make_channel(name="#announce"))

        result = await query_repo.get_all()

        assert len(result) == 2
        names = {ch.name for ch in result}
        assert names == {"#osu", "#announce"}

    async def test_excludes_non_public_channels(
        self,
        repo: InMemoryChannelCommandRepository,
        query_repo: InMemoryChannelQueryRepository,
    ) -> None:
        _ = await repo.create(_make_channel(name="#osu", channel_type=ChannelType.PUBLIC))
        _ = await repo.create(_make_channel(name="#mp-1", channel_type=ChannelType.MULTIPLAYER))
        _ = await repo.create(_make_channel(name="#spec-1", channel_type=ChannelType.SPECTATOR))

        result = await query_repo.get_all()

        assert len(result) == 1
        assert result[0].name == "#osu"

    async def test_empty_when_no_channels(
        self, query_repo: InMemoryChannelQueryRepository
    ) -> None:
        result = await query_repo.get_all()

        assert result == []


class TestGetAutoJoin:
    """get_auto_join() returns only channels with auto_join=True."""

    async def test_returns_auto_join_channels(
        self,
        repo: InMemoryChannelCommandRepository,
        query_repo: InMemoryChannelQueryRepository,
    ) -> None:
        _ = await repo.create(_make_channel(name="#osu", auto_join=True))
        _ = await repo.create(_make_channel(name="#staff", auto_join=False))

        result = await query_repo.get_auto_join()

        assert len(result) == 1
        assert result[0].name == "#osu"

    async def test_empty_when_none_auto_join(
        self,
        repo: InMemoryChannelCommandRepository,
        query_repo: InMemoryChannelQueryRepository,
    ) -> None:
        _ = await repo.create(_make_channel(name="#osu", auto_join=False))

        result = await query_repo.get_auto_join()

        assert result == []


class TestUpdate:
    """update() modifies an existing channel."""

    async def test_updates_fields(self, repo: InMemoryChannelCommandRepository) -> None:
        created = await repo.create(_make_channel(name="#osu", topic="Old topic"))
        modified = Channel(
            id=created.id,
            name=created.name,
            topic="New topic",
            channel_type=created.channel_type,
            auto_join=True,
            rate_limit_messages=created.rate_limit_messages,
            rate_limit_window=created.rate_limit_window,
            created_at=created.created_at,
            updated_at=created.updated_at,
        )

        updated = await repo.update(modified)

        assert updated.topic == "New topic"
        assert updated.auto_join is True

    async def test_updates_name_with_index(
        self,
        repo: InMemoryChannelCommandRepository,
        query_repo: InMemoryChannelQueryRepository,
    ) -> None:
        created = await repo.create(_make_channel(name="#osu"))
        modified = Channel(
            id=created.id,
            name="#general",
            topic=created.topic,
            channel_type=created.channel_type,
            auto_join=created.auto_join,
            rate_limit_messages=created.rate_limit_messages,
            rate_limit_window=created.rate_limit_window,
            created_at=created.created_at,
            updated_at=created.updated_at,
        )

        _ = await repo.update(modified)

        assert await query_repo.get_by_name("#general") is not None
        assert await query_repo.get_by_name("#osu") is None

    async def test_name_conflict_raises(self, repo: InMemoryChannelCommandRepository) -> None:
        created = await repo.create(_make_channel(name="#osu"))
        _ = await repo.create(_make_channel(name="#announce"))

        modified = Channel(
            id=created.id,
            name="#announce",
            topic=created.topic,
            channel_type=created.channel_type,
            auto_join=created.auto_join,
            rate_limit_messages=created.rate_limit_messages,
            rate_limit_window=created.rate_limit_window,
            created_at=created.created_at,
            updated_at=created.updated_at,
        )

        with pytest.raises(ValueError, match="channel name already exists"):
            _ = await repo.update(modified)

    async def test_nonexistent_raises(self, repo: InMemoryChannelCommandRepository) -> None:
        channel = _make_channel(name="#ghost")
        channel = Channel(
            id=9999,
            name=channel.name,
            topic=channel.topic,
            channel_type=channel.channel_type,
            auto_join=channel.auto_join,
            rate_limit_messages=channel.rate_limit_messages,
            rate_limit_window=channel.rate_limit_window,
            created_at=channel.created_at,
            updated_at=channel.updated_at,
        )

        with pytest.raises(ValueError, match="channel not found"):
            _ = await repo.update(channel)


class TestDelete:
    """delete() removes a channel by id."""

    async def test_removes_channel(
        self,
        repo: InMemoryChannelCommandRepository,
        query_repo: InMemoryChannelQueryRepository,
    ) -> None:
        created = await repo.create(_make_channel(name="#osu"))

        await repo.delete(created.id)

        assert await query_repo.get_by_name("#osu") is None

    async def test_removes_name_index(self, repo: InMemoryChannelCommandRepository) -> None:
        created = await repo.create(_make_channel(name="#osu"))

        await repo.delete(created.id)

        # Name should be available for reuse
        recreated = await repo.create(_make_channel(name="#osu"))
        assert recreated.id != created.id

    async def test_nonexistent_is_noop(self, repo: InMemoryChannelCommandRepository) -> None:
        await repo.delete(9999)  # Should not raise
