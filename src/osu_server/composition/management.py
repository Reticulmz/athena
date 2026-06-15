"""Lightweight composition helpers for management commands."""

from __future__ import annotations

from typing import TYPE_CHECKING

from osu_server.domain.identity.system_users import BANCHO_BOT_USER_ID
from osu_server.infrastructure.database.engine import create_engine
from osu_server.infrastructure.database.session import create_session_factory
from osu_server.repositories.sqlalchemy.queries.users import SQLAlchemyUserQueryRepository
from osu_server.repositories.sqlalchemy.unit_of_work import SQLAlchemyUnitOfWorkFactory
from osu_server.services.commands.identity.change_password import (
    ChangeUserPasswordCommandInput,
    ChangeUserPasswordCommandResult,
    ChangeUserPasswordCommandUseCase,
)
from osu_server.services.queries.identity.password_service import PasswordService

if TYPE_CHECKING:
    from osu_server.config import AppConfig


async def change_user_password(
    config: AppConfig,
    input_data: ChangeUserPasswordCommandInput,
) -> ChangeUserPasswordCommandResult:
    """Build the minimal DB-backed graph needed to change a user's password."""
    engine = create_engine(str(config.database_url))
    try:
        session_factory = create_session_factory(engine)
        password_service = PasswordService(
            hibp_client=None,
            banned_passwords=config.banned_passwords,
        )
        use_case = ChangeUserPasswordCommandUseCase(
            uow_factory=SQLAlchemyUnitOfWorkFactory(session_factory),
            user_query_repository=SQLAlchemyUserQueryRepository(session_factory),
            password_service=password_service,
            system_user_id=BANCHO_BOT_USER_ID,
        )
        return await use_case.execute(input_data)
    finally:
        await engine.dispose()
