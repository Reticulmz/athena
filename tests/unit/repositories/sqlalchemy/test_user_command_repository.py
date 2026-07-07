"""Tests for SQLAlchemy user command repository."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import TYPE_CHECKING, cast, final

from osu_server.repositories.sqlalchemy.commands.users import SQLAlchemyUserCommandRepository
from osu_server.repositories.sqlalchemy.models.user import UserModel

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

_CREATED_AT = datetime(2026, 7, 1, tzinfo=UTC)
_OLD_ACTIVITY = datetime(2026, 7, 2, tzinfo=UTC)
_NEW_ACTIVITY = datetime(2026, 7, 3, tzinfo=UTC)


@final
class FakeSession:
    """Minimal AsyncSession substitute for user command checks."""

    def __init__(self, model: UserModel | None) -> None:
        self._model: UserModel | None = model
        self.flushes: int = 0
        self.get_calls: list[tuple[type[object], object]] = []

    async def get(self, model_type: type[object], identity: object) -> object | None:
        self.get_calls.append((model_type, identity))
        return self._model

    async def flush(self) -> None:
        self.flushes += 1


async def test_touch_latest_activity_updates_existing_user() -> None:
    model = _user_model(latest_activity_at=_OLD_ACTIVITY)
    session = FakeSession(model)
    repository = SQLAlchemyUserCommandRepository(cast("AsyncSession", cast("object", session)))

    touched = await repository.touch_latest_activity(42, _NEW_ACTIVITY)

    assert touched is True
    assert model.latest_activity_at == _NEW_ACTIVITY
    assert model.created_at == _CREATED_AT
    assert session.flushes == 1
    assert session.get_calls == [(UserModel, 42)]


async def test_touch_latest_activity_returns_false_when_user_missing() -> None:
    session = FakeSession(None)
    repository = SQLAlchemyUserCommandRepository(cast("AsyncSession", cast("object", session)))

    touched = await repository.touch_latest_activity(404, _NEW_ACTIVITY)

    assert touched is False
    assert session.flushes == 0
    assert session.get_calls == [(UserModel, 404)]


def _user_model(*, latest_activity_at: datetime) -> UserModel:
    return UserModel(
        id=42,
        username="User",
        safe_username="user",
        email="user@example.com",
        password_hash="hash",
        country="JP",
        created_at=_CREATED_AT,
        updated_at=_CREATED_AT,
        latest_activity_at=latest_activity_at,
    )
