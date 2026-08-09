"""osu!direct access policy domain contractを検証するmodule."""

from osu_server.domain.beatmaps import (
    DirectAccessDecision,
    DirectAccessPolicy,
    DirectAccessPolicyMode,
)


def test_authenticated_policy_allows_authenticated_stable_user() -> None:
    """Authenticated default policyが認証済みstable userを許可する契約を検証する.

    Returns:
        None: authenticated policyの許可decisionを検証して完了する.
    """
    policy = DirectAccessPolicy(DirectAccessPolicyMode.AUTHENTICATED)

    decision = policy.evaluate(authenticated_user_id=42)

    assert decision is DirectAccessDecision.ALLOWED


def test_access_policy_distinguishes_missing_authentication_from_denial() -> None:
    """未認証userとpolicy拒否を別decisionとして返す契約を検証する.

    Returns:
        None: handlerが401とpolicy拒否を分離できるdecisionを検証して完了する.
    """
    authenticated_policy = DirectAccessPolicy(DirectAccessPolicyMode.AUTHENTICATED)
    disabled_policy = DirectAccessPolicy(DirectAccessPolicyMode.DISABLED)

    assert (
        authenticated_policy.evaluate(authenticated_user_id=None)
        is DirectAccessDecision.AUTHENTICATION_REQUIRED
    )
    assert disabled_policy.evaluate(authenticated_user_id=42) is DirectAccessDecision.DENIED


def test_supporter_entitlement_policy_denies_users_without_entitlement() -> None:
    """Supporter entitlement予約policyが権利なしuserを拒否できる契約を検証する.

    Returns:
        None: entitlement有無でdeny/allowが分かれることを確認して完了する.
    """
    policy = DirectAccessPolicy(DirectAccessPolicyMode.SUPPORTER_ENTITLEMENT)

    denied = policy.evaluate(authenticated_user_id=42)
    allowed = policy.evaluate(authenticated_user_id=42, has_supporter_entitlement=True)

    assert denied is DirectAccessDecision.DENIED
    assert allowed is DirectAccessDecision.ALLOWED
