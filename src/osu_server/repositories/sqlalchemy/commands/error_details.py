"""command repository log向けのSQLAlchemy例外詳細を提供する."""

from __future__ import annotations

from sqlalchemy.exc import DBAPIError, SQLAlchemyError, StatementError


def sqlalchemy_error_details(exc: SQLAlchemyError) -> dict[str, object]:
    """構造化logへ追加するSQLAlchemy例外の検索可能な詳細を作る.

    Args:
        exc (SQLAlchemyError): 詳細化するSQLAlchemy例外.

    Returns:
        dict[str, object]: 例外型とmessageを含むlog field. StatementErrorではSQLと原例外も含む.

    Notes:
        このhelperは例外を送出せず機密値のmaskも行わない. 呼び出し側がlog出力範囲を決める.
    """
    details: dict[str, object] = {
        "error_type": type(exc).__name__,
        "error_message": str(exc),
        "error_repr": repr(exc),
        "sqlalchemy_code": exc.code,
    }

    if isinstance(exc, StatementError):
        details["sqlalchemy_statement"] = exc.statement
        details["sqlalchemy_params_repr"] = repr(exc.params)
        details["sqlalchemy_ismulti"] = exc.ismulti

        if exc.orig is not None:
            details["original_error_type"] = type(exc.orig).__name__
            details["original_error_message"] = str(exc.orig)
            details["original_error_repr"] = repr(exc.orig)

    if isinstance(exc, DBAPIError):
        details["connection_invalidated"] = exc.connection_invalidated

    return details
