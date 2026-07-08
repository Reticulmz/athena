"""Replay download query service component を提供する."""

from __future__ import annotations

from dataclasses import dataclass, field
from hashlib import sha256
from typing import TYPE_CHECKING, Protocol, final

from osu_server.domain.compatibility.stable import (
    ReplayDownloadBodyStrategy,
    ReplayDownloadBranch,
    ReplayDownloadResponseBody,
    ReplayDownloadStoredBlobObject,
)
from osu_server.repositories.interfaces.queries.replay_download import (
    ReplayDownloadAvailableReplayCandidate,
    ReplayDownloadCandidate,
    ReplayDownloadCandidateQuery,
    ReplayDownloadHiddenScoreCandidate,
    ReplayDownloadMissingReplayCandidate,
    ReplayDownloadQueryRepository,
    ReplayDownloadScoreNotFoundCandidate,
)
from osu_server.services.queries.storage import BlobByteReader, BlobBytesUnavailableError

if TYPE_CHECKING:
    from osu_server.domain.scores.score import Ruleset


@dataclass(slots=True, frozen=True)
class ReplayDownloadQueryInput:
    """Replay download query use-case の入力を表す.

    引数:
        authenticated_user_id: Authentication 済み user id.
        score_id: Parse 済み score id.
        ruleset: Parse 済み Stable ruleset scope.

    戻り値:
        Dataclass のため戻り値はない.

    例外:
        なし.

    制約:
        Transport query string, credential value, SQLAlchemy object, storage backend
        detail は含めない. Auth と parse は呼び出し元で完了している前提とする.
    """

    authenticated_user_id: int
    score_id: int
    ruleset: Ruleset


@dataclass(slots=True, frozen=True)
class ReplayDownloadAccountingMetadata:
    """Replay download accounting に必要な内部 identity を表す.

    引数:
        score_id: Accounting 対象になる score identifier.
        score_owner_user_id: Self-view 判定に使う score owner user id.

    戻り値:
        Dataclass のため戻り値はない.

    例外:
        なし.

    制約:
        Transport query value, credential value, replay payload, storage backend detail,
        local artifact path は保持しない. Stable response へ serialize しない.
    """

    score_id: int
    score_owner_user_id: int


@dataclass(slots=True, frozen=True)
class ReplayDownloadQueryResult:
    """Replay download query use-case の branch result を表す.

    引数:
        branch: Client-visible response branch.
        response_body: Success branch で返す response body.
        accounting_metadata: Success branch の accounting に使う内部 identity.

    戻り値:
        Dataclass のため戻り値はない.

    例外:
        ValueError: Success branch と response body / metadata の有無が矛盾する場合.

    制約:
        Success 以外の branch は body と accounting metadata を保持しない.
        Storage backend detail, credential value, raw query value, local artifact path
        は保持しない.
    """

    branch: ReplayDownloadBranch
    response_body: ReplayDownloadResponseBody | None = None
    accounting_metadata: ReplayDownloadAccountingMetadata | None = field(
        default=None,
        repr=False,
    )

    def __post_init__(self) -> None:
        if self.branch is ReplayDownloadBranch.SUCCESS and self.response_body is None:
            msg = "success replay download query result requires response body"
            raise ValueError(msg)
        if self.branch is ReplayDownloadBranch.SUCCESS and self.accounting_metadata is None:
            msg = "success replay download query result requires accounting metadata"
            raise ValueError(msg)
        if self.branch is not ReplayDownloadBranch.SUCCESS and self.response_body is not None:
            msg = "non-success replay download query result must not include response body"
            raise ValueError(msg)
        if (
            self.branch is not ReplayDownloadBranch.SUCCESS
            and self.accounting_metadata is not None
        ):
            msg = "non-success replay download query result must not include accounting metadata"
            raise ValueError(msg)

    @property
    def is_success(self) -> bool:
        """Success branch かつ response body があるかを返す.

        引数:
            なし.

        戻り値:
            Success branch で response body がある場合は True.

        例外:
            なし.

        制約:
            HTTP status や transport response には依存しない.
        """

        return (
            self.branch is ReplayDownloadBranch.SUCCESS
            and self.response_body is not None
            and self.accounting_metadata is not None
        )


class _ReplayDownloadBodyBuilder(Protocol):
    def build(
        self,
        input_data: ReplayDownloadBodyBuildInput,
    ) -> ReplayDownloadBodyBuildResult: ...


@dataclass(slots=True, frozen=True)
class ReplayDownloadBodyBuildInput:
    """Replay download response body build の入力を表す.

    引数:
        strategy: Local validation で選ばれた response body strategy.
        stored_blob: Replay attachment から読んだ stored blob object.

    戻り値:
        Dataclass のため戻り値はない.

    例外:
        なし.

    制約:
        Stored blob bytes は validation 済みの値だけを渡す. Transport,
        SQLAlchemy, storage backend detail, credential value は含めない.
    """

    strategy: ReplayDownloadBodyStrategy
    stored_blob: ReplayDownloadStoredBlobObject


@dataclass(slots=True, frozen=True)
class ReplayDownloadBodyBuildResult:
    """Replay download response body build の結果を表す.

    引数:
        branch: Response body build の observable branch.
        response_body: Success branch で client-visible に返す body.

    戻り値:
        Dataclass のため戻り値はない.

    例外:
        ValueError: Success branch と response body の有無が矛盾する場合.

    制約:
        Success 以外の branch は response body を保持しない. Payload の内容は
        repr に出さない.
    """

    branch: ReplayDownloadBranch
    response_body: ReplayDownloadResponseBody | None = None

    def __post_init__(self) -> None:
        if self.branch is ReplayDownloadBranch.SUCCESS and self.response_body is None:
            msg = "success replay download body result requires response body"
            raise ValueError(msg)
        if self.branch is not ReplayDownloadBranch.SUCCESS and self.response_body is not None:
            msg = "non-success replay download body result must not include response body"
            raise ValueError(msg)

    @property
    def is_success(self) -> bool:
        """Success branch かつ response body があるかを返す.

        引数:
            なし.

        戻り値:
            Success branch で response body がある場合は True.

        例外:
            なし.

        制約:
            HTTP status は扱わず, query service result の branch だけを判定する.
        """

        return self.branch is ReplayDownloadBranch.SUCCESS and self.response_body is not None


@final
class ReplayDownloadBodyAssembler:
    """Stored replay bytes から client-visible response body を作る.

    引数:
        なし.

    戻り値:
        Class のため戻り値はない.

    例外:
        なし.

    制約:
        Blocked strategy と未確定 assemble strategy は bytes を生成しない.
        Transport, SQLAlchemy, storage backend implementation, Valkey, taskiq,
        composition には依存しない.
    """

    def build(
        self,
        input_data: ReplayDownloadBodyBuildInput,
    ) -> ReplayDownloadBodyBuildResult:
        """Replay download response body build result を返す.

        引数:
            input_data: Strategy と stored blob object.

        戻り値:
            Success または body strategy blocked の build result.

        例外:
            なし.

        制約:
            `direct_blob_bytes` では stored blob bytes をそのまま response body
            として返す. `assemble_download_body` は local validation decision が
            まだ存在しないため blocked として扱う.
        """

        match input_data.strategy:
            case ReplayDownloadBodyStrategy.BLOCKED:
                return _blocked_result()
            case ReplayDownloadBodyStrategy.DIRECT_BLOB_BYTES:
                return ReplayDownloadBodyBuildResult(
                    branch=ReplayDownloadBranch.SUCCESS,
                    response_body=ReplayDownloadResponseBody(
                        payload=input_data.stored_blob.payload,
                    ),
                )
            case ReplayDownloadBodyStrategy.ASSEMBLE_DOWNLOAD_BODY:
                # Local validation decision が入るまでは format 変換を推測しない.
                return _blocked_result()


@final
class ReplayDownloadQuery:
    """Replay download candidate から response branch を分類する.

    引数:
        なし.

    戻り値:
        Class のため戻り値はない.

    例外:
        なし.

    制約:
        Read-only query workflow として動作し, replay view count, latest activity,
        self-view, duplicate-view などの mutation dependency を持たない.
        Transport, SQLAlchemy, storage backend implementation, Valkey, taskiq,
        composition には依存しない.
    """

    def __init__(
        self,
        *,
        repository: ReplayDownloadQueryRepository,
        blob_reader: BlobByteReader,
        body_assembler: _ReplayDownloadBodyBuilder,
        body_strategy: ReplayDownloadBodyStrategy = ReplayDownloadBodyStrategy.BLOCKED,
    ) -> None:
        """Query workflow collaborator と body strategy を受け取る.

        引数:
            repository: Replay download candidate を読む read-only repository.
            blob_reader: Available replay branch だけで使う blob bytes reader.
            body_assembler: Stored blob object から response body result を作る builder.
            body_strategy: Local validation で選ばれた body strategy.

        戻り値:
            なし.

        例外:
            なし.

        制約:
            Default strategy は blocked とし, local validation decision がない状態で
            success body を推測しない. Mutation collaborator は受け取らない.
        """

        self._repository: ReplayDownloadQueryRepository = repository
        self._blob_reader: BlobByteReader = blob_reader
        self._body_assembler: _ReplayDownloadBodyBuilder = body_assembler
        self._body_strategy: ReplayDownloadBodyStrategy = body_strategy

    async def execute(
        self,
        input_data: ReplayDownloadQueryInput,
    ) -> ReplayDownloadQueryResult:
        """Replay download query input から branch result を返す.

        引数:
            input_data: Authentication と parse が完了した query input.

        戻り値:
            Success の場合は response body を含む result. それ以外は branch のみの
            result.

        例外:
            Repository の想定外永続化例外や body assembler の想定外例外は伝播する.

        制約:
            Blob bytes は available replay candidate の場合だけ読む.
            BlobBytesUnavailableError は storage_missing branch に変換し, storage
            backend detail は result に含めない.
        """

        candidate = await self._repository.get_candidate(
            ReplayDownloadCandidateQuery(
                score_id=input_data.score_id,
                ruleset=input_data.ruleset,
            )
        )
        return await self._result_from_candidate(candidate)

    async def _result_from_candidate(
        self,
        candidate: ReplayDownloadCandidate,
    ) -> ReplayDownloadQueryResult:
        if isinstance(
            candidate,
            ReplayDownloadScoreNotFoundCandidate | ReplayDownloadHiddenScoreCandidate,
        ):
            return ReplayDownloadQueryResult(branch=ReplayDownloadBranch.HIDDEN_SCORE)

        if isinstance(candidate, ReplayDownloadMissingReplayCandidate):
            return ReplayDownloadQueryResult(
                branch=ReplayDownloadBranch.MISSING_REPLAY_PROVISIONAL,
            )

        return await self._result_from_available_replay(candidate)

    async def _result_from_available_replay(
        self,
        candidate: ReplayDownloadAvailableReplayCandidate,
    ) -> ReplayDownloadQueryResult:
        try:
            blob_bytes = await self._blob_reader.read_bytes(candidate.blob_id)
        except BlobBytesUnavailableError:
            return ReplayDownloadQueryResult(branch=ReplayDownloadBranch.STORAGE_MISSING)

        if len(blob_bytes) != candidate.byte_size or sha256(blob_bytes).hexdigest() != (
            candidate.checksum
        ):
            return ReplayDownloadQueryResult(branch=ReplayDownloadBranch.STORAGE_MISSING)

        build_result = self._body_assembler.build(
            ReplayDownloadBodyBuildInput(
                strategy=self._body_strategy,
                stored_blob=ReplayDownloadStoredBlobObject(payload=blob_bytes),
            )
        )
        accounting_metadata = (
            ReplayDownloadAccountingMetadata(
                score_id=candidate.score_id,
                score_owner_user_id=candidate.score_owner_user_id,
            )
            if build_result.branch is ReplayDownloadBranch.SUCCESS
            else None
        )
        return ReplayDownloadQueryResult(
            branch=build_result.branch,
            response_body=build_result.response_body,
            accounting_metadata=accounting_metadata,
        )


def _blocked_result() -> ReplayDownloadBodyBuildResult:
    return ReplayDownloadBodyBuildResult(
        branch=ReplayDownloadBranch.BODY_STRATEGY_BLOCKED,
        response_body=None,
    )


__all__ = [
    "ReplayDownloadAccountingMetadata",
    "ReplayDownloadBodyAssembler",
    "ReplayDownloadBodyBuildInput",
    "ReplayDownloadBodyBuildResult",
    "ReplayDownloadQuery",
    "ReplayDownloadQueryInput",
    "ReplayDownloadQueryResult",
]
