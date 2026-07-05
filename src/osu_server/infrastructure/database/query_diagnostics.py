"""SQLAlchemy SQL query diagnostics listener."""

from __future__ import annotations

from threading import Lock
from typing import Protocol
from weakref import WeakSet

from sqlalchemy import event

from osu_server.shared.query_diagnostics import record_query


class _HasSyncEngine(Protocol):
    @property
    def sync_engine(self) -> object: ...


_installed_sync_engines: WeakSet[object] = WeakSet()
_installed_sync_engines_lock = Lock()


def install_query_diagnostics(engine: _HasSyncEngine) -> None:
    """AsyncEngine の sync engine に SQLAlchemy cursor event listener を登録する.

    Args:
        engine: sync_engine 属性を持つ SQLAlchemy async engine.

    Returns:
        なし.

    Constraints:
        同じ sync engine には listener を一度だけ登録する.
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
    record_query(statement, parameters=parameters)
