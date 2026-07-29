"""Replay download query repositoryのcandidate契約を検証するtests."""

from __future__ import annotations

from dataclasses import dataclass, fields

from osu_server.domain.scores.score import Ruleset
from osu_server.repositories.interfaces.queries.replay_download import (
    ReplayDownloadAvailableReplayCandidate,
    ReplayDownloadCandidate,
    ReplayDownloadCandidateKind,
    ReplayDownloadCandidateQuery,
    ReplayDownloadHiddenScoreCandidate,
    ReplayDownloadMissingReplayCandidate,
    ReplayDownloadQueryRepository,
    ReplayDownloadScoreNotFoundCandidate,
)


@dataclass(frozen=True, slots=True)
class _FakeReplayAttachment:
    """replay downloadのattachment metadataを表すtyped fake.

    Attributes:
        blob_id (int): storage blobを識別するID.
        checksum (str): blob contentを識別するchecksum.
        byte_size (int): download対象のbyte数.
    """

    blob_id: int
    checksum: str
    byte_size: int


@dataclass(frozen=True, slots=True)
class _FakeReplayDownloadCandidateRow:
    """replay download queryが読むscore rowを表すtyped fake.

    Attributes:
        score_id (int): queryで照合するscore ID.
        ruleset (Ruleset): scoreが属するruleset.
        hidden (bool): scoreをdownload対象から隠すか.
        replay (_FakeReplayAttachment | None): replayがある場合のattachment metadata.
        score_owner_user_id (int): scoreを提出したuser ID.
    """

    score_id: int
    ruleset: Ruleset
    hidden: bool
    replay: _FakeReplayAttachment | None
    score_owner_user_id: int = 0


class _TypedFakeReplayDownloadQueryRepository:
    """row fixtureからReplayDownloadCandidateを返すtyped fake repository.

    Attributes:
        _rows (tuple[_FakeReplayDownloadCandidateRow, ...]): query時に照合する固定row群.
    """

    def __init__(self, rows: tuple[_FakeReplayDownloadCandidateRow, ...]) -> None:
        """queryに使用するcandidate row群を保持する.

        Args:
            rows (tuple[_FakeReplayDownloadCandidateRow, ...]): score IDとrulesetで照合するrow群.
        """
        self._rows: tuple[_FakeReplayDownloadCandidateRow, ...] = rows

    async def get_candidate(
        self,
        query: ReplayDownloadCandidateQuery,
    ) -> ReplayDownloadCandidate:
        """queryに一致するscore rowを公開可能なcandidate種別へ写す.

        Args:
            query (ReplayDownloadCandidateQuery): score IDとrulesetを指定するread query.

        Returns:
            ReplayDownloadCandidate: score状態に応じた4種のcandidate.
        """
        for row in self._rows:
            if row.score_id != query.score_id or row.ruleset is not query.ruleset:
                continue
            if row.hidden:
                return ReplayDownloadHiddenScoreCandidate()
            if row.replay is None:
                return ReplayDownloadMissingReplayCandidate()
            return ReplayDownloadAvailableReplayCandidate(
                score_id=row.score_id,
                score_owner_user_id=row.score_owner_user_id,
                blob_id=row.replay.blob_id,
                checksum=row.replay.checksum,
                byte_size=row.replay.byte_size,
            )

        return ReplayDownloadScoreNotFoundCandidate()


async def test_candidate_contract_distinguishes_missing_score() -> None:
    """一致するscoreがないqueryをSCORE_NOT_FOUNDへ写す契約を検証する.

    異なるscore IDのrowだけを用意し, replay欠落とは区別したscore不在candidateを返すことを確認する.

    Returns:
        None: score不在のcandidate種別を検証して完了し, 呼び出し側へ値を返さない.
    """
    repository = _repository(
        (
            _FakeReplayDownloadCandidateRow(
                score_id=10,
                ruleset=Ruleset.OSU,
                hidden=False,
                replay=None,
            ),
        )
    )

    result = await repository.get_candidate(
        ReplayDownloadCandidateQuery(score_id=999, ruleset=Ruleset.OSU)
    )

    assert isinstance(result, ReplayDownloadScoreNotFoundCandidate)
    assert result.kind is ReplayDownloadCandidateKind.SCORE_NOT_FOUND


async def test_candidate_contract_distinguishes_hidden_score() -> None:
    """隠されたscoreをHIDDEN_SCORE candidateへ写す契約を検証する.

    replay metadataを持つhidden rowをqueryし,
    attachment内容を公開せずhidden種別を返すことを確認する.

    Returns:
        None: hidden scoreのcandidate種別を検証して完了し, 呼び出し側へ値を返さない.
    """
    repository = _repository(
        (
            _FakeReplayDownloadCandidateRow(
                score_id=11,
                ruleset=Ruleset.OSU,
                hidden=True,
                replay=_FakeReplayAttachment(
                    blob_id=101,
                    checksum="synthetic-hidden-checksum",
                    byte_size=2048,
                ),
            ),
        )
    )

    result = await repository.get_candidate(
        ReplayDownloadCandidateQuery(score_id=11, ruleset=Ruleset.OSU)
    )

    assert isinstance(result, ReplayDownloadHiddenScoreCandidate)
    assert result.kind is ReplayDownloadCandidateKind.HIDDEN_SCORE


async def test_candidate_contract_distinguishes_missing_replay() -> None:
    """可視scoreでreplayがない場合をMISSING_REPLAYへ写す契約を検証する.

    一致するvisible rowにreplay metadataを置かず,
    score不在ではない欠落candidateを返すことを確認する.

    Returns:
        None: replay不在のcandidate種別を検証して完了し, 呼び出し側へ値を返さない.
    """
    repository = _repository(
        (
            _FakeReplayDownloadCandidateRow(
                score_id=12,
                ruleset=Ruleset.OSU,
                hidden=False,
                replay=None,
            ),
        )
    )

    result = await repository.get_candidate(
        ReplayDownloadCandidateQuery(score_id=12, ruleset=Ruleset.OSU)
    )

    assert isinstance(result, ReplayDownloadMissingReplayCandidate)
    assert result.kind is ReplayDownloadCandidateKind.MISSING_REPLAY


async def test_available_replay_candidate_exposes_only_attachment_metadata() -> None:
    """利用可能なreplayが許可済みattachment metadataだけを公開する契約を検証する.

    visible rowのcandidateを読み,
    IDとchecksumとbyte数は含むがpayloadやstorage pathを含まないことを確認する.

    Returns:
        None: download境界の公開fieldを検証して完了し, 呼び出し側へ値を返さない.
    """
    checksum = "synthetic-available-checksum"
    repository = _repository(
        (
            _FakeReplayDownloadCandidateRow(
                score_id=13,
                score_owner_user_id=27,
                ruleset=Ruleset.OSU,
                hidden=False,
                replay=_FakeReplayAttachment(
                    blob_id=102,
                    checksum=checksum,
                    byte_size=4096,
                ),
            ),
        )
    )

    result = await repository.get_candidate(
        ReplayDownloadCandidateQuery(score_id=13, ruleset=Ruleset.OSU)
    )

    assert result == ReplayDownloadAvailableReplayCandidate(
        score_id=13,
        score_owner_user_id=27,
        blob_id=102,
        checksum=checksum,
        byte_size=4096,
    )
    assert result.kind is ReplayDownloadCandidateKind.AVAILABLE_REPLAY
    assert tuple(field.name for field in fields(result)) == (
        "score_id",
        "score_owner_user_id",
        "blob_id",
        "checksum",
        "byte_size",
    )
    assert not hasattr(result, "payload")
    assert not hasattr(result, "raw_bytes")
    assert not hasattr(result, "storage_key")
    assert not hasattr(result, "filesystem_path")
    assert not hasattr(result, "query_string")
    assert not hasattr(result, "session_token")
    assert checksum not in repr(result)


async def test_candidate_query_includes_ruleset_scope() -> None:
    """Candidate queryがscore IDだけでなくrulesetも照合する契約を検証する.

    同じscore IDで別rulesetのrowを用意し, ruleset不一致をscore不在として扱うことを確認する.

    Returns:
        None: ruleset境界のcandidate種別を検証して完了し, 呼び出し側へ値を返さない.
    """
    repository = _repository(
        (
            _FakeReplayDownloadCandidateRow(
                score_id=14,
                ruleset=Ruleset.TAIKO,
                hidden=False,
                replay=_FakeReplayAttachment(
                    blob_id=103,
                    checksum="synthetic-taiko-checksum",
                    byte_size=512,
                ),
            ),
        )
    )

    result = await repository.get_candidate(
        ReplayDownloadCandidateQuery(score_id=14, ruleset=Ruleset.OSU)
    )

    assert isinstance(result, ReplayDownloadScoreNotFoundCandidate)
    assert result.kind is ReplayDownloadCandidateKind.SCORE_NOT_FOUND


def _repository(
    rows: tuple[_FakeReplayDownloadCandidateRow, ...],
) -> ReplayDownloadQueryRepository:
    """Candidate contract test用のtyped fake repositoryを構築する.

    Args:
        rows (tuple[_FakeReplayDownloadCandidateRow, ...]): queryに返させる固定candidate row群.

    Returns:
        ReplayDownloadQueryRepository: protocol型で公開するtyped fake repository.
    """
    return _TypedFakeReplayDownloadQueryRepository(rows)
