"""Replay download query repository contract を定義する."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from typing import TYPE_CHECKING, ClassVar, Protocol

if TYPE_CHECKING:
    from osu_server.domain.scores.score import Ruleset


class ReplayDownloadCandidateKind(StrEnum):
    """Replay download candidate の repository branch を表す.

    Attributes:
        SCORE_NOT_FOUND (ReplayDownloadCandidateKind): Score が存在しない branch.
        HIDDEN_SCORE (ReplayDownloadCandidateKind): Viewer に隠す Score の branch.
        MISSING_REPLAY (ReplayDownloadCandidateKind): Replay attachment がない branch.
        AVAILABLE_REPLAY (ReplayDownloadCandidateKind): Replay metadata が利用可能な branch.

    Notes:
        この Enum は repository 内部の read model branch だけを表す. HTTP status, raw replay
        bytes, storage key, filesystem path, credential value は保持しない.
    """

    SCORE_NOT_FOUND = "score_not_found"
    HIDDEN_SCORE = "hidden_score"
    MISSING_REPLAY = "missing_replay"
    AVAILABLE_REPLAY = "available_replay"


@dataclass(slots=True, frozen=True)
class ReplayDownloadCandidateQuery:
    """Replay download candidate lookup の入力を表す.

    Attributes:
        score_id (int): 検索する parsed Score identifier.
        ruleset (Ruleset): 検索する parsed Stable ruleset scope.

    Notes:
        Transport query string, auth credential, SQLAlchemy object, storage backend detail は
        含めない. Input value の parse validation は transport mapper が行う.
    """

    score_id: int
    ruleset: Ruleset


@dataclass(slots=True, frozen=True)
class ReplayDownloadScoreNotFoundCandidate:
    """Score が存在しない candidate branch を表す.

    Attributes:
        kind (ClassVar[ReplayDownloadCandidateKind]): `SCORE_NOT_FOUND` branch kind.

    Notes:
        Score の不存在だけを表し storage や visibility の詳細を保持しない.
    """

    kind: ClassVar[ReplayDownloadCandidateKind] = ReplayDownloadCandidateKind.SCORE_NOT_FOUND


@dataclass(slots=True, frozen=True)
class ReplayDownloadHiddenScoreCandidate:
    """Replay download から隠す Score の candidate branch を表す.

    Attributes:
        kind (ClassVar[ReplayDownloadCandidateKind]): `HIDDEN_SCORE` branch kind.

    Notes:
        Client-visible response へ visibility reason を漏らさないため visibility detail や
        owner policy detail は保持しない.
    """

    kind: ClassVar[ReplayDownloadCandidateKind] = ReplayDownloadCandidateKind.HIDDEN_SCORE


@dataclass(slots=True, frozen=True)
class ReplayDownloadMissingReplayCandidate:
    """Replay attachment が存在しない candidate branch を表す.

    Attributes:
        kind (ClassVar[ReplayDownloadCandidateKind]): `MISSING_REPLAY` branch kind.

    Notes:
        Missing replay の内部原因や storage backend detail は保持しない. Provisional response
        label への変換は query use-case 以降が担当する.
    """

    kind: ClassVar[ReplayDownloadCandidateKind] = ReplayDownloadCandidateKind.MISSING_REPLAY


@dataclass(slots=True, frozen=True)
class ReplayDownloadAvailableReplayCandidate:
    """利用可能な Replay attachment metadata の candidate branch を表す.

    Attributes:
        score_id (int): Accounting 対象になる Score identifier.
        score_owner_user_id (int): Self-view 判定に使う Score owner User ID.
        blob_id (int): Stored Replay Blob を参照する identifier.
        checksum (str): Replay attachment metadata の checksum.
        byte_size (int): Replay attachment metadata の byte size.
        kind (ClassVar[ReplayDownloadCandidateKind]): `AVAILABLE_REPLAY` branch kind.

    Notes:
        Raw replay bytes, storage key, filesystem path, local artifact path, credential value は
        保持しない. Blob の存在確認と byte read は別 boundary が担当する. Accounting 用 identity
        は Score ID と owner User ID だけに限定する.
    """

    score_id: int = field(repr=False)
    score_owner_user_id: int = field(repr=False)
    blob_id: int
    checksum: str = field(repr=False)
    byte_size: int

    kind: ClassVar[ReplayDownloadCandidateKind] = ReplayDownloadCandidateKind.AVAILABLE_REPLAY


type ReplayDownloadCandidate = (
    ReplayDownloadScoreNotFoundCandidate
    | ReplayDownloadHiddenScoreCandidate
    | ReplayDownloadMissingReplayCandidate
    | ReplayDownloadAvailableReplayCandidate
)


class ReplayDownloadQueryRepository(Protocol):
    """Replay download candidate を読む read-only query repository port を定義する.

    Notes:
        Read-only boundary として Score visibility, Replay attachment metadata, Blob ID だけを
        投影する. Score view count や durable state を変更せず Command Unit of Work を開始または
        commit/rollback しない. SQLAlchemy, Starlette/FastAPI, Valkey, taskiq, services,
        transports, jobs, infrastructure, storage backend は import しない.
    """

    async def get_candidate(
        self,
        query: ReplayDownloadCandidateQuery,
    ) -> ReplayDownloadCandidate:
        """Replay download candidate branch を返す.

        Args:
            query (ReplayDownloadCandidateQuery): Parsed Score ID と ruleset scope.

        Returns:
            ReplayDownloadCandidate: Score not found, hidden Score, missing Replay, available
            Replay のいずれかの candidate branch.

        Notes:
            Available Replay branch でも raw replay bytes, storage key, filesystem path, local
            artifact path は返さない. View count の accounting はこの query の責務ではない.
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
