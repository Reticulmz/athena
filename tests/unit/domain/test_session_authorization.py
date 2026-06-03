from __future__ import annotations

from dataclasses import FrozenInstanceError

import pytest

from osu_server.domain.role import Privileges
from osu_server.domain.session_authorization import (
    AuthorizationRefreshStatus,
    RoleAuthorizationRefreshResult,
    SessionAuthorization,
    UserAuthorizationRefreshResult,
)


class TestAuthorizationRefreshStatus:
    def test_enum_values(self) -> None:
        assert AuthorizationRefreshStatus.REFRESHED.value == "refreshed"
        assert AuthorizationRefreshStatus.NO_ACTIVE_SESSION.value == "no_active_session"
        assert AuthorizationRefreshStatus.FAILED.value == "failed"

    def test_enum_members(self) -> None:
        members = set(AuthorizationRefreshStatus)
        assert members == {
            AuthorizationRefreshStatus.REFRESHED,
            AuthorizationRefreshStatus.NO_ACTIVE_SESSION,
            AuthorizationRefreshStatus.FAILED,
        }

    def test_is_str_enum(self) -> None:
        assert issubclass(AuthorizationRefreshStatus, str)


class TestSessionAuthorization:
    def test_slots(self) -> None:
        assert hasattr(SessionAuthorization, "__slots__")

    def test_creation_defaults(self) -> None:
        sa = SessionAuthorization(privileges=Privileges.NORMAL)
        assert sa.privileges == Privileges.NORMAL
        assert sa.role_ids == ()

    def test_creation_with_role_ids(self) -> None:
        sa = SessionAuthorization(
            privileges=Privileges.NORMAL | Privileges.VERIFIED,
            role_ids=(1, 2, 3),
        )
        assert sa.privileges == (Privileges.NORMAL | Privileges.VERIFIED)
        assert sa.role_ids == (1, 2, 3)

    def test_role_ids_is_always_tuple(self) -> None:
        sa = SessionAuthorization(privileges=Privileges.NORMAL, role_ids=[1, 2, 3])  # pyright: ignore[reportArgumentType]
        assert isinstance(sa.role_ids, tuple)
        assert sa.role_ids == (1, 2, 3)

    def test_role_ids_normalized_from_generator(self) -> None:
        sa = SessionAuthorization(
            privileges=Privileges.NORMAL,
            role_ids=(i for i in range(3)),  # type: ignore[arg-type]  # pyright: ignore[reportArgumentType]
        )
        assert isinstance(sa.role_ids, tuple)
        assert sa.role_ids == (0, 1, 2)

    def test_immutable_privileges(self) -> None:
        sa = SessionAuthorization(privileges=Privileges.NORMAL)
        with pytest.raises(FrozenInstanceError):
            sa.privileges = Privileges.ADMIN  # type: ignore[misc]  # pyright: ignore[reportAttributeAccessIssue]

    def test_immutable_role_ids(self) -> None:
        sa = SessionAuthorization(privileges=Privileges.NORMAL, role_ids=(1,))
        with pytest.raises(FrozenInstanceError):
            sa.role_ids = (2, 3)  # type: ignore[misc]  # pyright: ignore[reportAttributeAccessIssue]

    def test_equality_same_values(self) -> None:
        a = SessionAuthorization(privileges=Privileges.NORMAL, role_ids=(1, 2))
        b = SessionAuthorization(privileges=Privileges.NORMAL, role_ids=(1, 2))
        assert a == b
        assert hash(a) == hash(b)

    def test_inequality_different_privileges(self) -> None:
        a = SessionAuthorization(privileges=Privileges.NORMAL, role_ids=(1,))
        b = SessionAuthorization(privileges=Privileges.ADMIN, role_ids=(1,))
        assert a != b

    def test_inequality_different_role_ids(self) -> None:
        a = SessionAuthorization(privileges=Privileges.NORMAL, role_ids=(1,))
        b = SessionAuthorization(privileges=Privileges.NORMAL, role_ids=(2,))
        assert a != b

    def test_empty_privileges(self) -> None:
        sa = SessionAuthorization(privileges=Privileges.NONE, role_ids=())
        assert sa.privileges == Privileges.NONE
        assert sa.role_ids == ()

    def test_all_privileges_with_roles(self) -> None:
        all_privs = Privileges(0)
        for member in Privileges:
            all_privs |= member
        sa = SessionAuthorization(privileges=all_privs, role_ids=(1, 2, 3))
        assert sa.privileges == all_privs
        assert sa.role_ids == (1, 2, 3)


class TestUserAuthorizationRefreshResult:
    def test_slots(self) -> None:
        assert hasattr(UserAuthorizationRefreshResult, "__slots__")

    def test_refreshed_with_authorization(self) -> None:
        auth = SessionAuthorization(privileges=Privileges.NORMAL, role_ids=(1,))
        result = UserAuthorizationRefreshResult(
            user_id=42,
            status=AuthorizationRefreshStatus.REFRESHED,
            authorization=auth,
        )
        assert result.user_id == 42
        assert result.status == AuthorizationRefreshStatus.REFRESHED
        assert result.authorization is auth

    def test_no_active_session_without_authorization(self) -> None:
        result = UserAuthorizationRefreshResult(
            user_id=42,
            status=AuthorizationRefreshStatus.NO_ACTIVE_SESSION,
        )
        assert result.user_id == 42
        assert result.status == AuthorizationRefreshStatus.NO_ACTIVE_SESSION
        assert result.authorization is None

    def test_failed_without_authorization(self) -> None:
        result = UserAuthorizationRefreshResult(
            user_id=42,
            status=AuthorizationRefreshStatus.FAILED,
        )
        assert result.user_id == 42
        assert result.status == AuthorizationRefreshStatus.FAILED
        assert result.authorization is None

    def test_refreshed_requires_authorization(self) -> None:
        with pytest.raises(ValueError, match="authorization must be present"):
            UserAuthorizationRefreshResult(
                user_id=42,
                status=AuthorizationRefreshStatus.REFRESHED,
            )  # pyright: ignore[reportUnusedCallResult]

    def test_no_active_session_rejects_authorization(self) -> None:
        auth = SessionAuthorization(privileges=Privileges.NORMAL)
        with pytest.raises(ValueError, match="authorization must be None"):
            UserAuthorizationRefreshResult(
                user_id=42,
                status=AuthorizationRefreshStatus.NO_ACTIVE_SESSION,
                authorization=auth,
            )  # pyright: ignore[reportUnusedCallResult]

    def test_failed_rejects_authorization(self) -> None:
        auth = SessionAuthorization(privileges=Privileges.NORMAL)
        with pytest.raises(ValueError, match="authorization must be None"):
            UserAuthorizationRefreshResult(
                user_id=42,
                status=AuthorizationRefreshStatus.FAILED,
                authorization=auth,
            )  # pyright: ignore[reportUnusedCallResult]

    def test_default_authorization_is_none(self) -> None:
        result = UserAuthorizationRefreshResult(
            user_id=42,
            status=AuthorizationRefreshStatus.NO_ACTIVE_SESSION,
        )
        assert result.authorization is None

    def test_immutable(self) -> None:
        result = UserAuthorizationRefreshResult(
            user_id=42,
            status=AuthorizationRefreshStatus.FAILED,
        )
        with pytest.raises(FrozenInstanceError):
            result.status = AuthorizationRefreshStatus.REFRESHED  # type: ignore[misc]  # pyright: ignore[reportAttributeAccessIssue]


class TestRoleAuthorizationRefreshResult:
    def test_slots(self) -> None:
        assert hasattr(RoleAuthorizationRefreshResult, "__slots__")

    def test_creation_no_users(self) -> None:
        result = RoleAuthorizationRefreshResult(role_id=1, user_results=())
        assert result.role_id == 1
        assert result.user_results == ()

    def test_creation_with_user_results(self) -> None:
        user1 = UserAuthorizationRefreshResult(
            user_id=1,
            status=AuthorizationRefreshStatus.REFRESHED,
            authorization=SessionAuthorization(privileges=Privileges.NORMAL, role_ids=(1,)),
        )
        user2 = UserAuthorizationRefreshResult(
            user_id=2,
            status=AuthorizationRefreshStatus.NO_ACTIVE_SESSION,
        )
        result = RoleAuthorizationRefreshResult(
            role_id=5,
            user_results=(user1, user2),
        )
        assert result.role_id == 5
        assert len(result.user_results) == 2
        assert result.user_results[0] is user1
        assert result.user_results[1] is user2

    def test_user_results_is_always_tuple(self) -> None:
        user = UserAuthorizationRefreshResult(
            user_id=1,
            status=AuthorizationRefreshStatus.FAILED,
        )
        result = RoleAuthorizationRefreshResult(role_id=1, user_results=[user])  # pyright: ignore[reportArgumentType]
        assert isinstance(result.user_results, tuple)
        assert result.user_results == (user,)

    def test_immutable(self) -> None:
        result = RoleAuthorizationRefreshResult(role_id=1, user_results=())
        with pytest.raises(FrozenInstanceError):
            result.role_id = 2  # type: ignore[misc]  # pyright: ignore[reportAttributeAccessIssue]
