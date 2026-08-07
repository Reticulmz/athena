"""SQLAlchemyチャット永続化repositoryの障害ログ契約を検証する."""

from __future__ import annotations

from typing import TYPE_CHECKING, cast

import structlog.testing
from sqlalchemy.exc import SQLAlchemyError, StatementError

from osu_server.domain.chat import ChatPersistenceFailureReason
from osu_server.repositories.sqlalchemy.commands.chat import SQLAlchemyChatCommandRepository
from osu_server.repositories.sqlalchemy.models.channel import (
    ChannelMessageModel,
    PrivateMessageModel,
)

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession
    from sqlalchemy.sql.base import Executable


class ChannelIdResult:
    """fakeコマンドsessionが返すチャンネル識別子のscalar結果.

    Attributes:
        _channel_id (int | None): scalar取得時に返すチャンネル識別子.
    """

    def __init__(self, channel_id: int | None) -> None:
        """scalar取得結果に含めるチャンネル識別子を保持する.

        Args:
            channel_id (int | None): 見つかったチャンネルの識別子または未検出を表すNone.
        """
        self._channel_id: int | None = channel_id

    def scalar_one_or_none(self) -> int | None:
        """設定済みのチャンネル識別子をscalar結果として返す.

        Returns:
            int | None: 初期化時に設定したチャンネル識別子またはNone.
        """
        return self._channel_id


class FakeCommandSession:
    """DB driverなしでコマンドrepositoryを検証するsession fake.

    Attributes:
        channel_id (int | None): execute時にチャンネル検索結果として返す識別子.
        flush_error (SQLAlchemyError | None): flush時に送出する永続化エラー.
        added (list[object]): addで記録した永続化対象instance.
        execute_calls (int): executeの呼び出し回数.
        flush_calls (int): 成功したflushの呼び出し回数.
    """

    def __init__(
        self,
        *,
        channel_id: int | None = None,
        flush_error: SQLAlchemyError | None = None,
    ) -> None:
        """チャンネル検索結果と任意のflush障害を設定する.

        Args:
            channel_id (int | None): execute時に返すチャンネル識別子.
            flush_error (SQLAlchemyError | None): flush時に送出するSQLAlchemyエラー.
        """
        self.channel_id: int | None = channel_id
        self.flush_error: SQLAlchemyError | None = flush_error
        self.added: list[object] = []
        self.execute_calls: int = 0
        self.flush_calls: int = 0

    async def execute(self, statement: Executable) -> ChannelIdResult:
        """検索statementを記録して設定済みチャンネル結果を返す.

        Args:
            statement (Executable): repositoryが発行したチャンネル検索statement.

        Returns:
            ChannelIdResult: 設定済みチャンネル識別子を含むscalar結果.
        """
        _ = statement
        self.execute_calls += 1
        return ChannelIdResult(self.channel_id)

    def add(self, instance: object) -> None:
        """永続化対象instanceを記録する.

        Args:
            instance (object): repositoryがsessionへ追加するmodel instance.

        Returns:
            None: 実行結果を検証または記録して呼び出し側へ値を返さずに完了する.
        """
        self.added.append(instance)

    async def flush(self) -> None:
        """設定済み障害を送出するか成功回数を加算する.

        Raises:
            SQLAlchemyError: 初期化時に設定されたflush障害.

        Returns:
            None: 実行結果を検証または記録して呼び出し側へ値を返さずに完了する.
        """
        if self.flush_error is not None:
            raise self.flush_error
        self.flush_calls += 1


def make_repo(session: FakeCommandSession) -> SQLAlchemyChatCommandRepository:
    """Fake sessionを使用するチャットコマンドrepositoryを生成する.

    Args:
        session (FakeCommandSession): SQLAlchemy sessionとして扱うテストdouble.

    Returns:
        SQLAlchemyChatCommandRepository: 指定sessionへ書き込むチャットrepository.
    """
    return SQLAlchemyChatCommandRepository(cast("AsyncSession", cast("object", session)))


def make_statement_error(message: str) -> StatementError:
    """詳細ログ検証用のStatementErrorを生成する.

    Args:
        message (str): 永続化失敗としてログに含まれるエラーメッセージ.

    Returns:
        StatementError: SQLとパラメーターを保持するStatementError.
    """
    return StatementError(
        message,
        "insert into channel_messages",
        {"sender_id": 2, "content": "hello"},
        ValueError("foreign key violation"),
    )


async def test_save_channel_message_logs_storage_error_details() -> None:
    """チャンネル保存失敗がSQLAlchemy詳細を構造化ログへ出力することを検証する.

    Returns:
        None: 実行結果を検証または記録して呼び出し側へ値を返さずに完了する.
    """
    session = FakeCommandSession(
        channel_id=10,
        flush_error=make_statement_error("channel insert failed"),
    )
    repo = make_repo(session)

    with structlog.testing.capture_logs() as logs:
        result = await repo.save_channel_message(
            sender_id=2,
            channel_name="#osu",
            content="hello",
        )

    assert result.success is False
    assert result.reason is ChatPersistenceFailureReason.STORAGE_ERROR
    assert len(session.added) == 1
    assert isinstance(session.added[0], ChannelMessageModel)

    entries = [entry for entry in logs if entry.get("event") == "chat_persistence_storage_error"]
    assert len(entries) == 1
    assert entries[0]["operation"] == "save_channel_message"
    assert entries[0]["sender_id"] == 2
    assert entries[0]["channel_name"] == "#osu"
    assert entries[0]["reason"] == "storage_error"
    assert entries[0]["error_type"] == "StatementError"
    assert "channel insert failed" in entries[0]["error_message"]
    assert "StatementError" in entries[0]["error_repr"]
    assert entries[0]["sqlalchemy_code"] is None
    assert entries[0]["sqlalchemy_statement"] == "insert into channel_messages"
    assert entries[0]["sqlalchemy_params_repr"] == "{'sender_id': 2, 'content': 'hello'}"
    assert entries[0]["sqlalchemy_ismulti"] is None
    assert entries[0]["original_error_type"] == "ValueError"
    assert entries[0]["original_error_message"] == "foreign key violation"
    assert entries[0]["original_error_repr"] == "ValueError('foreign key violation')"


async def test_save_private_message_logs_storage_error_details() -> None:
    """個人メッセージ保存失敗が操作別の構造化ログを出力することを検証する.

    Returns:
        None: 実行結果を検証または記録して呼び出し側へ値を返さずに完了する.
    """
    session = FakeCommandSession(
        flush_error=SQLAlchemyError("private insert failed"),
    )
    repo = make_repo(session)

    with structlog.testing.capture_logs() as logs:
        result = await repo.save_private_message(
            sender_id=2,
            target_id=3,
            content="hello pm",
        )

    assert result.success is False
    assert result.reason is ChatPersistenceFailureReason.STORAGE_ERROR
    assert len(session.added) == 1
    assert isinstance(session.added[0], PrivateMessageModel)

    entries = [entry for entry in logs if entry.get("event") == "chat_persistence_storage_error"]
    assert len(entries) == 1
    assert entries[0]["operation"] == "save_private_message"
    assert entries[0]["sender_id"] == 2
    assert entries[0]["target_id"] == 3
    assert entries[0]["reason"] == "storage_error"
    assert entries[0]["error_type"] == "SQLAlchemyError"
