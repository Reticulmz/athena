"""Replay download query repository contract を定義する."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import TYPE_CHECKING, ClassVar, Protocol

if TYPE_CHECKING:
    from osu_server.domain.scores.score import Ruleset


class ReplayDownloadCandidateKind(StrEnum):
    """Replay download candidate の repository branch を表す.

    Args:
        なし.

    Returns:
        Enum class のため戻り値はない.

    Raises:
        なし.

    Constraints:
        Repository 内部の read model branch だけを表す. HTTP status, raw replay
        bytes, storage key, filesystem path, credential value は保持しない.
    """

    SCORE_NOT_FOUND = "score_not_found"
    HIDDEN_SCORE = "hidden_score"
    MISSING_REPLAY = "missing_replay"
    AVAILABLE_REPLAY = "available_replay"


@dataclass(slots=True, frozen=True)
class ReplayDownloadCandidateQuery:
    """Replay download candidate lookup の入力を表す.

    Args:
        score_id: Parsed score identifier.
        ruleset: Parsed Stable ruleset scope.

    Returns:
        Dataclass のため戻り値はない.

    Raises:
        なし.

    Constraints:
        Transport query string, auth credential, SQLAlchemy object, storage backend
        detail は含めない. 入力値の parse validation は transport mapper が行う.
    """

    score_id: int
    ruleset: Ruleset


@dataclass(slots=True, frozen=True)
class ReplayDownloadScoreNotFoundCandidate:
    """Score が存在しない candidate branch を表す.

    Args:
        なし.

    Returns:
        Dataclass のため戻り値はない.

    Raises:
        なし.

    Constraints:
        Score の不存在だけを表し, storage や visibility の詳細を保持しない.
    """

    kind: ClassVar[ReplayDownloadCandidateKind] = ReplayDownloadCandidateKind.SCORE_NOT_FOUND


@dataclass(slots=True, frozen=True)
class ReplayDownloadHiddenScoreCandidate:
    """Replay download から隠す score の candidate branch を表す.

    Args:
        なし.

    Returns:
        Dataclass のため戻り値はない.

    Raises:
        なし.

    Constraints:
        Client-visible response へ visibility reason を漏らさないため,
        visibility detail や owner policy detail は保持しない.
    """

    kind: ClassVar[ReplayDownloadCandidateKind] = ReplayDownloadCandidateKind.HIDDEN_SCORE


@dataclass(slots=True, frozen=True)
class ReplayDownloadMissingReplayCandidate:
    """Replay attachment が存在しない candidate branch を表す.

    Args:
        なし.

    Returns:
        Dataclass のため戻り値はない.

    Raises:
        なし.

    Constraints:
        Missing replay の内部原因や storage backend detail は保持しない.
        Provisional response label への変換は query use-case 以降が担当する.
    """

    kind: ClassVar[ReplayDownloadCandidateKind] = ReplayDownloadCandidateKind.MISSING_REPLAY


@dataclass(slots=True, frozen=True)
class ReplayDownloadAvailableReplayCandidate:
    """利用可能な Replay attachment metadata の candidate branch を表す.

    Args:
        blob_id: Stored Replay blob を参照する identifier.
        checksum: Replay attachment metadata の checksum.
        byte_size: Replay attachment metadata の byte size.

    Returns:
        Dataclass のため戻り値はない.

    Raises:
        なし.

    Constraints:
        Raw replay bytes, storage key, filesystem path, local artifact path,
        credential value は保持しない. Blob の存在確認と byte read は別 boundary
        が担当する.
    """

    blob_id: int
    checksum: str
    byte_size: int

    kind: ClassVar[ReplayDownloadCandidateKind] = ReplayDownloadCandidateKind.AVAILABLE_REPLAY


type ReplayDownloadCandidate = (
    ReplayDownloadScoreNotFoundCandidate
    | ReplayDownloadHiddenScoreCandidate
    | ReplayDownloadMissingReplayCandidate
    | ReplayDownloadAvailableReplayCandidate
)


class ReplayDownloadQueryRepository(Protocol):
    """Replay download candidate を読む query repository port.

    Args:
        なし.

    Returns:
        Protocol class のため戻り値はない.

    Raises:
        なし.

    Constraints:
        Read-only boundary として score visibility, replay attachment metadata,
        blob id だけを投影する. SQLAlchemy, Starlette/FastAPI, Valkey, taskiq,
        services, transports, jobs, infrastructure, storage backend は import しない.
    """

    async def get_candidate(
        self,
        query: ReplayDownloadCandidateQuery,
    ) -> ReplayDownloadCandidate:
        """Replay download candidate branch を返す.

        Args:
            query: Parsed score id と ruleset scope.

        Returns:
            Score not found, hidden score, missing replay, available replay の
            いずれかの candidate branch.

        Raises:
            実装依存の永続化例外をそのまま送出する可能性がある.

        Constraints:
            Available replay branch でも raw replay bytes, storage key,
            filesystem path, local artifact path は返さない.
        """
        ...


__all__ = [
    "ReplayDownloadAvailableReplayCandidate",
    "ReplayDownloadCandidate",
    "ReplayDownloadCandidateKind",
    "ReplayDownloadCandidateQuery",
    "ReplayDownloadHiddenScoreCandidate",
    "ReplayDownloadMissingReplayCandidate",
    "ReplayDownloadQueryRepository",
    "ReplayDownloadScoreNotFoundCandidate",
]
