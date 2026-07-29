"""安定版 legacy replay downloadのqueryを変換する."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from typing import TYPE_CHECKING

from osu_server.domain.compatibility.stable import ReplayDownloadBranch
from osu_server.domain.scores.score import Ruleset

if TYPE_CHECKING:
    from collections.abc import Mapping


_ALLOWED_QUERY_KEYS = frozenset({"c", "m", "u", "h"})


class ReplayDownloadMalformedReason(StrEnum):
    """Replay download queryのsanitized fallback reasonを表す.

    Attributes:
        MISSING_SCORE_ID (ReplayDownloadMalformedReason): score idが未指定である状態.
        MALFORMED_SCORE_ID (ReplayDownloadMalformedReason): score idを整数へ変換できない状態.
        MISSING_MODE (ReplayDownloadMalformedReason): rulesetが未指定である状態.
        MALFORMED_MODE (ReplayDownloadMalformedReason): rulesetを有効値へ変換できない状態.
        UNKNOWN_FIELD (ReplayDownloadMalformedReason): 許可されないquery fieldを含む状態.

    Notes:
        raw query値やcredentialは保持せず, provisional fallbackの分類だけに使用する.
    """

    MISSING_SCORE_ID = "missing_score_id"
    MALFORMED_SCORE_ID = "malformed_score_id"
    MISSING_MODE = "missing_mode"
    MALFORMED_MODE = "malformed_mode"
    UNKNOWN_FIELD = "unknown_field"


@dataclass(slots=True, frozen=True)
class ReplayDownloadRequest:
    """Replay download queryから解析したrequestを表す.

    Attributes:
        score_id (int): c fieldから解析したscore識別子.
        ruleset (Ruleset): m fieldから解析したstable ruleset.

    Notes:
        uとhはauth mapping専用のため保持しない. reprからも値を除外し, raw query値を
        failure outputへ混入させない.
    """

    score_id: int = field(repr=False)
    ruleset: Ruleset = field(repr=False)


@dataclass(slots=True, frozen=True)
class ReplayDownloadParseResult:
    """Replay download query parserのsanitized resultを表す.

    Attributes:
        request (ReplayDownloadRequest | None): 解析に成功したtyped request.
        branch (ReplayDownloadBranch | None): 失敗時に使用するprovisional fallback branch.
        reason (ReplayDownloadMalformedReason | None): 失敗時のsanitized reason.

    Notes:
        query全体, raw value, username, password hashは保持しない. requestもreprから除外し,
        test failure outputへraw query値を残さない.
    """

    request: ReplayDownloadRequest | None = field(default=None, repr=False)
    branch: ReplayDownloadBranch | None = None
    reason: ReplayDownloadMalformedReason | None = None


class ReplayDownloadQueryParser:
    """Stable legacy replay download queryをtyped requestへ変換する.

    Notes:
        cとmだけをrequestへ解析する. uとhはauth mapping専用なので保持しない. missing,
        malformed, unknown fieldはtarget-confirmed behaviorではなくprovisional fallbackとして
        分類する.
    """

    def parse(self, query: Mapping[str, str]) -> ReplayDownloadParseResult:
        """Replay download queryをsanitized parse resultに変換する.

        Args:
            query (Mapping[str, str]): Starlette QueryParams互換またはplain mappingのquery values.

        Returns:
            ReplayDownloadParseResult: 有効なrequestまたはprovisional malformed fallback result.

        Notes:
            query mapping全体, raw query値, u, hはresultへ返さない.
        """
        if any(key not in _ALLOWED_QUERY_KEYS for key in query):
            return _malformed_result(ReplayDownloadMalformedReason.UNKNOWN_FIELD)

        score_id = _parse_score_id(query.get("c"))
        if isinstance(score_id, ReplayDownloadMalformedReason):
            return _malformed_result(score_id)

        ruleset = _parse_ruleset(query.get("m"))
        if isinstance(ruleset, ReplayDownloadMalformedReason):
            return _malformed_result(ruleset)

        return ReplayDownloadParseResult(
            request=ReplayDownloadRequest(score_id=score_id, ruleset=ruleset),
        )


def _parse_score_id(raw_score_id: str | None) -> int | ReplayDownloadMalformedReason:
    """Score idのquery値を整数またはsanitized reasonへ変換する.

    Args:
        raw_score_id (str | None): c fieldから取得したraw score id.

    Returns:
        int | ReplayDownloadMalformedReason: 解析したscore id. 未指定または不正値ではreason.
    """
    if raw_score_id is None:
        return ReplayDownloadMalformedReason.MISSING_SCORE_ID

    try:
        return int(raw_score_id)
    except ValueError:
        return ReplayDownloadMalformedReason.MALFORMED_SCORE_ID


def _parse_ruleset(raw_ruleset: str | None) -> Ruleset | ReplayDownloadMalformedReason:
    """Rulesetのquery値をRulesetまたはsanitized reasonへ変換する.

    Args:
        raw_ruleset (str | None): m fieldから取得したraw ruleset.

    Returns:
        Ruleset | ReplayDownloadMalformedReason: 解析したruleset. 未指定または不正値ではreason.
    """
    if raw_ruleset is None:
        return ReplayDownloadMalformedReason.MISSING_MODE

    try:
        return Ruleset(int(raw_ruleset))
    except ValueError:
        return ReplayDownloadMalformedReason.MALFORMED_MODE


def _malformed_result(reason: ReplayDownloadMalformedReason) -> ReplayDownloadParseResult:
    """Sanitized reasonからprovisional malformed fallback resultを構築する.

    Args:
        reason (ReplayDownloadMalformedReason): requestを受理できない分類理由.

    Returns:
        ReplayDownloadParseResult: malformed request用のfallback branchを持つresult.
    """
    return ReplayDownloadParseResult(
        branch=ReplayDownloadBranch.MALFORMED_REQUEST_PROVISIONAL,
        reason=reason,
    )


__all__ = [
    "ReplayDownloadMalformedReason",
    "ReplayDownloadParseResult",
    "ReplayDownloadQueryParser",
    "ReplayDownloadRequest",
]
