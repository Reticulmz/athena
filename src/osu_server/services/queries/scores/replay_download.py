"""Replay download の response branch を分類する query service を提供する."""

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
    """Replay download query use-case の認証済み入力を表す.

    Attributes:
        authenticated_user_id (int): 認証済み viewer の User ID.
        score_id (int): 解析済み replay score の ID.
        ruleset (Ruleset): 解析済み Stable ruleset scope.

    Notes:
        Transport query string, credential value, SQLAlchemy object, storage backend detail は
        含めない. 認証と値の解析は呼び出し元で完了している前提とする.
    """

    authenticated_user_id: int
    score_id: int
    ruleset: Ruleset


@dataclass(slots=True, frozen=True)
class ReplayDownloadAccountingMetadata:
    """Replay download accounting に必要な内部 identity を表す.

    Attributes:
        score_id (int): accounting 対象になる score ID.
        score_owner_user_id (int): self-view 判定に使う score owner の User ID.

    Notes:
        Transport query value, credential value, replay payload, storage backend detail, local
        artifact path は保持しない. Stable response へ serialize しない.
    """

    score_id: int
    score_owner_user_id: int


@dataclass(slots=True, frozen=True)
class ReplayDownloadQueryResult:
    """Replay download query use-case の client-visible branch 結果を表す.

    Attributes:
        branch (ReplayDownloadBranch): client-visible response branch.
        response_body (ReplayDownloadResponseBody | None): SUCCESS branch で返す response body.
        accounting_metadata (ReplayDownloadAccountingMetadata | None): SUCCESS branch の
            accounting に使う内部 identity.

    Notes:
        SUCCESS 以外の branch は body と accounting metadata を保持しない. Storage backend
        detail, credential value, raw query value, local artifact path は保持しない.
    """

    branch: ReplayDownloadBranch
    response_body: ReplayDownloadResponseBody | None = None
    accounting_metadata: ReplayDownloadAccountingMetadata | None = field(
        default=None,
        repr=False,
    )

    def __post_init__(self) -> None:
        """Branch と任意 payload の組み合わせが整合することを検証する.

        Returns:
            None: result の不変条件を検証したことを表す.

        Raises:
            ValueError: SUCCESS branch に body または accounting metadata がない場合.
            ValueError: SUCCESS 以外の branch に body または accounting metadata がある場合.
        """
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
        """SUCCESS branch に body と accounting metadata があるかを返す.

        Returns:
            bool: query result が成功 payload を完全に持つ場合は True.
        """
        return (
            self.branch is ReplayDownloadBranch.SUCCESS
            and self.response_body is not None
            and self.accounting_metadata is not None
        )


class _ReplayDownloadBodyBuilder(Protocol):
    """Stored replay blob から response body result を作る Protocol."""

    def build(
        self,
        input_data: ReplayDownloadBodyBuildInput,
    ) -> ReplayDownloadBodyBuildResult:
        """Strategy に従って replay response body result を作る.

        Args:
            input_data (ReplayDownloadBodyBuildInput): strategy と validation 済み blob を含む入力.

        Returns:
            ReplayDownloadBodyBuildResult: SUCCESS または body strategy blocked の結果.
        """
        ...


@dataclass(slots=True, frozen=True)
class ReplayDownloadBodyBuildInput:
    """Replay download response body を組み立てる入力を表す.

    Attributes:
        strategy (ReplayDownloadBodyStrategy): local validation で選ばれた body strategy.
        stored_blob (ReplayDownloadStoredBlobObject): replay attachment から読んだ stored blob.

    Notes:
        Stored blob bytes は validation 済みの値だけを渡す. Transport, SQLAlchemy, storage
        backend detail, credential value は含めない.
    """

    strategy: ReplayDownloadBodyStrategy
    stored_blob: ReplayDownloadStoredBlobObject


@dataclass(slots=True, frozen=True)
class ReplayDownloadBodyBuildResult:
    """Replay download response body build の結果を表す.

    Attributes:
        branch (ReplayDownloadBranch): response body build の observable branch.
        response_body (ReplayDownloadResponseBody | None): SUCCESS branch で client-visible に
            返す body.

    Notes:
        SUCCESS 以外の branch は response body を保持しない. Payload の内容は repr に出さない.
    """

    branch: ReplayDownloadBranch
    response_body: ReplayDownloadResponseBody | None = None

    def __post_init__(self) -> None:
        """Branch と response body の有無が整合することを検証する.

        Returns:
            None: result の不変条件を検証したことを表す.

        Raises:
            ValueError: SUCCESS branch に response body がない場合.
            ValueError: SUCCESS 以外の branch に response body がある場合.
        """
        if self.branch is ReplayDownloadBranch.SUCCESS and self.response_body is None:
            msg = "success replay download body result requires response body"
            raise ValueError(msg)
        if self.branch is not ReplayDownloadBranch.SUCCESS and self.response_body is not None:
            msg = "non-success replay download body result must not include response body"
            raise ValueError(msg)

    @property
    def is_success(self) -> bool:
        """SUCCESS branch に response body があるかを返す.

        Returns:
            bool: body build result が成功 payload を持つ場合は True.
        """
        return self.branch is ReplayDownloadBranch.SUCCESS and self.response_body is not None


@final
class ReplayDownloadBodyAssembler:
    """Stored replay bytes から client-visible response body を作る.

    Notes:
        BLOCKED strategy と未確定の ASSEMBLE_DOWNLOAD_BODY strategy は bytes を生成しない.
        Transport, SQLAlchemy, storage backend implementation, Valkey, taskiq, composition には
        依存しない.
    """

    def build(
        self,
        input_data: ReplayDownloadBodyBuildInput,
    ) -> ReplayDownloadBodyBuildResult:
        """Replay download response body build result を返す.

        Args:
            input_data (ReplayDownloadBodyBuildInput): strategy と validation 済み stored blob.

        Returns:
            ReplayDownloadBodyBuildResult: SUCCESS または body strategy blocked の結果.

        Notes:
            DIRECT_BLOB_BYTES は stored blob bytes をそのまま response body として返す.
            ASSEMBLE_DOWNLOAD_BODY は local validation decision が未確定のため blocked とする.
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
    """Replay download candidate から response branch を読み取り専用で分類する.

    Attributes:
        _repository (ReplayDownloadQueryRepository): score と replay candidate を読む repository.
        _blob_reader (BlobByteReader): available replay の blob bytes を読む reader.
        _body_assembler (_ReplayDownloadBodyBuilder): validation 済み bytes から response body を
            作る builder.
        _body_strategy (ReplayDownloadBodyStrategy): response body の構築方針.

    Notes:
        replay view count, latest activity, self-view, duplicate-view などの mutation dependency
        を持たない. Transport, SQLAlchemy, storage backend implementation, Valkey, taskiq,
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
        """Query workflow の collaborators と body strategy を設定する.

        Args:
            repository (ReplayDownloadQueryRepository): replay download candidate を読む
                read-only repository.
            blob_reader (BlobByteReader): available replay branch だけで使う blob bytes reader.
            body_assembler (_ReplayDownloadBodyBuilder): stored blob から response body result を
                作る builder.
            body_strategy (ReplayDownloadBodyStrategy): local validation で選ばれた body strategy.

        Notes:
            既定 strategy は BLOCKED とし, local validation decision がない状態で success body
            を推測しない. Mutation collaborator は受け取らない.
        """
        self._repository: ReplayDownloadQueryRepository = repository
        self._blob_reader: BlobByteReader = blob_reader
        self._body_assembler: _ReplayDownloadBodyBuilder = body_assembler
        self._body_strategy: ReplayDownloadBodyStrategy = body_strategy

    async def execute(
        self,
        input_data: ReplayDownloadQueryInput,
    ) -> ReplayDownloadQueryResult:
        """Replay download query input から client-visible branch result を返す.

        Args:
            input_data (ReplayDownloadQueryInput): 認証と値の解析が完了した query input.

        Returns:
            ReplayDownloadQueryResult: SUCCESS では response body を含む結果. それ以外は
                branch だけを含む結果.

        Notes:
            Blob bytes は available replay candidate の場合だけ読む. BlobBytesUnavailableError
            は STORAGE_MISSING branch に変換する. repository または body assembler の想定外の
            例外は伝播する.
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
        """Repository candidate を対応する replay download branch へ変換する.

        Args:
            candidate (ReplayDownloadCandidate): repository が返した score と replay の候補.

        Returns:
            ReplayDownloadQueryResult: hidden, missing replay, または available replay の結果.
        """
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
        """Available replay candidate の blob を検証して response result を作る.

        Args:
            candidate (ReplayDownloadAvailableReplayCandidate): blob ID, size, checksum を持つ
                available replay candidate.

        Returns:
            ReplayDownloadQueryResult: blob が利用不可または不整合なら STORAGE_MISSING. 検証済み
                blob は body strategy の結果を返す.

        Notes:
            BlobBytesUnavailableError は STORAGE_MISSING に変換する. body assembler の想定外の
            例外は伝播する.
        """
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
    """未確定または明示的に blocked な body strategy の結果を作る.

    Returns:
        ReplayDownloadBodyBuildResult: response body を持たない BODY_STRATEGY_BLOCKED 結果.
    """
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
