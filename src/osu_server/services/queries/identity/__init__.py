"""Identity query use-case package."""

from osu_server.services.queries.identity.authorization import (
    ComputePermissionsQuery,
    ComputePermissionsQueryInput,
    ComputePermissionsQueryResult,
    ComputePermissionsQueryUseCase,
    ComputeSessionAuthorizationQuery,
    ComputeSessionAuthorizationQueryInput,
    ComputeSessionAuthorizationQueryResult,
    ComputeSessionAuthorizationQueryUseCase,
)
from osu_server.services.queries.identity.online_users import (
    ListOnlineUsersQuery,
    ListOnlineUsersQueryInput,
    ListOnlineUsersQueryResult,
    ListOnlineUsersQueryUseCase,
)
from osu_server.services.queries.identity.online_users_service import OnlineUsersService
from osu_server.services.queries.identity.password_service import PasswordService
from osu_server.services.queries.identity.permission_service import PermissionService
from osu_server.services.queries.identity.session_credentials import (
    SessionCredentialsQuery,
    SessionCredentialsQueryInput,
    SessionCredentialsQueryResult,
    SessionCredentialsQueryUseCase,
)

__all__ = [
    "ComputePermissionsQuery",
    "ComputePermissionsQueryInput",
    "ComputePermissionsQueryResult",
    "ComputePermissionsQueryUseCase",
    "ComputeSessionAuthorizationQuery",
    "ComputeSessionAuthorizationQueryInput",
    "ComputeSessionAuthorizationQueryResult",
    "ComputeSessionAuthorizationQueryUseCase",
    "ListOnlineUsersQuery",
    "ListOnlineUsersQueryInput",
    "ListOnlineUsersQueryResult",
    "ListOnlineUsersQueryUseCase",
    "OnlineUsersService",
    "PasswordService",
    "PermissionService",
    "SessionCredentialsQuery",
    "SessionCredentialsQueryInput",
    "SessionCredentialsQueryResult",
    "SessionCredentialsQueryUseCase",
]
