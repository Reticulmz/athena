"""SQLAlchemyユーザーコマンドrepositoryの活動時刻更新を検証する."""

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
    """ユーザーコマンドrepository検証用の最小AsyncSession double.

    Attributes:
        _model (UserModel | None): getで返すユーザーmodelまたは未検出を表すNone.
        flushes (int): flushの呼び出し回数.
        get_calls (list[tuple[type[object], object]]): getに渡されたmodel型と識別子の記録.
    """

    def __init__(self, model: UserModel | None) -> None:
        """getが返すユーザーmodelを設定する.

        Args:
            model (UserModel | None): 既存ユーザーのmodelまたは未検出を表すNone.
        """
        self._model: UserModel | None = model
        self.flushes: int = 0
        self.get_calls: list[tuple[type[object], object]] = []

    async def get(self, model_type: type[object], identity: object) -> object | None:
        """検索条件を記録して設定済みmodelを返す.

        Args:
            model_type (type[object]): repositoryが検索する永続化model型.
            identity (object): repositoryが検索する主キー識別子.

        Returns:
            object | None: 設定済みユーザーmodelまたはNone.
        """
        self.get_calls.append((model_type, identity))
        return self._model

    async def flush(self) -> None:
        """flush呼び出し回数を記録する.

        Returns:
            None: 実行結果を検証または記録して呼び出し側へ値を返さずに完了する.
        """
        self.flushes += 1


async def test_touch_latest_activity_updates_existing_user() -> None:
    """既存ユーザーの活動時刻更新がflushされ真を返すことを検証する.

    Returns:
        None: 実行結果を検証または記録して呼び出し側へ値を返さずに完了する.
    """
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
    """未検出ユーザーの活動時刻更新がflushせず偽を返すことを検証する.

    Returns:
        None: 実行結果を検証または記録して呼び出し側へ値を返さずに完了する.
    """
    session = FakeSession(None)
    repository = SQLAlchemyUserCommandRepository(cast("AsyncSession", cast("object", session)))

    touched = await repository.touch_latest_activity(404, _NEW_ACTIVITY)

    assert touched is False
    assert session.flushes == 0
    assert session.get_calls == [(UserModel, 404)]


def _user_model(*, latest_activity_at: datetime) -> UserModel:
    """活動時刻更新テスト用のユーザー永続化modelを生成する.

    Args:
        latest_activity_at (datetime): modelへ設定する既存の最終活動時刻.

    Returns:
        UserModel: 固定識別子と作成時刻を持つユーザーmodel.
    """
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
