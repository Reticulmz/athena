"""replay download query use-caseのunit testを定義する."""

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
    """score不在candidateがblob readなしでhidden scoreになる契約を検証する.

    score-not-found candidateを返すrepositoryでqueryを実行し,client-visible detailを含まない
    hidden score結果と未呼び出しのcollaboratorを確認する.

    Returns:
        None: branch,非公開failure結果,collaborator非呼び出しを検証して完了する.
    """
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
    """Hidden score candidateがblob readなしでhidden scoreになる契約を検証する.

    hidden-score candidateを返すrepositoryでqueryを実行し,client-visible detailを含まない
    hidden score結果と未呼び出しのcollaboratorを確認する.

    Returns:
        None: branch,非公開failure結果,collaborator非呼び出しを検証して完了する.
    """
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
    """Missing replay candidateがblob readなしでprovisional branchになる契約を検証する.

    missing-replay candidateを返すrepositoryでqueryを実行し,client-visible detailを含まない
    provisional結果と未呼び出しのcollaboratorを確認する.

    Returns:
        None: provisional branch,非公開failure結果,collaborator非呼び出しを検証して完了する.
    """
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
    """Blob readerのunavailableがstorage missing結果になる契約を検証する.

    利用可能なreplay candidateに内部storage errorを設定し,blob read後にprivate detailを
    露出しないstorage missing結果を返すことを確認する.

    Returns:
        None: storage missing branch,非公開failure結果,body assembler非呼び出しを
            検証して完了する.
    """
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
    """Default body strategyがaccountingなしのblocked結果になる契約を検証する.

    stored replay bytesを持つcandidateでdefault strategyを使い,blocked branchを返し
    view/activity mutationを行わないことを確認する.

    Returns:
        None: blocked branch,非公開failure結果,assembler入力,mutation不在を検証して完了する.
    """
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
    """Direct blob bytes strategyが成功bodyとaccounting metadataを返す契約を検証する.

    利用可能なreplay candidateと一致するblob bytesでqueryを実行し,payload,byte size,
    score accounting metadataを持つ成功結果を確認する.

    Returns:
        None: success branch,response body,accounting metadata,mutation不在を検証して完了する.
    """
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
    """Success replay resultがaccounting metadataを必須とする不変条件を検証する.

    success branchとresponse bodyだけでresultを構築し,accounting metadata欠落をValueErrorとして
    拒否することを確認する.

    Returns:
        None: constructorが不正なsuccess resultを拒否することを検証して完了する.
    """
    with pytest.raises(
        ValueError,
        match="success replay download query result requires accounting metadata",
    ):
        _ = ReplayDownloadQueryResult(
            branch=ReplayDownloadBranch.SUCCESS,
            response_body=ReplayDownloadResponseBody(payload=b"rd"),
        )


def test_non_success_result_rejects_accounting_metadata() -> None:
    """非success replay resultがaccounting metadataを拒否する不変条件を検証する.

    hidden score branchへaccounting metadataを与えてresultを構築し,client accountingの混入を
    ValueErrorとして拒否することを確認する.

    Returns:
        None: constructorが不正なnon-success resultを拒否することを検証して完了する.
    """
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
    """Assemble body strategyがlocal decisionなしでblockedのままになる契約を検証する.

    利用可能なreplayとassemble strategyでqueryを実行し,bodyを組み立てずblocked結果を
    返すことを確認する.

    Returns:
        None: blocked branch,非公開failure結果,assembler strategyを検証して完了する.
    """
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
    """Stored blobのbyte size不一致がstorage missing結果になる契約を検証する.

    candidateの期待byte sizeをpayloadと不一致にしてqueryを実行し,body assemblerを呼ばず
    storage missing結果を返すことを確認する.

    Returns:
        None: storage missing branch,非公開failure結果,assembler非呼び出しを検証して完了する.
    """
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
    """Stored blobのchecksum不一致がstorage missing結果になる契約を検証する.

    candidateの期待checksumをpayloadと不一致にしてqueryを実行し,body assemblerを呼ばず
    storage missing結果を返すことを確認する.

    Returns:
        None: storage missing branch,非公開failure結果,assembler非呼び出しを検証して完了する.
    """
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
    """storage backendの非公開detailを模したtest-only errorを表す."""


@final
class ReplayDownloadQueryRepositoryStub:
    """replay download candidate repositoryのtyped test doubleを提供する.

    Attributes:
        _candidate (ReplayDownloadCandidate): get_candidateで返す固定candidate.
        requests (list[ReplayDownloadCandidateQuery]): repositoryへ渡されたcandidate queryの記録.
        replay_view_update_count (int): record_replay_viewの呼び出し回数.
        latest_activity_update_count (int): touch_latest_activityの呼び出し回数.
    """

    def __init__(self, candidate: ReplayDownloadCandidate) -> None:
        """固定candidateを返すrepository stubを初期化する.

        Args:
            candidate (ReplayDownloadCandidate): get_candidateで返すsynthetic candidate.
        """
        self._candidate: ReplayDownloadCandidate = candidate
        self.requests: list[ReplayDownloadCandidateQuery] = []
        self.replay_view_update_count = 0
        self.latest_activity_update_count = 0

    async def get_candidate(
        self,
        query: ReplayDownloadCandidateQuery,
    ) -> ReplayDownloadCandidate:
        """Candidate queryを記録して固定candidateを返す.

        Args:
            query (ReplayDownloadCandidateQuery): replay download候補を取得するquery条件.

        Returns:
            ReplayDownloadCandidate: 初期化時に指定されたsynthetic candidate.
        """
        self.requests.append(query)
        return self._candidate

    async def record_replay_view(self) -> None:
        """Replay view mutationの呼び出し回数を記録する.

        Returns:
            None: 呼び出し回数を増やし,呼び出し側へ値を返さずに完了する.
        """
        self.replay_view_update_count += 1

    async def touch_latest_activity(self) -> None:
        """Latest activity mutationの呼び出し回数を記録する.

        Returns:
            None: 呼び出し回数を増やし,呼び出し側へ値を返さずに完了する.
        """
        self.latest_activity_update_count += 1


@final
class BlobByteReaderStub:
    """replay blob bytes readerのtyped test doubleを提供する.

    Attributes:
        _payload (bytes): read_bytesが成功時に返すsynthetic blob bytes.
        _unavailable_cause (Exception | None): read時にunavailableとして変換する任意の原因例外.
        read_blob_ids (list[int]): read_bytesへ渡されたblob識別子.
    """

    def __init__(
        self,
        *,
        payload: bytes = b"synthetic-stored-replay",
        unavailable_cause: Exception | None = None,
    ) -> None:
        """成功payloadまたはunavailable原因を持つreader stubを初期化する.

        Args:
            payload (bytes): 原因例外がない場合に返すstored replay bytes.
            unavailable_cause (Exception | None): 指定時にBlobBytesUnavailableErrorのcauseに
                する例外.
        """
        self._payload: bytes = payload
        self._unavailable_cause: Exception | None = unavailable_cause
        self.read_blob_ids: list[int] = []

    async def read_bytes(self, blob_id: int) -> bytes:
        """Blob IDを記録してpayloadを返すかunavailable errorを送出する.

        Args:
            blob_id (int): 読み込むstored blobの識別子.

        Returns:
            bytes: 原因例外がない場合のsynthetic stored replay bytes.

        Raises:
            BlobBytesUnavailableError: unavailable_causeが指定されている場合.
        """
        self.read_blob_ids.append(blob_id)
        if self._unavailable_cause is not None:
            raise BlobBytesUnavailableError(blob_id) from self._unavailable_cause
        return self._payload


@final
class RecordingReplayDownloadBodyAssembler:
    """replay download body assemblerのtyped recording test doubleを提供する.

    Attributes:
        _assembler (ReplayDownloadBodyAssembler): buildを委譲するproduction assembler.
        inputs (list[ReplayDownloadBodyBuildInput]): buildへ渡されたinputの記録.
    """

    def __init__(self) -> None:
        """Production assemblerと空のbuild input記録を初期化する."""
        self._assembler = ReplayDownloadBodyAssembler()
        self.inputs: list[ReplayDownloadBodyBuildInput] = []

    def build(
        self,
        input_data: ReplayDownloadBodyBuildInput,
    ) -> ReplayDownloadBodyBuildResult:
        """Build inputを記録してproduction assemblerへ委譲する.

        Args:
            input_data (ReplayDownloadBodyBuildInput): replay response bodyを構築するinput.

        Returns:
            ReplayDownloadBodyBuildResult: production assemblerが返すbody構築結果.
        """
        self.inputs.append(input_data)
        return self._assembler.build(input_data)


@dataclass(slots=True, frozen=True)
class ReplayDownloadQueryHarness:
    """replay download query testのcollaboratorをまとめる.

    Attributes:
        query (ReplayDownloadQuery): test対象のquery use-case.
        repository (ReplayDownloadQueryRepositoryStub): candidateを返すrepository stub.
        blob_reader (BlobByteReaderStub): stored blob bytesを返すreader stub.
        body_assembler (RecordingReplayDownloadBodyAssembler): build inputを記録するassembler stub.
    """

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
    """Replay download queryのtest harnessを構築する.

    Args:
        candidate (ReplayDownloadCandidate): repository stubが返すcandidate.
        blob_payload (bytes): blob readerが成功時に返すstored replay bytes.
        blob_error (Exception | None): blob readerがunavailableとして変換する任意の原因例外.
        body_strategy (ReplayDownloadBodyStrategy): queryがbody assemblerへ渡すstrategy.

    Returns:
        ReplayDownloadQueryHarness: queryと観測用collaboratorを保持するharness.
    """
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
    """Authenticated replay download query inputを構築する.

    Args:
        score_id (int): 取得対象scoreの識別子.
        ruleset (Ruleset): scoreを検索するruleset.

    Returns:
        ReplayDownloadQueryInput: 固定authenticated user IDを含むquery input.
    """
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
    """利用可能なreplay candidateを構築する.

    Args:
        score_id (int): replayを所有するscoreの識別子.
        score_owner_user_id (int): score ownerの識別子.
        blob_id (int): stored replay blobの識別子.
        payload (bytes): checksumと既定byte sizeの算出元にするsynthetic bytes.
        checksum (str | None): candidateへ明示設定するchecksum.
            指定しない場合はpayloadのSHA-256を使う.
        byte_size (int | None): candidateへ明示設定するbyte size. 指定しない場合はpayload長を使う.

    Returns:
        ReplayDownloadAvailableReplayCandidate: checksumとbyte sizeを持つ利用可能なreplay
            candidate.
    """
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
    """Available replay専用collaboratorが未呼び出しであることを検証する.

    Args:
        harness (ReplayDownloadQueryHarness): 呼び出し記録を確認するquery test harness.

    Returns:
        None: blob read,body build,view/activity mutationがないことを検証して完了する.
    """
    assert harness.blob_reader.read_blob_ids == []
    assert harness.body_assembler.inputs == []
    assert harness.repository.replay_view_update_count == 0
    assert harness.repository.latest_activity_update_count == 0


def _assert_failure_result_has_no_client_visible_details(
    result: ReplayDownloadQueryResult,
    *private_values: object,
) -> None:
    """Failure resultがclient-visibleなprivate detailを含まないことを検証する.

    Args:
        result (ReplayDownloadQueryResult): failure branchとして検証するquery結果.
        private_values (object): reprから除外されるべき追加の非公開値.

    Returns:
        None: 非成功状態,response body不在,private detail非露出を検証して完了する.
    """
    assert result.is_success is False
    assert result.response_body is None
    result_repr = repr(result)
    assert "ReplayDownloadResponseBody" not in result_repr
    assert "payload" not in result_repr
    for private_value in (*_PRIVATE_SENTINELS, *private_values):
        assert str(private_value) not in result_repr
        assert repr(private_value) not in result_repr
