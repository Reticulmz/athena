"""Replay download query use-case の tests."""

from __future__ import annotations

from dataclasses import dataclass
from hashlib import sha256
from typing import Final, final

import pytest

from osu_server.domain.compatibility.stable import (
    ReplayDownloadBodyStrategy,
    ReplayDownloadBranch,
    ReplayDownloadResponseBody,
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
    ReplayDownloadAccountingMetadata,
    ReplayDownloadBodyAssembler,
    ReplayDownloadBodyBuildInput,
    ReplayDownloadBodyBuildResult,
    ReplayDownloadQuery,
    ReplayDownloadQueryInput,
    ReplayDownloadQueryResult,
)
from osu_server.services.queries.storage import BlobBytesUnavailableError

_PRIVATE_SENTINELS: Final[tuple[str, ...]] = (
    "synthetic-private-storage-detail",
    "synthetic-private-credential-value",
    "synthetic-private-query-value",
    "synthetic-private-artifact-reference",
)


async def test_score_not_found_candidate_returns_hidden_score_without_blob_read() -> None:
    harness = _make_harness(candidate=ReplayDownloadScoreNotFoundCandidate())
    input_data = _input(score_id=910, ruleset=Ruleset.TAIKO)

    result = await harness.query.execute(input_data)

    assert harness.repository.requests == [
        ReplayDownloadCandidateQuery(score_id=910, ruleset=Ruleset.TAIKO)
    ]
    assert result.branch is ReplayDownloadBranch.HIDDEN_SCORE
    _assert_failure_result_has_no_client_visible_details(
        result,
        input_data.score_id,
        input_data.authenticated_user_id,
    )
    _assert_available_replay_collaborators_not_called(harness)


async def test_hidden_score_candidate_returns_hidden_score_without_blob_read() -> None:
    harness = _make_harness(candidate=ReplayDownloadHiddenScoreCandidate())
    input_data = _input(score_id=303)

    result = await harness.query.execute(input_data)

    assert result.branch is ReplayDownloadBranch.HIDDEN_SCORE
    _assert_failure_result_has_no_client_visible_details(
        result,
        input_data.score_id,
        input_data.authenticated_user_id,
    )
    _assert_available_replay_collaborators_not_called(harness)


async def test_missing_replay_candidate_returns_provisional_branch_without_blob_read() -> None:
    harness = _make_harness(candidate=ReplayDownloadMissingReplayCandidate())
    input_data = _input(score_id=404)

    result = await harness.query.execute(input_data)

    assert result.branch is ReplayDownloadBranch.MISSING_REPLAY_PROVISIONAL
    _assert_failure_result_has_no_client_visible_details(
        result,
        input_data.score_id,
        input_data.authenticated_user_id,
    )
    _assert_available_replay_collaborators_not_called(harness)


async def test_available_replay_with_blob_unavailable_returns_storage_missing() -> None:
    storage_detail = BackendStorageDetailError(" ".join(_PRIVATE_SENTINELS))
    harness = _make_harness(
        candidate=_available_replay(blob_id=707),
        blob_error=storage_detail,
    )

    result = await harness.query.execute(_input())

    assert result.branch is ReplayDownloadBranch.STORAGE_MISSING
    _assert_failure_result_has_no_client_visible_details(result, storage_detail)
    assert harness.blob_reader.read_blob_ids == [707]
    assert harness.body_assembler.inputs == []


async def test_available_replay_with_default_strategy_returns_body_strategy_blocked() -> None:
    stored_blob_payload = b"bk"
    harness = _make_harness(
        candidate=_available_replay(blob_id=808, payload=stored_blob_payload),
        blob_payload=stored_blob_payload,
    )

    result = await harness.query.execute(_input())

    assert result.branch is ReplayDownloadBranch.BODY_STRATEGY_BLOCKED
    _assert_failure_result_has_no_client_visible_details(result, stored_blob_payload)
    assert harness.blob_reader.read_blob_ids == [808]
    assert [entry.strategy for entry in harness.body_assembler.inputs] == [
        ReplayDownloadBodyStrategy.BLOCKED
    ]
    assert harness.body_assembler.inputs[0].stored_blob.byte_size == len(stored_blob_payload)
    assert harness.repository.replay_view_update_count == 0
    assert harness.repository.latest_activity_update_count == 0


async def test_available_replay_with_direct_strategy_returns_exact_blob_bytes() -> None:
    replay_payload = b"rd"
    harness = _make_harness(
        candidate=_available_replay(
            score_id=515,
            score_owner_user_id=616,
            blob_id=909,
            payload=replay_payload,
        ),
        blob_payload=replay_payload,
        body_strategy=ReplayDownloadBodyStrategy.DIRECT_BLOB_BYTES,
    )

    result = await harness.query.execute(_input())

    assert result.branch is ReplayDownloadBranch.SUCCESS
    assert result.response_body is not None
    assert result.response_body.payload == replay_payload
    assert result.response_body.byte_size == len(replay_payload)
    assert result.accounting_metadata is not None
    assert isinstance(result.accounting_metadata, ReplayDownloadAccountingMetadata)
    assert result.accounting_metadata.score_id == 515
    assert result.accounting_metadata.score_owner_user_id == 616
    assert result.is_success is True
    assert harness.blob_reader.read_blob_ids == [909]
    assert [entry.strategy for entry in harness.body_assembler.inputs] == [
        ReplayDownloadBodyStrategy.DIRECT_BLOB_BYTES
    ]
    assert harness.repository.replay_view_update_count == 0
    assert harness.repository.latest_activity_update_count == 0
    assert repr(replay_payload) not in repr(result)
    assert "score_owner_user_id=616" not in repr(result)


def test_success_result_rejects_missing_accounting_metadata() -> None:
    with pytest.raises(
        ValueError,
        match="success replay download query result requires accounting metadata",
    ):
        _ = ReplayDownloadQueryResult(
            branch=ReplayDownloadBranch.SUCCESS,
            response_body=ReplayDownloadResponseBody(payload=b"rd"),
        )


def test_non_success_result_rejects_accounting_metadata() -> None:
    with pytest.raises(
        ValueError,
        match="non-success replay download query result must not include accounting metadata",
    ):
        _ = ReplayDownloadQueryResult(
            branch=ReplayDownloadBranch.HIDDEN_SCORE,
            accounting_metadata=ReplayDownloadAccountingMetadata(
                score_id=1,
                score_owner_user_id=2,
            ),
        )


async def test_available_replay_with_assemble_strategy_remains_blocked() -> None:
    stored_blob_payload = b"as"
    harness = _make_harness(
        candidate=_available_replay(blob_id=1001, payload=stored_blob_payload),
        blob_payload=stored_blob_payload,
        body_strategy=ReplayDownloadBodyStrategy.ASSEMBLE_DOWNLOAD_BODY,
    )

    result = await harness.query.execute(_input())

    assert result.branch is ReplayDownloadBranch.BODY_STRATEGY_BLOCKED
    _assert_failure_result_has_no_client_visible_details(result, stored_blob_payload)
    assert harness.blob_reader.read_blob_ids == [1001]
    assert [entry.strategy for entry in harness.body_assembler.inputs] == [
        ReplayDownloadBodyStrategy.ASSEMBLE_DOWNLOAD_BODY
    ]


async def test_available_replay_with_byte_size_mismatch_returns_storage_missing() -> None:
    replay_payload = b"size-mismatch"
    harness = _make_harness(
        candidate=_available_replay(
            blob_id=1101,
            payload=replay_payload,
            byte_size=len(replay_payload) + 1,
        ),
        blob_payload=replay_payload,
        body_strategy=ReplayDownloadBodyStrategy.DIRECT_BLOB_BYTES,
    )

    result = await harness.query.execute(_input())

    assert result.branch is ReplayDownloadBranch.STORAGE_MISSING
    _assert_failure_result_has_no_client_visible_details(result, replay_payload)
    assert harness.blob_reader.read_blob_ids == [1101]
    assert harness.body_assembler.inputs == []


async def test_available_replay_with_checksum_mismatch_returns_storage_missing() -> None:
    replay_payload = b"checksum-mismatch"
    harness = _make_harness(
        candidate=_available_replay(
            blob_id=1102,
            payload=replay_payload,
            checksum="0" * 64,
        ),
        blob_payload=replay_payload,
        body_strategy=ReplayDownloadBodyStrategy.DIRECT_BLOB_BYTES,
    )

    result = await harness.query.execute(_input())

    assert result.branch is ReplayDownloadBranch.STORAGE_MISSING
    _assert_failure_result_has_no_client_visible_details(result, replay_payload)
    assert harness.blob_reader.read_blob_ids == [1102]
    assert harness.body_assembler.inputs == []


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


def _available_replay(
    *,
    score_id: int = 13,
    score_owner_user_id: int = 24,
    blob_id: int,
    payload: bytes = b"synthetic-stored-replay",
    checksum: str | None = None,
    byte_size: int | None = None,
) -> ReplayDownloadAvailableReplayCandidate:
    return ReplayDownloadAvailableReplayCandidate(
        score_id=score_id,
        score_owner_user_id=score_owner_user_id,
        blob_id=blob_id,
        checksum=checksum or sha256(payload).hexdigest(),
        byte_size=len(payload) if byte_size is None else byte_size,
    )


def _assert_available_replay_collaborators_not_called(
    harness: ReplayDownloadQueryHarness,
) -> None:
    assert harness.blob_reader.read_blob_ids == []
    assert harness.body_assembler.inputs == []
    assert harness.repository.replay_view_update_count == 0
    assert harness.repository.latest_activity_update_count == 0


def _assert_failure_result_has_no_client_visible_details(
    result: ReplayDownloadQueryResult,
    *private_values: object,
) -> None:
    assert result.is_success is False
    assert result.response_body is None
    result_repr = repr(result)
    assert "ReplayDownloadResponseBody" not in result_repr
    assert "payload" not in result_repr
    for private_value in (*_PRIVATE_SENTINELS, *private_values):
        assert str(private_value) not in result_repr
        assert repr(private_value) not in result_repr
