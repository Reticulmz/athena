from __future__ import annotations

from osu_server.domain.identity.authorization import Privileges, has_privilege
from osu_server.domain.identity.leaderboard_visibility import (
    LEADERBOARD_VISIBLE_PERMISSION_MASK,
    LEADERBOARD_VISIBLE_PRIVILEGES,
    is_leaderboard_visible_user,
)


def test_normal_and_unrestricted_user_is_leaderboard_visible() -> None:
    privileges = Privileges.NORMAL | Privileges.UNRESTRICTED

    assert is_leaderboard_visible_user(privileges)


def test_missing_unrestricted_user_is_hidden_for_public_leaderboard() -> None:
    assert not is_leaderboard_visible_user(Privileges.NORMAL)


def test_admin_does_not_bypass_leaderboard_visibility() -> None:
    privileges = Privileges.ADMIN
    required = Privileges.NORMAL | Privileges.UNRESTRICTED

    assert has_privilege(privileges, required)
    assert not is_leaderboard_visible_user(privileges)


def test_restricted_viewer_personal_best_is_suppressed() -> None:
    restricted_viewer_privileges = Privileges.NORMAL

    assert not is_leaderboard_visible_user(restricted_viewer_privileges)


def test_integer_privileges_use_same_no_bypass_policy() -> None:
    privileges = int(Privileges.NORMAL | Privileges.UNRESTRICTED)

    assert is_leaderboard_visible_user(privileges)


def test_leaderboard_visible_mask_matches_policy_privileges() -> None:
    assert LEADERBOARD_VISIBLE_PRIVILEGES == Privileges.NORMAL | Privileges.UNRESTRICTED
    assert int(LEADERBOARD_VISIBLE_PRIVILEGES) == LEADERBOARD_VISIBLE_PERMISSION_MASK
