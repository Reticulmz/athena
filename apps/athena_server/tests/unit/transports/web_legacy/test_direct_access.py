"""Stable osu!direct access gateの契約を検証するmodule."""

from dataclasses import dataclass

from osu_server.domain.beatmaps import (
    DirectAccessDecision,
    DirectAccessPolicy,
    DirectAccessPolicyMode,
)
from osu_server.domain.identity.authentication import LegacyWebAuthFailure, LegacyWebAuthResult
from osu_server.services.queries.identity import (
    SessionCredentialsQueryInput,
    SessionCredentialsQueryResult,
)
from osu_server.transports.stable.web_legacy.direct_access import StableDirectAccessGate


@dataclass(slots=True)
class _AuthQuery:
    """Stable direct access testで固定認証結果を返すquery fake.

    Attributes:
        result (LegacyWebAuthResult): executeが返すauthentication outcome.
        inputs (list[SessionCredentialsQueryInput]): 受け取ったcredential input列.
    """

    result: LegacyWebAuthResult
    inputs: list[SessionCredentialsQueryInput]

    async def execute(
        self,
        input_data: SessionCredentialsQueryInput,
    ) -> SessionCredentialsQueryResult:
        """Credential inputを記録して固定結果を返す.

        Args:
            input_data (SessionCredentialsQueryInput): stable direct queryから抽出したcredential.

        Returns:
            SessionCredentialsQueryResult: testで設定したauth outcome.
        """
        self.inputs.append(input_data)
        return SessionCredentialsQueryResult(outcome=self.result)


async def test_direct_access_gate_authenticates_legacy_credentials_before_work() -> None:
    """Stable direct access gateがwork前にlegacy credentialを認証する契約を検証する.

    Returns:
        None: u/hから認証queryを呼び, 許可decisionとuser IDを返すことを確認する.
    """
    auth_query = _AuthQuery(LegacyWebAuthResult(user_id=42, username="Player"), [])
    gate = StableDirectAccessGate(
        auth_query=auth_query,
        access_policy=DirectAccessPolicy(DirectAccessPolicyMode.AUTHENTICATED),
    )

    result = await gate.authorize({"u": "Player", "h": "password-md5"})

    assert result.decision is DirectAccessDecision.ALLOWED
    assert result.authenticated_user_id == 42
    assert auth_query.inputs == [
        SessionCredentialsQueryInput(username="Player", password_md5="password-md5")
    ]


async def test_direct_access_gate_rejects_auth_failure_without_catalog_data() -> None:
    """認証失敗時にcatalog dataなしの拒否decisionだけを返す契約を検証する.

    Returns:
        None: 認証失敗resultがuser IDやcredentialを保持しないことを確認する.
    """
    auth_query = _AuthQuery(
        LegacyWebAuthResult(failure=LegacyWebAuthFailure.INVALID_CREDENTIALS),
        [],
    )
    gate = StableDirectAccessGate(
        auth_query=auth_query,
        access_policy=DirectAccessPolicy(DirectAccessPolicyMode.AUTHENTICATED),
    )

    result = await gate.authorize({"u": "Player", "h": "secret-hash"})

    assert result.decision is DirectAccessDecision.AUTHENTICATION_REQUIRED
    assert result.authenticated_user_id is None
    assert "Player" not in repr(result)
    assert "secret-hash" not in repr(result)


async def test_direct_access_gate_applies_disabled_policy_after_authentication() -> None:
    """認証成功後にdisabled policyがdirect workを拒否する契約を検証する.

    Returns:
        None: 認証済みuserへDENIED decisionを返すことを確認する.
    """
    auth_query = _AuthQuery(LegacyWebAuthResult(user_id=42, username="Player"), [])
    gate = StableDirectAccessGate(
        auth_query=auth_query,
        access_policy=DirectAccessPolicy(DirectAccessPolicyMode.DISABLED),
    )

    result = await gate.authorize({"u": "Player", "h": "password-md5"})

    assert result.decision is DirectAccessDecision.DENIED
    assert result.authenticated_user_id == 42
