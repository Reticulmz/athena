"""Identity privilegeに基づくpublic leaderboard visibility policyを検証する."""

from __future__ import annotations

from osu_server.domain.identity.authorization import Privileges, has_privilege
from osu_server.domain.identity.leaderboard_visibility import (
    LEADERBOARD_VISIBLE_PERMISSION_MASK,
    LEADERBOARD_VISIBLE_PRIVILEGES,
    is_leaderboard_visible_user,
)


def test_normal_and_unrestricted_user_is_leaderboard_visible() -> None:
    """NORMALとUNRESTRICTEDを両方持つuserだけをpublic leaderboardへ表示することを検証する.

    Returns:
        None: 必要なprivilege集合でvisibility判定がTrueになることを検証して完了する.

    Raises:
        AssertionError: 完全な必要privilege集合を持つuserを非表示にした場合.
    """
    privileges = Privileges.NORMAL | Privileges.UNRESTRICTED

    assert is_leaderboard_visible_user(privileges)


def test_missing_unrestricted_user_is_hidden_for_public_leaderboard() -> None:
    """UNRESTRICTEDを欠くNORMAL userをpublic leaderboardから隠すことを検証する.

    Returns:
        None: 欠落した必要privilegeでvisibility判定がFalseになることを検証して完了する.

    Raises:
        AssertionError: restricted userをpublic leaderboardへ表示した場合.
    """
    assert not is_leaderboard_visible_user(Privileges.NORMAL)


def test_admin_does_not_bypass_leaderboard_visibility() -> None:
    """一般authorizationでは十分なADMIN privilegeがvisibility policyをbypassしないことを検証する.

    Returns:
        None: has_privilegeとvisibility policyの異なる結果を検証して完了する.

    Raises:
        AssertionError: ADMINだけでpublic leaderboard visibilityを許可した場合.
    """
    privileges = Privileges.ADMIN
    required = Privileges.NORMAL | Privileges.UNRESTRICTED

    assert has_privilege(privileges, required)
    assert not is_leaderboard_visible_user(privileges)


def test_restricted_viewer_personal_best_is_suppressed() -> None:
    """Restricted viewerのpersonal bestをleaderboard表示対象にしないことを検証する.

    Returns:
        None: NORMALだけのviewerでvisibility判定がFalseになることを検証して完了する.

    Raises:
        AssertionError: restricted viewerのpersonal bestを公開した場合.
    """
    restricted_viewer_privileges = Privileges.NORMAL

    assert not is_leaderboard_visible_user(restricted_viewer_privileges)


def test_integer_privileges_use_same_no_bypass_policy() -> None:
    """整数bitmask入力にもPrivileges入力と同じvisibility policyを適用することを検証する.

    Returns:
        None: 必要な整数bitmaskでvisibility判定がTrueになることを検証して完了する.

    Raises:
        AssertionError: int入力とPrivileges入力でpolicy結果が異なる場合.
    """
    privileges = int(Privileges.NORMAL | Privileges.UNRESTRICTED)

    assert is_leaderboard_visible_user(privileges)


def test_leaderboard_visible_mask_matches_policy_privileges() -> None:
    """公開条件のPrivileges定数と整数mask定数が同じbit集合を表すことを検証する.

    Returns:
        None: policy privilege集合とそのint値が公開mask定数と一致することを検証して完了する.

    Raises:
        AssertionError: privilege定数と公開mask定数の対応が崩れた場合.
    """
    assert LEADERBOARD_VISIBLE_PRIVILEGES == Privileges.NORMAL | Privileges.UNRESTRICTED
    assert int(LEADERBOARD_VISIBLE_PRIVILEGES) == LEADERBOARD_VISIBLE_PERMISSION_MASK
