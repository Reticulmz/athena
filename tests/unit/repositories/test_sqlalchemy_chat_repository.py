"""SQLAlchemy chat command repositoryの履歴保存契約を検証する."""

from __future__ import annotations

from contextlib import AbstractAsyncContextManager
from typing import TYPE_CHECKING, cast, override

import structlog.testing
from sqlalchemy.exc import SQLAlchemyError, StatementError

from osu_server.domain.chat import ChatPersistenceFailureReason
from osu_server.repositories.sqlalchemy.commands.chat import SQLAlchemyChatCommandRepository
from osu_server.repositories.sqlalchemy.models.channel import (
    ChannelMessageModel,
    PrivateMessageModel,
)

if TYPE_CHECKING:
    from types import TracebackType

    from sqlalchemy.ext.asyncio import AsyncSession
    from sqlalchemy.sql.base import Executable


class ChannelIdResult:
    """Channel IDを返すscalar query resultの最小fakeを表す.

    Attributes:
        _channel_id (int | None): lookupで返すchannel識別子またはNone.
    """

    _channel_id: int | None

    def __init__(self, channel_id: int | None) -> None:
        """Scalar lookupで返すchannel識別子を初期化する.

        Args:
            channel_id (int | None): 解決済みchannel IDまたは未解決を表すNone.
        """
        self._channel_id = channel_id

    def scalar_one_or_none(self) -> int | None:
        """初期化時に設定したchannel識別子を返す.

        Returns:
            int | None: 解決済みchannel IDまたはNone.
        """
        return self._channel_id


class FakeSession(AbstractAsyncContextManager["FakeSession"]):
    """Database driverなしでrepository操作を再現するsession fake.

    Attributes:
        channel_id (int | None): channel name lookupで返す識別子またはNone.
        flush_error (SQLAlchemyError | None): flush時に送出するSQLAlchemy errorまたはNone.
        added (list[object]): addで受け取ったORM instanceの記録.
        execute_calls (int): execute呼出回数.
        flushes (int): 成功したflush呼出回数.
    """

    channel_id: int | None
    flush_error: SQLAlchemyError | None
    added: list[object]
    execute_calls: int
    flushes: int

    def __init__(
        self,
        *,
        channel_id: int | None = None,
        flush_error: SQLAlchemyError | None = None,
    ) -> None:
        """Lookup結果とflush failureを持つfake sessionを初期化する.

        Args:
            channel_id (int | None): channel lookupで返す識別子またはNone.
            flush_error (SQLAlchemyError | None): flush時に送出するerrorまたはNone.
        """
        self.channel_id = channel_id
        self.flush_error = flush_error
        self.added = []
        self.execute_calls = 0
        self.flushes = 0

    @override
    async def __aenter__(self) -> FakeSession:
        """Context内で利用するこのfake sessionを返す.

        Returns:
            FakeSession: contextに入った同一session instance.
        """
        return self

    @override
    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        """Context終了時のexception情報を消費して追加処理なしで完了する.

        Args:
            exc_type (type[BaseException] | None): context内で送出されたexception型またはNone.
            exc (BaseException | None): context内で送出されたexception instanceまたはNone.
            traceback (TracebackType | None): exception tracebackまたはNone.

        Returns:
            None: transaction cleanupを行わずcontext終了処理を完了する.
        """
        _ = exc_type
        _ = exc
        _ = traceback

    async def execute(self, statement: Executable) -> ChannelIdResult:
        """Channel lookup statementを実行した記録と設定済みID結果を返す.

        Args:
            statement (Executable): repositoryが発行したSQLAlchemy statement.

        Returns:
            ChannelIdResult: 初期化時に設定したchannel IDを包むscalar result.
        """
        _ = statement
        self.execute_calls += 1
        return ChannelIdResult(self.channel_id)

    def add(self, instance: object) -> None:
        """永続化対象ORM instanceを追加記録へ積む.

        Args:
            instance (object): sessionへ追加するORM instance.

        Returns:
            None: instanceを追加記録へ格納して完了する.
        """
        self.added.append(instance)

    async def flush(self) -> None:
        """設定済みerrorを送出するか成功したflush回数を増やす.

        Returns:
            None: 成功時にflush回数を1増やして完了する.

        Raises:
            SQLAlchemyError: 初期化時にflush_errorが設定されている場合.
        """
        if self.flush_error is not None:
            raise self.flush_error
        self.flushes += 1


def make_repo(session: FakeSession) -> SQLAlchemyChatCommandRepository:
    """FakeSessionを受け取るSQLAlchemy chat command repositoryを作成する.

    Args:
        session (FakeSession): AsyncSessionとして振る舞うtest double.

    Returns:
        SQLAlchemyChatCommandRepository: 指定fake sessionを使用するrepository.
    """
    return SQLAlchemyChatCommandRepository(cast("AsyncSession", cast("object", session)))


def make_statement_error(message: str) -> StatementError:
    """Logへ公開される詳細を持つSQLAlchemy statement errorを作成する.

    Args:
        message (str): error logで確認する主message.

    Returns:
        StatementError: SQLとparameterおよびoriginal errorを含むdatabase error.
    """
    return StatementError(
        message,
        "insert into private_messages",
        {"sender_id": 1, "target_user_id": 2, "content": "secret"},
        ValueError("foreign key violation"),
    )


class TestSaveChannelMessage:
    """Public channel message保存の成功と未解決channel処理を検証するtest group."""

    async def test_adds_message_with_resolved_channel_id(self) -> None:
        """解決済みchannel IDでpublic messageを保存することを検証する.

        Returns:
            None: 成功結果とsession操作および保存ORM modelのfieldを検証して完了する.
        """
        session = FakeSession(channel_id=10)
        repo = make_repo(session)

        result = await repo.save_channel_message(
            sender_id=1,
            channel_name="#osu",
            content="hello",
        )

        assert result.success is True
        assert result.reason is None
        assert session.execute_calls == 1
        assert session.flushes == 1
        assert len(session.added) == 1
        message = session.added[0]
        assert isinstance(message, ChannelMessageModel)
        assert message.sender_id == 1
        assert message.channel_id == 10
        assert message.content == "hello"

    async def test_unresolved_channel_returns_failure_without_insert(self) -> None:
        """未解決channel名でmessageを挿入せずfailureを返すことを検証する.

        Returns:
            None: CHANNEL_NOT_FOUND結果とinsert/flush不実行を検証して完了する.
        """
        session = FakeSession(channel_id=None)
        repo = make_repo(session)

        result = await repo.save_channel_message(
            sender_id=1,
            channel_name="#missing",
            content="hello",
        )

        assert result.success is False
        assert result.reason is ChatPersistenceFailureReason.CHANNEL_NOT_FOUND
        assert session.execute_calls == 1
        assert session.flushes == 0
        assert session.added == []


class TestSavePrivateMessage:
    """Private message保存の成功とstorage failure処理を検証するtest group."""

    async def test_adds_private_message(self) -> None:
        """Private messageをORM modelとして保存することを検証する.

        Returns:
            None: 成功結果とsession操作および保存modelの送受信者と本文を検証して完了する.
        """
        session = FakeSession()
        repo = make_repo(session)

        result = await repo.save_private_message(
            sender_id=1,
            target_id=2,
            content="secret",
        )

        assert result.success is True
        assert result.reason is None
        assert session.execute_calls == 0
        assert session.flushes == 1
        assert len(session.added) == 1
        message = session.added[0]
        assert isinstance(message, PrivateMessageModel)
        assert message.sender_id == 1
        assert message.target_user_id == 2
        assert message.content == "secret"

    async def test_storage_error_returns_failure(self) -> None:
        """Storage errorをfailure結果と構造化logへ変換することを検証する.

        Returns:
            None: STORAGE_ERROR結果とflush状態およびerror log fieldを検証して完了する.
        """
        session = FakeSession(flush_error=make_statement_error("storage failed"))
        repo = make_repo(session)

        with structlog.testing.capture_logs() as logs:
            result = await repo.save_private_message(
                sender_id=1,
                target_id=2,
                content="secret",
            )

        assert result.success is False
        assert result.reason is ChatPersistenceFailureReason.STORAGE_ERROR
        assert session.flushes == 0

        entries = [
            entry for entry in logs if entry.get("event") == "chat_persistence_storage_error"
        ]
        assert len(entries) == 1
        assert entries[0]["operation"] == "save_private_message"
        assert entries[0]["sender_id"] == 1
        assert entries[0]["target_id"] == 2
        assert entries[0]["reason"] == "storage_error"
        assert entries[0]["error_type"] == "StatementError"
        assert "storage failed" in entries[0]["error_message"]
        assert "StatementError" in entries[0]["error_repr"]
        assert entries[0]["sqlalchemy_code"] is None
        assert entries[0]["sqlalchemy_statement"] == "insert into private_messages"
        assert (
            entries[0]["sqlalchemy_params_repr"]
            == "{'sender_id': 1, 'target_user_id': 2, 'content': 'secret'}"
        )
        assert entries[0]["sqlalchemy_ismulti"] is None
        assert entries[0]["original_error_type"] == "ValueError"
        assert entries[0]["original_error_message"] == "foreign key violation"
