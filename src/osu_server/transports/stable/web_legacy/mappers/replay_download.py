"""Stable legacy replay download query mapper."""

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
    """Replay download query parse の sanitized fallback reason を表す.

    Args:
        なし.

    Returns:
        Enum class のため戻り値はない.

    Raises:
        なし.

    Constraints:
        Raw query value, username, password hash, field value は保持しない.
        値は provisional fallback classification だけに使う.
    """

    MISSING_SCORE_ID = "missing_score_id"
    MALFORMED_SCORE_ID = "malformed_score_id"
    MISSING_MODE = "missing_mode"
    MALFORMED_MODE = "malformed_mode"
    UNKNOWN_FIELD = "unknown_field"


@dataclass(slots=True, frozen=True)
class ReplayDownloadRequest:
    """Replay download query から parse 済み request を表す.

    Args:
        score_id: `c` から parse した score identifier.
        ruleset: `m` から parse した Stable ruleset.

    Returns:
        Dataclass のため戻り値はない.

    Raises:
        なし.

    Constraints:
        `u` と `h` は auth mapping 専用のため保持しない. Repr には parse
        後の値も出さず, raw query value の failure output 混入を避ける.
    """

    score_id: int = field(repr=False)
    ruleset: Ruleset = field(repr=False)


@dataclass(slots=True, frozen=True)
class ReplayDownloadParseResult:
    """Replay download query parser の sanitized result を表す.

    Args:
        request: Parse に成功した typed request.
        branch: Parse に失敗した場合の provisional fallback branch.
        reason: Parse に失敗した場合の sanitized reason.

    Returns:
        Dataclass のため戻り値はない.

    Raises:
        なし.

    Constraints:
        Whole query mapping, raw query value, username, password hash は保持しない.
        `request` は repr から除外し, test failure output に raw query value を
        残さない.
    """

    request: ReplayDownloadRequest | None = field(default=None, repr=False)
    branch: ReplayDownloadBranch | None = None
    reason: ReplayDownloadMalformedReason | None = None


class ReplayDownloadQueryParser:
    """Stable legacy replay download query を typed request に変換する.

    Args:
        なし.

    Returns:
        Parser class のため戻り値はない.

    Raises:
        なし.

    Constraints:
        `c` と `m` だけを request に parse する. `u` と `h` は auth mapping
        専用なので保持しない. Missing, malformed, unknown field は target-confirmed
        behavior ではなく provisional fallback として分類する.
    """

    def parse(self, query: Mapping[str, str]) -> ReplayDownloadParseResult:
        """Replay download query を sanitized parse result に変換する.

        Args:
            query: Starlette QueryParams 互換または plain mapping の query values.

        Returns:
            Valid request または provisional malformed fallback result.

        Raises:
            なし.

        Constraints:
            Query mapping 全体, raw query value, `u`, `h` は返さない.
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
    if raw_score_id is None:
        return ReplayDownloadMalformedReason.MISSING_SCORE_ID

    try:
        return int(raw_score_id)
    except ValueError:
        return ReplayDownloadMalformedReason.MALFORMED_SCORE_ID


def _parse_ruleset(raw_ruleset: str | None) -> Ruleset | ReplayDownloadMalformedReason:
    if raw_ruleset is None:
        return ReplayDownloadMalformedReason.MISSING_MODE

    try:
        return Ruleset(int(raw_ruleset))
    except ValueError:
        return ReplayDownloadMalformedReason.MALFORMED_MODE


def _malformed_result(reason: ReplayDownloadMalformedReason) -> ReplayDownloadParseResult:
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
