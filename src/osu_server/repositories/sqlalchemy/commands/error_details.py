"""Structured SQLAlchemy exception details for command repository logs."""

from __future__ import annotations

from sqlalchemy.exc import DBAPIError, SQLAlchemyError, StatementError


def sqlalchemy_error_details(exc: SQLAlchemyError) -> dict[str, object]:
    """Return searchable SQLAlchemy exception details for structured logs."""
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
