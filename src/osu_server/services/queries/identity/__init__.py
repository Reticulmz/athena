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
from osu_server.services.queries.identity.friend_relationships import (
    CheckFriendRelationshipQuery,
    CheckFriendRelationshipQueryUseCase,
    GetFriendEligibleUserIdsQuery,
    GetFriendEligibleUserIdsQueryUseCase,
    ListFriendIdsQuery,
    ListFriendIdsQueryInput,
    ListFriendIdsQueryResult,
    ListFriendIdsQueryUseCase,
)
from osu_server.services.queries.identity.online_sessions import (
    ListActiveSessionsQuery,
    ListActiveSessionsQueryInput,
    ListActiveSessionsQueryResult,
    ListActiveSessionsQueryUseCase,
    OnlineSessionSnapshot,
)
from osu_server.services.queries.identity.password_service import PasswordService
from osu_server.services.queries.identity.permission_service import PermissionService
from osu_server.services.queries.identity.session_credentials import (
    SessionCredentialsQuery,
    SessionCredentialsQueryInput,
    SessionCredentialsQueryResult,
    SessionCredentialsQueryUseCase,
)

__all__ = [
    "CheckFriendRelationshipQuery",
    "CheckFriendRelationshipQueryUseCase",
    "ComputePermissionsQuery",
    "ComputePermissionsQueryInput",
    "ComputePermissionsQueryResult",
    "ComputePermissionsQueryUseCase",
    "ComputeSessionAuthorizationQuery",
    "ComputeSessionAuthorizationQueryInput",
    "ComputeSessionAuthorizationQueryResult",
    "ComputeSessionAuthorizationQueryUseCase",
    "GetFriendEligibleUserIdsQuery",
    "GetFriendEligibleUserIdsQueryUseCase",
    "ListActiveSessionsQuery",
    "ListActiveSessionsQueryInput",
    "ListActiveSessionsQueryResult",
    "ListActiveSessionsQueryUseCase",
    "ListFriendIdsQuery",
    "ListFriendIdsQueryInput",
    "ListFriendIdsQueryResult",
    "ListFriendIdsQueryUseCase",
    "OnlineSessionSnapshot",
    "PasswordService",
    "PermissionService",
    "SessionCredentialsQuery",
    "SessionCredentialsQueryInput",
    "SessionCredentialsQueryResult",
    "SessionCredentialsQueryUseCase",
]
