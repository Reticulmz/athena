"""Alembic async migration environment.

Reads DATABASE_URL from AppConfig and converts it to the
``postgresql+asyncpg://`` scheme for async engine creation.
"""

import asyncio
from logging.config import fileConfig

from alembic import context
from sqlalchemy import pool
from sqlalchemy.engine import Connection
from sqlalchemy.ext.asyncio import async_engine_from_config

from osu_server.config import load_config
from osu_server.infrastructure.database.base import Base
from osu_server.repositories.sqlalchemy.models import *  # noqa: F403 — register models with Base.metadata

# Alembic Config object
config = context.config

# Set sqlalchemy.url from AppConfig. DATABASE_URL in the process environment still
# takes precedence over .env.<environment> via pydantic-settings.
database_url = str(load_config().database_url)

async_url = database_url.replace("postgres://", "postgresql+asyncpg://", 1).replace(
    "postgresql://", "postgresql+asyncpg://", 1
)
config.set_main_option("sqlalchemy.url", async_url)

# Python logging configuration
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

# MetaData for autogenerate support
target_metadata = Base.metadata


def run_migrations_offline() -> None:
    """DB接続なしでmigration SQLを生成する.

    Returns:
        None: transaction単位をmigration fileごとに分けてSQL生成を完了したことを示す.

    Raises:
        Exception: Alembic contextの構成またはmigration SQL生成に失敗した場合.

    Notes:
        autocommit blockを含むmigrationと同じtransaction境界をoffline SQLにも適用する.
    """
    url = config.get_main_option("sqlalchemy.url")
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        transaction_per_migration=True,
    )

    with context.begin_transaction():
        context.run_migrations()


def do_run_migrations(connection: Connection) -> None:
    """同期connection上でmigrationをfile単位のtransactionとして実行する.

    Args:
        connection (Connection): Alembicがmigrationに使用する同期DB connection.

    Returns:
        None: 対象revisionまでのmigration実行が完了したことを示す.

    Raises:
        SQLAlchemyError: migration DDLまたはtransaction操作に失敗した場合.

    Notes:
        autocommit blockは直前のtransactionをcommitするため, Alembic公式推奨に従い
        `transaction_per_migration=True`でfile間のtransaction境界を維持する.
    """
    context.configure(
        connection=connection,
        target_metadata=target_metadata,
        transaction_per_migration=True,
    )

    with context.begin_transaction():
        context.run_migrations()


async def run_async_migrations() -> None:
    """Create an async engine and run migrations."""
    connectable = async_engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )

    async with connectable.connect() as connection:
        await connection.run_sync(do_run_migrations)

    await connectable.dispose()


def run_migrations_online() -> None:
    """Run migrations in 'online' mode."""
    asyncio.run(run_async_migrations())


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
