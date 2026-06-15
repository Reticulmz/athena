"""Tests for the SQLAlchemy command Unit of Work."""

from __future__ import annotations

import ast
from contextlib import AbstractAsyncContextManager
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING, cast, override

import pytest
from tests.factories.domain import make_channel, make_user

from osu_server.repositories.sqlalchemy.commands import (
    SQLAlchemyBeatmapCommandRepository,
    SQLAlchemyBlobCommandRepository,
    SQLAlchemyChannelCommandRepository,
    SQLAlchemyChatCommandRepository,
    SQLAlchemyReplayCommandRepository,
    SQLAlchemyRoleCommandRepository,
    SQLAlchemyScoreCommandRepository,
    SQLAlchemyScoreSubmissionCommandRepository,
    SQLAlchemyUserCommandRepository,
)
from osu_server.repositories.sqlalchemy.models.channel import ChannelModel
from osu_server.repositories.sqlalchemy.models.user import UserModel
from osu_server.repositories.sqlalchemy.unit_of_work import (
    SQLAlchemyCommandSessionFactory,
    SQLAlchemyUnitOfWorkFactory,
)

if TYPE_CHECKING:
    from types import TracebackType

    from sqlalchemy.ext.asyncio import AsyncSession
    from sqlalchemy.sql.base import Executable

PROJECT_ROOT = Path(__file__).parents[3]
COMMAND_ROOT = PROJECT_ROOT / "src" / "osu_server" / "repositories" / "sqlalchemy" / "commands"
_NOW = datetime(2026, 6, 14, tzinfo=UTC)


class FakeResult:
    """Small SQLAlchemy result double for command repository checks."""

    _value: object | None
    _values: list[object]

    def __init__(self, value: object | None = None, values: list[object] | None = None) -> None:
        self._value = value
        self._values = values or []

    def scalar_one_or_none(self) -> object | None:
        return self._value

    def scalars(self) -> FakeResult:
        return self

    def all(self) -> list[object]:
        return self._values


class FakeSession(AbstractAsyncContextManager["FakeSession"]):
    """AsyncSession-shaped fake that records transaction ownership."""

    added: list[object]
    commits: int
    rollbacks: int
    flushes: int
    refreshed: list[object]
    closed: bool
    _next_user_id: int
    _next_channel_id: int
    _get_results: dict[tuple[type[object], object], object]

    def __init__(
        self,
        *,
        get_results: dict[tuple[type[object], object], object] | None = None,
    ) -> None:
        self.added = []
        self.commits = 0
        self.rollbacks = 0
        self.flushes = 0
        self.refreshed = []
        self.closed = False
        self._next_user_id = 10
        self._next_channel_id = 20
        self._get_results = get_results or {}

    @override
    async def __aenter__(self) -> FakeSession:
        return self

    @override
    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        _ = exc_type
        _ = exc
        _ = traceback
        await self.close()

    async def get(self, model_type: type[object], identity: object) -> object | None:
        return self._get_results.get((model_type, identity))

    async def execute(self, statement: Executable) -> FakeResult:
        _ = statement
        return FakeResult()

    async def merge(self, instance: object) -> object:
        self.added.append(instance)
        return instance

    def add(self, instance: object) -> None:
        self.added.append(instance)

    async def delete(self, instance: object) -> None:
        self.added.remove(instance)

    async def flush(self) -> None:
        self.flushes += 1
        for instance in self.added:
            if isinstance(instance, UserModel) and getattr(instance, "id", None) is None:
                instance.id = self._next_user_id
                self._next_user_id += 1
                instance.created_at = _NOW
                instance.updated_at = _NOW
            if isinstance(instance, ChannelModel) and getattr(instance, "id", None) is None:
                instance.id = self._next_channel_id
                self._next_channel_id += 1
                instance.created_at = _NOW
                instance.updated_at = _NOW

    async def refresh(self, instance: object) -> None:
        self.refreshed.append(instance)

    async def commit(self) -> None:
        self.commits += 1

    async def rollback(self) -> None:
        self.rollbacks += 1

    async def close(self) -> None:
        self.closed = True


class FakeSessionFactory:
    _session: FakeSession

    def __init__(self, session: FakeSession) -> None:
        self._session = session

    def __call__(self) -> AsyncSession:
        return cast("AsyncSession", cast("object", self._session))


def _factory(session: FakeSession) -> SQLAlchemyUnitOfWorkFactory:
    session_factory = cast("SQLAlchemyCommandSessionFactory", FakeSessionFactory(session))
    return SQLAlchemyUnitOfWorkFactory(session_factory)


async def test_commit_persists_multi_repository_outcome_once_through_unit_of_work() -> None:
    session = FakeSession()
    factory = _factory(session)

    async with factory() as uow:
        created_user = await uow.users.create(
            make_user(username="SQL User", email="sql@example.com")
        )
        created_channel = await uow.channels.create(make_channel(name="#sql"))

        assert created_user.id == 10
        assert created_channel.id == 20
        assert session.commits == 0
        assert session.rollbacks == 0

        await uow.commit()

    assert session.commits == 1
    assert session.rollbacks == 0
    assert session.closed is True
    assert any(isinstance(model, UserModel) for model in session.added)
    assert any(isinstance(model, ChannelModel) for model in session.added)


async def test_exception_rolls_back_uncommitted_sqlalchemy_command_changes() -> None:
    session = FakeSession()
    factory = _factory(session)

    with pytest.raises(RuntimeError, match="abort command"):
        await _raise_after_command_mutation(factory)

    assert session.commits == 0
    assert session.rollbacks == 1
    assert session.closed is True


async def test_unit_of_work_exposes_typed_sqlalchemy_command_repositories() -> None:
    factory = _factory(FakeSession())

    async with factory() as uow:
        assert isinstance(uow.users, SQLAlchemyUserCommandRepository)
        assert isinstance(uow.roles, SQLAlchemyRoleCommandRepository)
        assert isinstance(uow.channels, SQLAlchemyChannelCommandRepository)
        assert isinstance(uow.chat, SQLAlchemyChatCommandRepository)
        assert isinstance(uow.scores, SQLAlchemyScoreCommandRepository)
        assert isinstance(uow.submissions, SQLAlchemyScoreSubmissionCommandRepository)
        assert isinstance(uow.replays, SQLAlchemyReplayCommandRepository)
        assert isinstance(uow.blobs, SQLAlchemyBlobCommandRepository)
        assert isinstance(uow.beatmaps, SQLAlchemyBeatmapCommandRepository)


async def test_user_command_repository_updates_password_hash_without_commit() -> None:
    user = UserModel(
        id=3,
        username="SQLUser",
        safe_username="sqluser",
        email="sql@example.com",
        password_hash="old-hash",
        country="JP",
    )
    session = FakeSession(get_results={(UserModel, 3): user})
    repo = SQLAlchemyUserCommandRepository(cast("AsyncSession", cast("object", session)))

    updated = await repo.update_password_hash(3, "new-hash")

    assert updated is True
    assert user.password_hash == "new-hash"
    assert session.flushes == 1
    assert session.commits == 0
    assert session.rollbacks == 0


def test_sqlalchemy_command_repositories_do_not_commit_or_rollback_per_method() -> None:
    violations: list[str] = []
    for path in sorted(COMMAND_ROOT.glob("*.py")):
        if path.name == "__init__.py":
            continue
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            if not isinstance(node.func, ast.Attribute):
                continue
            if node.func.attr in {"commit", "rollback"}:
                violations.append(f"{path.relative_to(PROJECT_ROOT)} calls {node.func.attr}()")

    assert violations == []


async def _raise_after_command_mutation(factory: SQLAlchemyUnitOfWorkFactory) -> None:
    async with factory() as uow:
        _ = await uow.users.create(
            make_user(username="Rollback SQL", email="rollback-sql@example.com")
        )
        raise RuntimeError("abort command")
