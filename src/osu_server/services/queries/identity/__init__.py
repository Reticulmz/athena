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
from osu_server.services.queries.identity.legacy_web_auth import (
    LegacyWebAuthQuery,
    LegacyWebAuthQueryInput,
    LegacyWebAuthQueryResult,
    LegacyWebAuthQueryUseCase,
)
from osu_server.services.queries.identity.online_users import (
    ListOnlineUsersQuery,
    ListOnlineUsersQueryInput,
    ListOnlineUsersQueryResult,
    ListOnlineUsersQueryUseCase,
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
    "LegacyWebAuthQuery",
    "LegacyWebAuthQueryInput",
    "LegacyWebAuthQueryResult",
    "LegacyWebAuthQueryUseCase",
    "ListOnlineUsersQuery",
    "ListOnlineUsersQueryInput",
    "ListOnlineUsersQueryResult",
    "ListOnlineUsersQueryUseCase",
]
