"""Replay download query repository contract の tests."""

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
    blob_id: int
    checksum: str
    byte_size: int


@dataclass(frozen=True, slots=True)
class _FakeReplayDownloadCandidateRow:
    score_id: int
    ruleset: Ruleset
    hidden: bool
    replay: _FakeReplayAttachment | None
    score_owner_user_id: int = 0


class _TypedFakeReplayDownloadQueryRepository:
    def __init__(self, rows: tuple[_FakeReplayDownloadCandidateRow, ...]) -> None:
        self._rows: tuple[_FakeReplayDownloadCandidateRow, ...] = rows

    async def get_candidate(
        self,
        query: ReplayDownloadCandidateQuery,
    ) -> ReplayDownloadCandidate:
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
    return _TypedFakeReplayDownloadQueryRepository(rows)
