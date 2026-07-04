"""Replay download query use-case の tests."""

from __future__ import annotations

from dataclasses import dataclass
from typing import final

from osu_server.domain.compatibility.stable import (
    ReplayDownloadBodyStrategy,
    ReplayDownloadBranch,
)
from osu_server.domain.scores import Ruleset
from osu_server.repositories.interfaces.queries.replay_download import (
    ReplayDownloadAvailableReplayCandidate,
    ReplayDownloadCandidate,
    ReplayDownloadCandidateQuery,
    ReplayDownloadHiddenScoreCandidate,
    ReplayDownloadMissingReplayCandidate,
    ReplayDownloadScoreNotFoundCandidate,
)
from osu_server.services.queries.scores import (
    ReplayDownloadBodyAssembler,
    ReplayDownloadBodyBuildInput,
    ReplayDownloadBodyBuildResult,
    ReplayDownloadQuery,
    ReplayDownloadQueryInput,
)
from osu_server.services.queries.storage import BlobBytesUnavailableError


async def test_score_not_found_candidate_returns_hidden_score_without_blob_read() -> None:
    harness = _make_harness(candidate=ReplayDownloadScoreNotFoundCandidate())

    result = await harness.query.execute(_input(score_id=910, ruleset=Ruleset.TAIKO))

    assert harness.repository.requests == [
        ReplayDownloadCandidateQuery(score_id=910, ruleset=Ruleset.TAIKO)
    ]
    assert result.branch is ReplayDownloadBranch.HIDDEN_SCORE
    assert result.response_body is None
    assert result.is_success is False
    _assert_available_replay_collaborators_not_called(harness)


async def test_hidden_score_candidate_returns_hidden_score_without_blob_read() -> None:
    harness = _make_harness(candidate=ReplayDownloadHiddenScoreCandidate())

    result = await harness.query.execute(_input())

    assert result.branch is ReplayDownloadBranch.HIDDEN_SCORE
    assert result.response_body is None
    assert result.is_success is False
    _assert_available_replay_collaborators_not_called(harness)


async def test_missing_replay_candidate_returns_provisional_branch_without_blob_read() -> None:
    harness = _make_harness(candidate=ReplayDownloadMissingReplayCandidate())

    result = await harness.query.execute(_input())

    assert result.branch is ReplayDownloadBranch.MISSING_REPLAY_PROVISIONAL
    assert result.response_body is None
    assert result.is_success is False
    _assert_available_replay_collaborators_not_called(harness)


async def test_available_replay_with_blob_unavailable_returns_storage_missing() -> None:
    storage_detail = BackendStorageDetailError(
        "storage_key=SYNTHETIC_INTERNAL_STORAGE_KEY",
    )
    harness = _make_harness(
        candidate=_available_replay(blob_id=707),
        blob_error=storage_detail,
    )

    result = await harness.query.execute(_input())

    assert result.branch is ReplayDownloadBranch.STORAGE_MISSING
    assert result.response_body is None
    assert result.is_success is False
    assert harness.blob_reader.read_blob_ids == [707]
    assert harness.body_assembler.inputs == []
    result_repr = repr(result)
    assert "SYNTHETIC_INTERNAL_STORAGE_KEY" not in result_repr
    assert "storage_key" not in result_repr


async def test_available_replay_with_default_strategy_returns_body_strategy_blocked() -> None:
    harness = _make_harness(
        candidate=_available_replay(blob_id=808),
        blob_payload=b"synthetic-default-blocked",
    )

    result = await harness.query.execute(_input())

    assert result.branch is ReplayDownloadBranch.BODY_STRATEGY_BLOCKED
    assert result.response_body is None
    assert result.is_success is False
    assert harness.blob_reader.read_blob_ids == [808]
    assert [entry.strategy for entry in harness.body_assembler.inputs] == [
        ReplayDownloadBodyStrategy.BLOCKED
    ]
    assert harness.body_assembler.inputs[0].stored_blob.payload == (b"synthetic-default-blocked")
    assert harness.repository.replay_view_update_count == 0
    assert harness.repository.latest_activity_update_count == 0


async def test_available_replay_with_direct_strategy_returns_exact_blob_bytes() -> None:
    replay_payload = b"synthetic-direct-response-body"
    harness = _make_harness(
        candidate=_available_replay(blob_id=909),
        blob_payload=replay_payload,
        body_strategy=ReplayDownloadBodyStrategy.DIRECT_BLOB_BYTES,
    )

    result = await harness.query.execute(_input())

    assert result.branch is ReplayDownloadBranch.SUCCESS
    assert result.response_body is not None
    assert result.response_body.payload == replay_payload
    assert result.response_body.byte_size == len(replay_payload)
    assert result.is_success is True
    assert harness.blob_reader.read_blob_ids == [909]
    assert [entry.strategy for entry in harness.body_assembler.inputs] == [
        ReplayDownloadBodyStrategy.DIRECT_BLOB_BYTES
    ]
    assert harness.repository.replay_view_update_count == 0
    assert harness.repository.latest_activity_update_count == 0


async def test_available_replay_with_assemble_strategy_remains_blocked() -> None:
    harness = _make_harness(
        candidate=_available_replay(blob_id=1001),
        blob_payload=b"synthetic-assemble-blocked",
        body_strategy=ReplayDownloadBodyStrategy.ASSEMBLE_DOWNLOAD_BODY,
    )

    result = await harness.query.execute(_input())

    assert result.branch is ReplayDownloadBranch.BODY_STRATEGY_BLOCKED
    assert result.response_body is None
    assert result.is_success is False
    assert harness.blob_reader.read_blob_ids == [1001]
    assert [entry.strategy for entry in harness.body_assembler.inputs] == [
        ReplayDownloadBodyStrategy.ASSEMBLE_DOWNLOAD_BODY
    ]


@final
class BackendStorageDetailError(FileNotFoundError):
    """Storage backend の内部 detail を模した test-only error."""


@final
class ReplayDownloadQueryRepositoryStub:
    """Replay download candidate repository の typed test double."""

    def __init__(self, candidate: ReplayDownloadCandidate) -> None:
        self._candidate: ReplayDownloadCandidate = candidate
        self.requests: list[ReplayDownloadCandidateQuery] = []
        self.replay_view_update_count = 0
        self.latest_activity_update_count = 0

    async def get_candidate(
        self,
        query: ReplayDownloadCandidateQuery,
    ) -> ReplayDownloadCandidate:
        """Replay download candidate query を記録して candidate を返す."""
        self.requests.append(query)
        return self._candidate

    async def record_replay_view(self) -> None:
        """将来の replay view mutation が呼ばれた場合に記録する."""
        self.replay_view_update_count += 1

    async def touch_latest_activity(self) -> None:
        """将来の latest activity mutation が呼ばれた場合に記録する."""
        self.latest_activity_update_count += 1


@final
class BlobByteReaderStub:
    """Replay blob bytes reader の typed test double."""

    def __init__(
        self,
        *,
        payload: bytes = b"synthetic-stored-replay",
        unavailable_cause: Exception | None = None,
    ) -> None:
        self._payload: bytes = payload
        self._unavailable_cause: Exception | None = unavailable_cause
        self.read_blob_ids: list[int] = []

    async def read_bytes(self, blob_id: int) -> bytes:
        """blob id を記録し, 設定済み bytes または unavailable error を返す."""
        self.read_blob_ids.append(blob_id)
        if self._unavailable_cause is not None:
            raise BlobBytesUnavailableError(blob_id) from self._unavailable_cause
        return self._payload


@final
class RecordingReplayDownloadBodyAssembler:
    """Replay download body assembler の typed recording test double."""

    def __init__(self) -> None:
        self._assembler = ReplayDownloadBodyAssembler()
        self.inputs: list[ReplayDownloadBodyBuildInput] = []

    def build(
        self,
        input_data: ReplayDownloadBodyBuildInput,
    ) -> ReplayDownloadBodyBuildResult:
        """build input を記録して production assembler へ委譲する."""
        self.inputs.append(input_data)
        return self._assembler.build(input_data)


@dataclass(slots=True, frozen=True)
class ReplayDownloadQueryHarness:
    """Replay download query test collaborators をまとめる."""

    query: ReplayDownloadQuery
    repository: ReplayDownloadQueryRepositoryStub
    blob_reader: BlobByteReaderStub
    body_assembler: RecordingReplayDownloadBodyAssembler


def _make_harness(
    *,
    candidate: ReplayDownloadCandidate,
    blob_payload: bytes = b"synthetic-stored-replay",
    blob_error: Exception | None = None,
    body_strategy: ReplayDownloadBodyStrategy = ReplayDownloadBodyStrategy.BLOCKED,
) -> ReplayDownloadQueryHarness:
    repository = ReplayDownloadQueryRepositoryStub(candidate)
    blob_reader = BlobByteReaderStub(
        payload=blob_payload,
        unavailable_cause=blob_error,
    )
    body_assembler = RecordingReplayDownloadBodyAssembler()
    query = ReplayDownloadQuery(
        repository=repository,
        blob_reader=blob_reader,
        body_assembler=body_assembler,
        body_strategy=body_strategy,
    )
    return ReplayDownloadQueryHarness(
        query=query,
        repository=repository,
        blob_reader=blob_reader,
        body_assembler=body_assembler,
    )


def _input(
    *,
    score_id: int = 101,
    ruleset: Ruleset = Ruleset.OSU,
) -> ReplayDownloadQueryInput:
    return ReplayDownloadQueryInput(
        authenticated_user_id=202,
        score_id=score_id,
        ruleset=ruleset,
    )


def _available_replay(blob_id: int) -> ReplayDownloadAvailableReplayCandidate:
    return ReplayDownloadAvailableReplayCandidate(
        blob_id=blob_id,
        checksum="synthetic-checksum",
        byte_size=24,
    )


def _assert_available_replay_collaborators_not_called(
    harness: ReplayDownloadQueryHarness,
) -> None:
    assert harness.blob_reader.read_blob_ids == []
    assert harness.body_assembler.inputs == []
    assert harness.repository.replay_view_update_count == 0
    assert harness.repository.latest_activity_update_count == 0
