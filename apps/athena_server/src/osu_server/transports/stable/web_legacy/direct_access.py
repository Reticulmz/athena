"""Stable legacy osu!direct access gateを提供するmodule."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from osu_server.domain.beatmaps import DirectAccessDecision, DirectAccessPolicy
from osu_server.services.queries.identity import SessionCredentialsQueryInput

if TYPE_CHECKING:
    from collections.abc import Mapping

    from osu_server.services.queries.identity import SessionCredentialsQuery


@dataclass(slots=True, frozen=True)
class StableDirectAccessResult:
    """Stable direct work開始前のaccess判定結果を表す.

    Attributes:
        decision (DirectAccessDecision): auth/access policyの判定結果.
        authenticated_user_id (int | None): 認証済みuser ID. 認証失敗時はNone.

    Notes:
        username, password hash, query全体は保持しない.
    """

    decision: DirectAccessDecision
    authenticated_user_id: int | None = field(default=None, repr=False)


class StableDirectAccessGate:
    """Stable direct search/point lookupの前段で認証とaccess policyを適用する."""

    _auth_query: SessionCredentialsQuery
    _access_policy: DirectAccessPolicy

    def __init__(
        self,
        *,
        auth_query: SessionCredentialsQuery,
        access_policy: DirectAccessPolicy,
    ) -> None:
        """Access gateのlegacy auth queryとpolicyを保持する.

        Args:
            auth_query (SessionCredentialsQuery): legacy credentialを検証するquery.
            access_policy (DirectAccessPolicy): osu!direct work前に適用するpolicy.
        """
        self._auth_query = auth_query
        self._access_policy = access_policy

    async def authorize(self, query: Mapping[str, str]) -> StableDirectAccessResult:
        """Stable legacy queryを認証し, osu!direct access decisionを返す.

        Args:
            query (Mapping[str, str]): Starlette QueryParams互換またはplain mappingのquery values.

        Returns:
            StableDirectAccessResult: catalog workを始めてよいかを示すsanitize済み結果.

        Notes:
            `u`と`h`を認証queryへ渡すが,戻り値にはcredentialを保持しない.
        """
        auth_query_result = await self._auth_query.execute(
            SessionCredentialsQueryInput(
                username=query.get("u"),
                password_md5=query.get("h"),
            )
        )
        auth_result = auth_query_result.outcome
        if auth_result.failure is not None or auth_result.user_id is None:
            return StableDirectAccessResult(DirectAccessDecision.AUTHENTICATION_REQUIRED)

        user_id = auth_result.user_id
        decision = self._access_policy.evaluate(authenticated_user_id=user_id)
        return StableDirectAccessResult(decision=decision, authenticated_user_id=user_id)


__all__ = [
    "StableDirectAccessGate",
    "StableDirectAccessResult",
]
