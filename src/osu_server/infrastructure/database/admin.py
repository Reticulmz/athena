"""local development用のPostgreSQL database管理補助を提供するmodule.

test databaseの作成に必要なURL変換, identifier quoting, 存在確認を収める.
"""

from __future__ import annotations

from sqlalchemy import text
from sqlalchemy.engine import URL, make_url
from sqlalchemy.ext.asyncio import create_async_engine

_MAINTENANCE_DATABASE = "postgres"


def to_asyncpg_url(database_url: str) -> URL:
    """PostgreSQL URLをasyncpg driver付きSQLAlchemy URLへ変換する.

    Args:
        database_url (str): PostgreSQL接続先を表すURL.

    Returns:
        URL: ``postgresql+asyncpg`` driverを使うSQLAlchemy URL.

    Raises:
        sqlalchemy.exc.ArgumentError: ``database_url``が空または不正で、
            ``make_url``が解析できない場合.
        ValueError: PostgreSQL以外のdriverを含むURLが渡された場合.
    """
    url = make_url(database_url)
    if url.drivername in {"postgres", "postgresql"}:
        return url.set(drivername="postgresql+asyncpg")
    if url.drivername == "postgresql+asyncpg":
        return url
    msg = f"Unsupported database driver for PostgreSQL admin task: {url.drivername}"
    raise ValueError(msg)


def maintenance_url_for(database_url: str) -> tuple[URL, str]:
    """対象databaseを作成するためのmaintenance URLとdatabase名を返す.

    Args:
        database_url (str): 作成対象を含むPostgreSQL接続URL.

    Returns:
        tuple[URL, str]: ``postgres`` databaseへのasyncpg URLと対象database名.

    Raises:
        sqlalchemy.exc.ArgumentError: 空または不正な``database_url``を
            ``to_asyncpg_url``から伝播する場合.
        ValueError: URLのdriverがPostgreSQLではないか, database名を含まない場合.
    """
    target_url = to_asyncpg_url(database_url)
    target_database = target_url.database
    if not target_database:
        msg = "DATABASE_URL must include a database name"
        raise ValueError(msg)
    return target_url.set(database=_MAINTENANCE_DATABASE), target_database


def quote_identifier(identifier: str) -> str:
    """PostgreSQL DDLで安全に使えるようidentifierをdouble quoteで囲む.

    Args:
        identifier (str): quoteするPostgreSQL identifier.

    Returns:
        str: 内部のdouble quoteをescapeしたquoted identifier.

    Raises:
        ValueError: identifierにNUL byteが含まれる場合.
    """
    if "\x00" in identifier:
        msg = "PostgreSQL identifiers cannot contain NUL bytes"
        raise ValueError(msg)
    escaped = identifier.replace('"', '""')
    return f'"{escaped}"'


async def create_database_if_missing(database_url: str) -> bool:
    """対象databaseが未作成の場合だけ作成する.

    Args:
        database_url (str): 作成対象のdatabase名を含むPostgreSQL接続URL.

    Returns:
        bool: databaseを新規作成した場合はTrue. 既に存在した場合はFalse.

    Raises:
        sqlalchemy.exc.ArgumentError: 空または不正な``database_url``を
            ``maintenance_url_for``から伝播する場合.
        ValueError: URLのdriverがPostgreSQLではないか, database名を含まない場合.

    Notes:
        engineは処理の成否にかかわらずdisposeする.
    """
    maintenance_url, target_database = maintenance_url_for(database_url)
    engine = create_async_engine(
        maintenance_url.render_as_string(hide_password=False),
        isolation_level="AUTOCOMMIT",
    )
    try:
        async with engine.connect() as connection:
            result = await connection.execute(
                text("SELECT 1 FROM pg_database WHERE datname = :database"),
                {"database": target_database},
            )
            if result.first() is not None:
                return False
            create_database = text(f"CREATE DATABASE {quote_identifier(target_database)}")
            _ = await connection.execute(create_database)
            return True
    finally:
        await engine.dispose()
