"""SQLAlchemy query実行をshared diagnosticsへ記録するlistenerを提供するmodule.

engineごとにcursor event listenerを一度だけ登録し, 実行SQLとparameterを観測可能にする.
"""

from __future__ import annotations

from threading import Lock
from typing import Protocol
from weakref import WeakSet

from sqlalchemy import event

from osu_server.shared.query_diagnostics import record_query


class _HasSyncEngine(Protocol):
    """SQLAlchemy event登録に必要な同期engineを公開するProtocol.

    Attributes:
        sync_engine (object): cursor event listenerを登録するSQLAlchemy同期engine.
    """

    @property
    def sync_engine(self) -> object:
        """Event listenerを登録する同期engineを返す.

        Returns:
            object: SQLAlchemy event APIが受け付ける同期engine object.
        """
        ...


_installed_sync_engines: WeakSet[object] = WeakSet()
_installed_sync_engines_lock = Lock()


def install_query_diagnostics(engine: _HasSyncEngine) -> None:
    """Async engineのsync engineにSQLAlchemy cursor event listenerを登録する.

    Args:
        engine (_HasSyncEngine): ``sync_engine``属性を持つSQLAlchemy async engine.

    Returns:
        None: listener登録済みの場合を含めて値を返さない.

    Notes:
        同じsync engineへlistenerを重複登録しない.
    """
    sync_engine = engine.sync_engine
    with _installed_sync_engines_lock:
        if sync_engine in _installed_sync_engines:
            return
        event.listen(sync_engine, "before_cursor_execute", _before_cursor_execute)
        _installed_sync_engines.add(sync_engine)


def _before_cursor_execute(
    _conn: object,
    _cursor: object,
    statement: str,
    parameters: object,
    _context: object,
    _executemany: bool,
) -> None:
    """cursor実行直前のSQLとparameterをquery diagnosticsへ渡す.

    Args:
        _conn (object): SQLAlchemy connection. diagnosticsには使用しない.
        _cursor (object): DBAPI cursor. diagnosticsには使用しない.
        statement (str): 実行直前のSQL statement.
        parameters (object): statementへ渡すparameter.
        _context (object): SQLAlchemy execution context. diagnosticsには使用しない.
        _executemany (bool): executemany実行かどうか. diagnosticsには使用しない.

    Returns:
        None: queryを記録するだけで値を返さない.
    """
    record_query(statement, parameters=parameters)
