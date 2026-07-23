"""Session authorization snapshotとrefresh resultの不変条件を検証するmodule."""

from __future__ import annotations

import pytest

from osu_server.domain.identity.authorization import Privileges
from osu_server.domain.identity.sessions import (
    AuthorizationRefreshStatus,
    RoleAuthorizationRefreshResult,
    SessionAuthorization,
    UserAuthorizationRefreshResult,
)
from tests.support.runtime_assertions import assert_rejects_setattr


class TestAuthorizationRefreshStatus:
    """Authorization refreshのoutcome enum contractを検証する."""

    def test_enum_values(self) -> None:
        """各outcomeがwire/persistenceで使う文字列値を持つことを検証する.

        Returns:
            None: enum値を検証して完了し,呼び出し側へ値を返さない.
        """
        assert AuthorizationRefreshStatus.REFRESHED.value == "refreshed"
        assert AuthorizationRefreshStatus.NO_ACTIVE_SESSION.value == "no_active_session"
        assert AuthorizationRefreshStatus.FAILED.value == "failed"

    def test_enum_members(self) -> None:
        """Refresh statusが定義済みの3 outcomeだけを列挙することを検証する.

        Returns:
            None: enum member集合を検証して完了し,呼び出し側へ値を返さない.
        """
        members = set(AuthorizationRefreshStatus)
        assert members == {
            AuthorizationRefreshStatus.REFRESHED,
            AuthorizationRefreshStatus.NO_ACTIVE_SESSION,
            AuthorizationRefreshStatus.FAILED,
        }

    def test_is_str_enum(self) -> None:
        """Refresh statusが文字列として扱えるenumであることを検証する.

        Returns:
            None: str継承を検証して完了し,呼び出し側へ値を返さない.
        """
        assert issubclass(AuthorizationRefreshStatus, str)


class TestSessionAuthorization:
    """SessionAuthorizationの正規化,不変性,value equalityを検証する."""

    def test_slots(self) -> None:
        """Snapshotがslotsを持つcompactなvalue objectであることを検証する.

        Returns:
            None: slotsの存在を検証して完了し,呼び出し側へ値を返さない.
        """
        assert hasattr(SessionAuthorization, "__slots__")

    def test_creation_defaults(self) -> None:
        """Role IDを省略したsnapshotが空tupleを既定値にすることを検証する.

        Returns:
            None: 既定field値を検証して完了し,呼び出し側へ値を返さない.
        """
        sa = SessionAuthorization(privileges=Privileges.NORMAL)
        assert sa.privileges == Privileges.NORMAL
        assert sa.role_ids == ()

    def test_creation_with_role_ids(self) -> None:
        """Privilege集合とrole ID群がsnapshotへ保持されることを検証する.

        Returns:
            None: constructor inputの保持を検証して完了し,呼び出し側へ値を返さない.
        """
        sa = SessionAuthorization(
            privileges=Privileges.NORMAL | Privileges.VERIFIED,
            role_ids=(1, 2, 3),
        )
        assert sa.privileges == (Privileges.NORMAL | Privileges.VERIFIED)
        assert sa.role_ids == (1, 2, 3)

    def test_role_ids_is_always_tuple(self) -> None:
        """Listで渡したrole ID群がimmutable tupleへ正規化されることを検証する.

        Returns:
            None: collection正規化を検証して完了し,呼び出し側へ値を返さない.
        """
        sa = SessionAuthorization(privileges=Privileges.NORMAL, role_ids=[1, 2, 3])  # pyright: ignore[reportArgumentType]
        assert isinstance(sa.role_ids, tuple)
        assert sa.role_ids == (1, 2, 3)

    def test_role_ids_normalized_from_generator(self) -> None:
        """Generatorで渡したrole ID群もtupleへ正規化されることを検証する.

        Returns:
            None: iterable正規化を検証して完了し,呼び出し側へ値を返さない.
        """
        sa = SessionAuthorization(
            privileges=Privileges.NORMAL,
            role_ids=(i for i in range(3)),  # type: ignore[arg-type]  # pyright: ignore[reportArgumentType]
        )
        assert isinstance(sa.role_ids, tuple)
        assert sa.role_ids == (0, 1, 2)

    def test_immutable_privileges(self) -> None:
        """生成後のprivilegesを変更できない不変性契約を検証する.

        Returns:
            None: attribute代入拒否を検証して完了し,呼び出し側へ値を返さない.
        """
        sa = SessionAuthorization(privileges=Privileges.NORMAL)
        assert_rejects_setattr(sa, "privileges", Privileges.ADMIN)

    def test_immutable_role_ids(self) -> None:
        """生成後のrole_idsを変更できない不変性契約を検証する.

        Returns:
            None: attribute代入拒否を検証して完了し,呼び出し側へ値を返さない.
        """
        sa = SessionAuthorization(privileges=Privileges.NORMAL, role_ids=(1,))
        assert_rejects_setattr(sa, "role_ids", (2, 3))

    def test_equality_same_values(self) -> None:
        """同じprivilegesとrole_idsを持つsnapshotが等価で同じhashになることを検証する.

        Returns:
            None: value equalityを検証して完了し,呼び出し側へ値を返さない.
        """
        a = SessionAuthorization(privileges=Privileges.NORMAL, role_ids=(1, 2))
        b = SessionAuthorization(privileges=Privileges.NORMAL, role_ids=(1, 2))
        assert a == b
        assert hash(a) == hash(b)

    def test_inequality_different_privileges(self) -> None:
        """Privilegesが異なるsnapshotが非等価になることを検証する.

        Returns:
            None: privilege差分の比較を検証して完了し,呼び出し側へ値を返さない.
        """
        a = SessionAuthorization(privileges=Privileges.NORMAL, role_ids=(1,))
        b = SessionAuthorization(privileges=Privileges.ADMIN, role_ids=(1,))
        assert a != b

    def test_inequality_different_role_ids(self) -> None:
        """Role ID群が異なるsnapshotが非等価になることを検証する.

        Returns:
            None: role ID差分の比較を検証して完了し,呼び出し側へ値を返さない.
        """
        a = SessionAuthorization(privileges=Privileges.NORMAL, role_ids=(1,))
        b = SessionAuthorization(privileges=Privileges.NORMAL, role_ids=(2,))
        assert a != b

    def test_empty_privileges(self) -> None:
        """NONE privilegeと空role ID群を保持できることを検証する.

        Returns:
            None: 空authorizationの表現を検証して完了し,呼び出し側へ値を返さない.
        """
        sa = SessionAuthorization(privileges=Privileges.NONE, role_ids=())
        assert sa.privileges == Privileges.NONE
        assert sa.role_ids == ()

    def test_all_privileges_with_roles(self) -> None:
        """全 privilegeと複数role IDを同じsnapshotへ保存できることを検証する.

        Returns:
            None: 最大flag集合の保持を検証して完了し,呼び出し側へ値を返さない.
        """
        all_privs = Privileges(0)
        for member in Privileges:
            all_privs |= member
        sa = SessionAuthorization(privileges=all_privs, role_ids=(1, 2, 3))
        assert sa.privileges == all_privs
        assert sa.role_ids == (1, 2, 3)


class TestUserAuthorizationRefreshResult:
    """User単位のauthorization refresh result invariantを検証する."""

    def test_slots(self) -> None:
        """Refresh resultがslotsを持つcompactなvalue objectであることを検証する.

        Returns:
            None: slotsの存在を検証して完了し,呼び出し側へ値を返さない.
        """
        assert hasattr(UserAuthorizationRefreshResult, "__slots__")

    def test_refreshed_with_authorization(self) -> None:
        """REFRESHED resultが新しいauthorization snapshotを保持することを検証する.

        Returns:
            None: refresh成功結果を検証して完了し,呼び出し側へ値を返さない.
        """
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
        """Active sessionがないresultがauthorizationを持たないことを検証する.

        Returns:
            None: session不在結果を検証して完了し,呼び出し側へ値を返さない.
        """
        result = UserAuthorizationRefreshResult(
            user_id=42,
            status=AuthorizationRefreshStatus.NO_ACTIVE_SESSION,
        )
        assert result.user_id == 42
        assert result.status == AuthorizationRefreshStatus.NO_ACTIVE_SESSION
        assert result.authorization is None

    def test_failed_without_authorization(self) -> None:
        """失敗resultがauthorizationを持たないことを検証する.

        Returns:
            None: failure resultを検証して完了し,呼び出し側へ値を返さない.
        """
        result = UserAuthorizationRefreshResult(
            user_id=42,
            status=AuthorizationRefreshStatus.FAILED,
        )
        assert result.user_id == 42
        assert result.status == AuthorizationRefreshStatus.FAILED
        assert result.authorization is None

    def test_refreshed_requires_authorization(self) -> None:
        """REFRESHED resultでauthorizationを省略するとValueErrorになることを検証する.

        Returns:
            None: 必須snapshot invariantの例外を検証して完了し,呼び出し側へ値を返さない.
        """
        with pytest.raises(ValueError, match="authorization must be present"):
            UserAuthorizationRefreshResult(
                user_id=42,
                status=AuthorizationRefreshStatus.REFRESHED,
            )  # pyright: ignore[reportUnusedCallResult]

    def test_no_active_session_rejects_authorization(self) -> None:
        """NO_ACTIVE_SESSION resultへauthorizationを渡すとValueErrorになることを検証する.

        Returns:
            None: statusとsnapshotの排他条件を検証して完了し,呼び出し側へ値を返さない.
        """
        auth = SessionAuthorization(privileges=Privileges.NORMAL)
        with pytest.raises(ValueError, match="authorization must be None"):
            UserAuthorizationRefreshResult(
                user_id=42,
                status=AuthorizationRefreshStatus.NO_ACTIVE_SESSION,
                authorization=auth,
            )  # pyright: ignore[reportUnusedCallResult]

    def test_failed_rejects_authorization(self) -> None:
        """FAILED resultへauthorizationを渡すとValueErrorになることを検証する.

        Returns:
            None: failure時のsnapshot禁止を検証して完了し,呼び出し側へ値を返さない.
        """
        auth = SessionAuthorization(privileges=Privileges.NORMAL)
        with pytest.raises(ValueError, match="authorization must be None"):
            UserAuthorizationRefreshResult(
                user_id=42,
                status=AuthorizationRefreshStatus.FAILED,
                authorization=auth,
            )  # pyright: ignore[reportUnusedCallResult]

    def test_default_authorization_is_none(self) -> None:
        """Authorization未指定時の既定値がNoneであることを検証する.

        Returns:
            None: 既定snapshot値を検証して完了し,呼び出し側へ値を返さない.
        """
        result = UserAuthorizationRefreshResult(
            user_id=42,
            status=AuthorizationRefreshStatus.NO_ACTIVE_SESSION,
        )
        assert result.authorization is None

    def test_immutable(self) -> None:
        """生成後のrefresh statusを変更できないことを検証する.

        Returns:
            None: resultの不変性を検証して完了し,呼び出し側へ値を返さない.
        """
        result = UserAuthorizationRefreshResult(
            user_id=42,
            status=AuthorizationRefreshStatus.FAILED,
        )
        assert_rejects_setattr(result, "status", AuthorizationRefreshStatus.REFRESHED)


class TestRoleAuthorizationRefreshResult:
    """Role単位に集約するauthorization refresh resultを検証する."""

    def test_slots(self) -> None:
        """Role refresh resultがslotsを持つvalue objectであることを検証する.

        Returns:
            None: slotsの存在を検証して完了し,呼び出し側へ値を返さない.
        """
        assert hasattr(RoleAuthorizationRefreshResult, "__slots__")

    def test_creation_no_users(self) -> None:
        """対象userがいないroleでも空tupleのresultを作れることを検証する.

        Returns:
            None: 空の集約結果を検証して完了し,呼び出し側へ値を返さない.
        """
        result = RoleAuthorizationRefreshResult(role_id=1, user_results=())
        assert result.role_id == 1
        assert result.user_results == ()

    def test_creation_with_user_results(self) -> None:
        """複数userのrefresh結果が順序を保ってrole resultへ集約されることを検証する.

        Returns:
            None: user result集合を検証して完了し,呼び出し側へ値を返さない.
        """
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
        """Listで渡したuser result群がimmutable tupleへ正規化されることを検証する.

        Returns:
            None: user resultのcollection正規化を検証して完了し,呼び出し側へ値を返さない.
        """
        user = UserAuthorizationRefreshResult(
            user_id=1,
            status=AuthorizationRefreshStatus.FAILED,
        )
        result = RoleAuthorizationRefreshResult(role_id=1, user_results=[user])  # pyright: ignore[reportArgumentType]
        assert isinstance(result.user_results, tuple)
        assert result.user_results == (user,)

    def test_immutable(self) -> None:
        """生成後のrole_idを変更できない不変性契約を検証する.

        Returns:
            None: role resultの不変性を検証して完了し,呼び出し側へ値を返さない.
        """
        result = RoleAuthorizationRefreshResult(role_id=1, user_results=())
        assert_rejects_setattr(result, "role_id", 2)
