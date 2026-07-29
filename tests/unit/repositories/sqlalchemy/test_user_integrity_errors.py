"""SQLAlchemyユーザーrepositoryのIntegrityError分類を検証する."""

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
    """repositoryの事前存在確認で未検出を返すresult double."""

    def scalar_one_or_none(self) -> None:
        """単一行取得結果が存在しないことを返す.

        Returns:
            事前存在確認で対象ユーザーが見つからなかったことを表す None.
        """


@final
class _IntegrityErrorSession:
    """flush時に指定されたIntegrityErrorを送出するsession double.

    Attributes:
        _error (IntegrityError): flush時に送出する永続化エラー.
        added (list[object]): addで記録した永続化対象instance.
    """

    _error: IntegrityError
    added: list[object]

    def __init__(self, error: IntegrityError) -> None:
        """Flush時に送出するIntegrityErrorを保持する.

        Args:
            error (IntegrityError): repository.create()のflushで送出する永続化エラー.
        """
        self._error = error
        self.added = []

    async def execute(self, statement: object) -> _NoResult:
        """事前存在確認 query に対して未検出の result double を返す.

        Args:
            statement (object): repositoryが発行したSQLAlchemy statement.

        Returns:
            _NoResult: scalar_one_or_none()がNoneを返すresult double.
        """
        _ = statement
        return _NoResult()

    def add(self, instance: object) -> None:
        """追加対象 instance を記録する.

        Args:
            instance (object): repositoryがsessionに追加するSQLAlchemy model instance.

        Returns:
            None: instanceを記録して呼び出し側へ値を返さずに完了する.
        """
        self.added.append(instance)

    async def flush(self) -> None:
        """Flush失敗として設定済みIntegrityErrorを送出する.

        Returns:
            None: 処理を完了し, 呼び出し側へ値を返さない.

        Raises:
            IntegrityError: このdoubleの初期化時に渡された永続化エラー.
        """
        raise self._error

    async def refresh(self, instance: object) -> None:
        """Refresh対象instanceを受け取り何も変更せずに終了する.

        Args:
            instance (object): repositoryがrefreshしようとしたSQLAlchemy model instance.

        Returns:
            None: instanceを変更せず呼び出し側へ値を返さずに完了する.
        """
        _ = instance


@final
class _OriginWithConstraintError(Exception):
    """asyncpg形式のconstraint_nameを持つorigin error.

    Attributes:
        constraint_name (str): 一意性違反を示すdatabase制約名.
    """

    constraint_name: str

    def __init__(self, constraint_name: str) -> None:
        """一意性違反を表すconstraint名を持つエラーを初期化する.

        Args:
            constraint_name (str): PostgreSQLが返した一意性制約名.
        """
        super().__init__(f'duplicate key value violates unique constraint "{constraint_name}"')
        self.constraint_name = constraint_name


@final
class _Diagnostic:
    """psycopg形式のdiag.constraint_nameを持つdiagnostic.

    Attributes:
        constraint_name (str): 一意性違反を示すdatabase制約名.
    """

    constraint_name: str

    def __init__(self, constraint_name: str) -> None:
        """Psycopg diagnosticが公開するconstraint名を初期化する.

        Args:
            constraint_name (str): PostgreSQLが返した一意性制約名.
        """
        self.constraint_name = constraint_name


@final
class _OriginWithDiagnosticError(Exception):
    """psycopg形式のdiagを持つorigin error.

    Attributes:
        diag (_Diagnostic): database制約名を公開するdiagnostic.
    """

    diag: _Diagnostic

    def __init__(self, constraint_name: str) -> None:
        """一意性違反のconstraint名を含むpsycopg形式エラーを初期化する.

        Args:
            constraint_name (str): PostgreSQLが返した一意性制約名.
        """
        super().__init__(f'duplicate key value violates unique constraint "{constraint_name}"')
        self.diag = _Diagnostic(constraint_name)


async def test_primary_key_error_is_not_misclassified_as_username_conflict() -> None:
    """safe_usernameを含むINSERTでも主キー衝突をusername競合にしないことを検証する.

    Returns:
        None: 実行結果を検証または記録して呼び出し側へ値を返さずに完了する.
    """
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
    """safe_username一意制約をusername競合のValueErrorへ変換することを検証する.

    Returns:
        None: 実行結果を検証または記録して呼び出し側へ値を返さずに完了する.
    """
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
    """diag.constraint_name由来のemail一意制約をemail競合へ変換することを検証する.

    Returns:
        None: 実行結果を検証または記録して呼び出し側へ値を返さずに完了する.
    """
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
    """指定IntegrityErrorをflushで送出するユーザーrepositoryを生成する.

    Args:
        error (IntegrityError): repository.createのflushで発生させる一意性エラー.

    Returns:
        SQLAlchemyUserCommandRepository: 指定エラーを送出するsessionを使用するユーザーrepository.
    """
    session = cast("AsyncSession", cast("object", _IntegrityErrorSession(error)))
    return SQLAlchemyUserCommandRepository(session)
