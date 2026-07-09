"""SQLAlchemy user repository の IntegrityError 分類を検証する."""

from __future__ import annotations

from typing import TYPE_CHECKING, cast, final

import pytest
from sqlalchemy.exc import IntegrityError
from tests.factories.domain import make_user

from osu_server.repositories.sqlalchemy.commands.users import SQLAlchemyUserCommandRepository

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession


@final
class _NoResult:
    """Repository の事前存在確認で未検出を返す result double."""

    def scalar_one_or_none(self) -> None:
        return None


@final
class _IntegrityErrorSession:
    """flush 時に指定された IntegrityError を送出する session double."""

    _error: IntegrityError
    added: list[object]

    def __init__(self, error: IntegrityError) -> None:
        self._error = error
        self.added = []

    async def execute(self, statement: object) -> _NoResult:
        _ = statement
        return _NoResult()

    def add(self, instance: object) -> None:
        self.added.append(instance)

    async def flush(self) -> None:
        raise self._error

    async def refresh(self, instance: object) -> None:
        _ = instance


@final
class _OriginWithConstraintError(Exception):
    """asyncpg style の constraint_name を持つ origin error."""

    constraint_name: str

    def __init__(self, constraint_name: str) -> None:
        super().__init__(f'duplicate key value violates unique constraint "{constraint_name}"')
        self.constraint_name = constraint_name


@final
class _Diagnostic:
    """psycopg style の diag.constraint_name を持つ diagnostic."""

    constraint_name: str

    def __init__(self, constraint_name: str) -> None:
        self.constraint_name = constraint_name


@final
class _OriginWithDiagnosticError(Exception):
    """psycopg style の diag を持つ origin error."""

    diag: _Diagnostic

    def __init__(self, constraint_name: str) -> None:
        super().__init__(f'duplicate key value violates unique constraint "{constraint_name}"')
        self.diag = _Diagnostic(constraint_name)


async def test_primary_key_error_is_not_misclassified_as_username_conflict() -> None:
    """INSERT 文に safe_username が含まれても pkey 衝突は username 扱いしない."""
    error = IntegrityError(
        "INSERT INTO users (username, safe_username, email) VALUES ($1, $2, $3)",
        {"safe_username": "remiaaaaa"},
        _OriginWithConstraintError("users_pkey"),
    )
    repository = _repository_for_error(error)

    with pytest.raises(ValueError, match=r"^user uniqueness constraint failed$") as exc_info:
        _ = await repository.create(make_user(username="Remiaaaaa"))

    assert str(exc_info.value) == "user uniqueness constraint failed"


async def test_safe_username_constraint_is_reported_as_username_conflict() -> None:
    """safe_username unique constraint は username conflict に変換する."""
    error = IntegrityError(
        "INSERT INTO users (username, safe_username, email) VALUES ($1, $2, $3)",
        {"safe_username": "remiaaaaa"},
        _OriginWithConstraintError("users_safe_username_key"),
    )
    repository = _repository_for_error(error)

    with pytest.raises(ValueError, match=r"^safe_username already exists: remiaaaaa$") as exc_info:
        _ = await repository.create(make_user(username="Remiaaaaa"))

    assert str(exc_info.value) == "safe_username already exists: remiaaaaa"


async def test_email_constraint_from_diag_is_reported_as_email_conflict() -> None:
    """diag.constraint_name 由来の email unique constraint を email conflict に変換する."""
    error = IntegrityError(
        "INSERT INTO users (username, safe_username, email) VALUES ($1, $2, $3)",
        {"email": "remi@example.com"},
        _OriginWithDiagnosticError("users_email_key"),
    )
    repository = _repository_for_error(error)

    with pytest.raises(ValueError, match=r"^email already exists: remi@example.com$") as exc_info:
        _ = await repository.create(make_user(email="remi@example.com"))

    assert str(exc_info.value) == "email already exists: remi@example.com"


def _repository_for_error(error: IntegrityError) -> SQLAlchemyUserCommandRepository:
    session = cast("AsyncSession", cast("object", _IntegrityErrorSession(error)))
    return SQLAlchemyUserCommandRepository(session)
