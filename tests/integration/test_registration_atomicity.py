"""Registration atomicity integration tests."""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest
from sqlalchemy import text

from osu_server.domain.identity.authentication import RegistrationForm
from osu_server.repositories.sqlalchemy.queries.users import SQLAlchemyUserQueryRepository
from osu_server.services.auth_service import AuthService

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

    from osu_server.repositories.interfaces.queries.roles import RoleQueryRepository
    from osu_server.repositories.interfaces.queries.users import UserQueryRepository
    from osu_server.repositories.interfaces.session_store import SessionStore
    from osu_server.repositories.interfaces.unit_of_work import UnitOfWorkFactory
    from osu_server.services.password_service import PasswordService
    from osu_server.services.permission_service import PermissionService


@pytest.fixture
def auth_service(
    uow_factory: UnitOfWorkFactory,
    user_query_repo: UserQueryRepository,
    role_query_repo: RoleQueryRepository,
    password_service: PasswordService,
    permission_service: PermissionService,
    session_store: SessionStore,
) -> AuthService:
    """AuthService instance for registration tests."""
    return AuthService(
        uow_factory=uow_factory,
        user_query_repo=user_query_repo,
        role_query_repo=role_query_repo,
        password_service=password_service,
        permission_service=permission_service,
        session_store=session_store,
        system_user_id=1,
    )


@pytest.mark.asyncio
async def test_role_assignment_failure_rolls_back_user_creation(
    auth_service: AuthService,
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """If default role assignment fails after user creation, neither should be committed.

    This test verifies the atomicity contract: user creation and role assignment
    must succeed or fail together. If the Default role is missing, the UoW should
    rollback the entire registration transaction, leaving no zombie account.
    """
    # Setup: Remove Default role to simulate role assignment failure
    async with session_factory() as session:
        _ = await session.execute(text("DELETE FROM roles WHERE name = 'Default'"))
        await session.commit()

    # Attempt registration
    form = RegistrationForm(
        username="atomictest",
        password="securepassword123",
        email="atomic@example.com",
    )

    # Execute: registration should fail due to missing Default role
    with pytest.raises(LookupError, match="No role named 'Default' exists"):
        _ = await auth_service.register(form, check_only=False)

    # Assert: user should NOT exist in database (rollback happened)
    user_query_repo = SQLAlchemyUserQueryRepository(session_factory)
    user = await user_query_repo.get_by_safe_username("atomictest")
    assert user is None, "User should not be committed when role assignment fails"


@pytest.mark.asyncio
async def test_successful_registration_commits_both_user_and_role(
    auth_service: AuthService,
    user_query_repo: UserQueryRepository,
    role_query_repo: RoleQueryRepository,
) -> None:
    """Successful registration atomically commits both user and role assignment."""
    form = RegistrationForm(
        username="successtest",
        password="securepassword123",
        email="success@example.com",
    )

    # Execute: registration should succeed
    result = await auth_service.register(form, check_only=False)
    assert result.success is True

    # Assert: user exists
    user = await user_query_repo.get_by_safe_username("successtest")
    assert user is not None
    assert user.username == "successtest"

    # Assert: user has Default role assigned
    roles = await role_query_repo.get_roles_for_user(user.id)
    assert len(roles) == 1
    assert roles[0].name == "Default"
