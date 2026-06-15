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
    "SessionCredentialsQuery",
    "SessionCredentialsQueryInput",
    "SessionCredentialsQueryResult",
    "SessionCredentialsQueryUseCase",
]
