"""Lightweight composition helpers for management commands."""

from __future__ import annotations

from typing import TYPE_CHECKING

from osu_server.domain.identity.system_users import BANCHO_BOT_USER_ID
from osu_server.infrastructure.cache.valkey_client import create_valkey_client
from osu_server.infrastructure.database.engine import create_engine
from osu_server.infrastructure.database.session import create_session_factory
from osu_server.repositories.sqlalchemy.queries.roles import SQLAlchemyRoleQueryRepository
from osu_server.repositories.sqlalchemy.queries.users import SQLAlchemyUserQueryRepository
from osu_server.repositories.sqlalchemy.unit_of_work import SQLAlchemyUnitOfWorkFactory
from osu_server.repositories.valkey.session_store import ValkeySessionStore
from osu_server.services.commands.identity.change_password import (
    ChangeUserPasswordCommandInput,
    ChangeUserPasswordCommandResult,
    ChangeUserPasswordCommandUseCase,
)
from osu_server.services.commands.identity.change_role import (
    ChangeUserRoleCommandInput,
    ChangeUserRoleCommandResult,
    ChangeUserRoleCommandUseCase,
)
from osu_server.services.commands.identity.session_authorization_service import (
    SessionAuthorizationService,
)
from osu_server.services.queries.identity.password_service import PasswordService
from osu_server.services.queries.identity.permission_service import PermissionService

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


async def change_user_role(
    config: AppConfig,
    input_data: ChangeUserRoleCommandInput,
) -> ChangeUserRoleCommandResult:
    """Build the minimal DB-backed graph needed to change a user's role."""
    engine = create_engine(str(config.database_url))
    try:
        valkey = await create_valkey_client(str(config.valkey_url))
        try:
            session_factory = create_session_factory(engine)
            role_query_repository = SQLAlchemyRoleQueryRepository(session_factory)
            session_authorization_service = SessionAuthorizationService(
                permission_service=PermissionService(role_query_repository),
                session_store=ValkeySessionStore(valkey, ttl=config.session_ttl),
                role_repository=role_query_repository,
            )
            use_case = ChangeUserRoleCommandUseCase(
                uow_factory=SQLAlchemyUnitOfWorkFactory(session_factory),
                session_authorization_service=session_authorization_service,
                system_user_id=BANCHO_BOT_USER_ID,
            )
            return await use_case.execute(input_data)
        finally:
            await valkey.close()
    finally:
        await engine.dispose()
