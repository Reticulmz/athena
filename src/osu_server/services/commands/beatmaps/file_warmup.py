"""stable client の beatmap file warmup request を正規化して解決する command boundary を提供する.

この module は authentication 済み request の beatmap identity を検証し、既存 resolver に file
availability を問い合わせる. resolver
の例外は呼出側へ返さず、診断可能で機密情報を含まない結果へ
変換する.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from enum import Enum
from typing import Protocol, cast

import structlog

from osu_server.domain.beatmaps import (
    BeatmapFileState,
    BeatmapResolveOptions,
    BeatmapResolveResult,
)

logger = cast("structlog.stdlib.BoundLogger", structlog.get_logger(__name__))

_NORMALIZED_MD5_RE = re.compile(r"^[0-9a-f]{32}$")
_WARMUP_RESOLVE_OPTIONS = BeatmapResolveOptions(
    require_osu_file=True,
    wait_timeout_seconds=0.0,
)


class BeatmapFileWarmupEntrance(Enum):
    """beatmap file warmup を要求できる stable workflow の入口を表す.

    Attributes:
        STABLE_GETSCORES (BeatmapFileWarmupEntrance): stable getscores request からの warmup.
        STABLE_STATUS_CHANGE (BeatmapFileWarmupEntrance): stable status change からの warmup.
        STABLE_SCORE_SUBMIT_FALLBACK (BeatmapFileWarmupEntrance):
            stable score submit fallback からの warmup.
    """

    STABLE_GETSCORES = "stable_getscores"
    STABLE_STATUS_CHANGE = "stable_status_change"
    STABLE_SCORE_SUBMIT_FALLBACK = "stable_score_submit_fallback"


class BeatmapFileWarmupOutcome(Enum):
    """operator と test が確認する beatmap file warmup の結果を表す.

    Attributes:
        REQUESTED (BeatmapFileWarmupOutcome): metadata はあり、file fetch を要求した状態.
        ALREADY_AVAILABLE (BeatmapFileWarmupOutcome): 検証済み file がすでに利用可能な状態.
        METADATA_PENDING (BeatmapFileWarmupOutcome): beatmap metadata の取得完了を待つ状態.
        SKIPPED_NO_IDENTITY (BeatmapFileWarmupOutcome):
            authenticated user または beatmap identity がないため省略した状態.
        SKIPPED_MALFORMED_IDENTITY (BeatmapFileWarmupOutcome):
            beatmap identity が不正なため省略した状態.
        FAILED (BeatmapFileWarmupOutcome): resolver failure を安全な診断結果へ変換した状態.
    """

    REQUESTED = "requested"
    ALREADY_AVAILABLE = "already_available"
    METADATA_PENDING = "metadata_pending"
    SKIPPED_NO_IDENTITY = "skipped_no_identity"
    SKIPPED_MALFORMED_IDENTITY = "skipped_malformed_identity"
    FAILED = "failed"


@dataclass(slots=True, frozen=True)
class BeatmapFileWarmupRequest:
    """beatmap file の準備を要求する authentication 済み stable activity を表す.

    Attributes:
        entrance (BeatmapFileWarmupEntrance): warmup を要求した stable workflow.
        user_id (int): authentication 済み user の識別子.
        beatmap_id (int | None):
            優先して使用する beatmap ID. 指定しない場合はchecksumを評価する.
        checksum_md5 (str | None): beatmap ID がない場合に使用する MD5 checksum.
    """

    entrance: BeatmapFileWarmupEntrance
    user_id: int
    beatmap_id: int | None = None
    checksum_md5: str | None = None


@dataclass(slots=True, frozen=True)
class BeatmapFileWarmupResult:
    """diagnostic と test が利用する beatmap file warmup の結果を表す.

    Attributes:
        outcome (BeatmapFileWarmupOutcome): warmup の終端状態.
        entrance (BeatmapFileWarmupEntrance): request を発行した stable workflow.
        user_id (int): request を発行した authentication 済み user の識別子.
        beatmap_id (int | None): 正規化後に使用した beatmap ID.
        checksum_md5 (str | None): 正規化後に使用した lowercase MD5 checksum.
        reason (str | None): outcome の診断用 reason. reason が不要な場合はNone.
    """

    outcome: BeatmapFileWarmupOutcome
    entrance: BeatmapFileWarmupEntrance
    user_id: int
    beatmap_id: int | None
    checksum_md5: str | None
    reason: str | None


class BeatmapFileWarmupResolver(Protocol):
    """既存の beatmap fetch enqueue behavior を所有する resolver port を定義する."""

    async def resolve_by_beatmap_id(
        self,
        beatmap_id: int,
        options: BeatmapResolveOptions | None = None,
    ) -> BeatmapResolveResult:
        """Beatmap ID から file availability を解決する.

        Args:
            beatmap_id (int): 解決する正の beatmap ID.
            options (BeatmapResolveOptions | None):
                file requirement と待機時間を指定する option. 指定しない場合は resolver
                の既定を使う.

        Returns:
            BeatmapResolveResult: metadata、file state、enqueue result を含む解決結果.
        """
        ...

    async def resolve_by_checksum(
        self,
        checksum_md5: str,
        options: BeatmapResolveOptions | None = None,
    ) -> BeatmapResolveResult:
        """MD5 checksum から file availability を解決する.

        Args:
            checksum_md5 (str): 解決する lowercase または case-insensitive の MD5 checksum.
            options (BeatmapResolveOptions | None):
                file requirement と待機時間を指定する option. 指定しない場合は resolver
                の既定を使う.

        Returns:
            BeatmapResolveResult: metadata、file state、enqueue result を含む解決結果.
        """
        ...


@dataclass(slots=True, frozen=True)
class _NormalizedWarmupIdentity:
    """resolver に渡せるよう正規化済みの beatmap identity を表す.

    Attributes:
        beatmap_id (int | None): 優先された正の beatmap ID.
        checksum_md5 (str | None): beatmap ID がない場合に使用する lowercase MD5 checksum.
    """

    beatmap_id: int | None
    checksum_md5: str | None


class _IdentityPolicyOutcome(Enum):
    """warmup request identity の policy 評価結果を表す内部 enum.

    Attributes:
        VALID (_IdentityPolicyOutcome): resolver に渡せる identity がある状態.
        NO_IDENTITY (_IdentityPolicyOutcome):
            user または beatmap identity が指定されていない状態.
        MALFORMED (_IdentityPolicyOutcome): 指定された beatmap ID または checksum が不正な状態.
    """

    VALID = "valid"
    NO_IDENTITY = "no_identity"
    MALFORMED = "malformed"


@dataclass(slots=True, frozen=True)
class _IdentityPolicyResult:
    """identity policy の outcome と正規化済み identity をまとめる内部値を表す.

    Attributes:
        outcome (_IdentityPolicyOutcome): identity の有効性を示す policy outcome.
        identity (_NormalizedWarmupIdentity | None):
            VALID の場合に resolver へ渡す identity. それ以外はNone.
    """

    outcome: _IdentityPolicyOutcome
    identity: _NormalizedWarmupIdentity | None


class RequestBeatmapFileWarmupUseCase:
    """authentication 済み stable warmup request を正規化して resolver へ渡す use-case.

    正の beatmap ID を checksum より優先し、checksum は lowercase MD5 へ正規化する. resolver の
    exception は failure result に変換するため、stable workflow は retry 可能な診断を得られる.

    Attributes:
        _resolver (BeatmapFileWarmupResolver):
            beatmap identity から metadata と file state を解決する port.
    """

    def __init__(self, resolver: BeatmapFileWarmupResolver) -> None:
        """Warmup request を解決する resolver を設定する.

        Args:
            resolver (BeatmapFileWarmupResolver):
                beatmap ID または checksum による既存解決 workflow を所有する port.

        """
        self._resolver: BeatmapFileWarmupResolver
        self._resolver = resolver

    async def execute(
        self,
        request: BeatmapFileWarmupRequest,
    ) -> BeatmapFileWarmupResult:
        """Request の identity を検証し、file warmup の outcome を返す.

        Args:
            request (BeatmapFileWarmupRequest):
                authentication 済み user と beatmap identity を含む warmup request.

        Returns:
            BeatmapFileWarmupResult: identity policy、resolver result、または resolver failure
            を表す安全な
            outcome.

        Notes:
            user ID が正でない場合、identity がない場合、不正な identity は resolver
            を呼び出さない. resolver exception
            は例外本文を log field に含めずFAILED resultへ変換する.
        """
        if request.user_id <= 0:
            return self._skipped_result(
                request,
                BeatmapFileWarmupOutcome.SKIPPED_NO_IDENTITY,
                reason="no_authenticated_identity",
            )

        policy_result = _normalize_identity(request)
        if policy_result.outcome is _IdentityPolicyOutcome.NO_IDENTITY:
            return self._skipped_result(
                request,
                BeatmapFileWarmupOutcome.SKIPPED_NO_IDENTITY,
                reason="no_beatmap_identity",
            )

        if policy_result.outcome is _IdentityPolicyOutcome.MALFORMED:
            return self._skipped_result(
                request,
                BeatmapFileWarmupOutcome.SKIPPED_MALFORMED_IDENTITY,
                reason="malformed_beatmap_identity",
            )

        if policy_result.identity is None:
            return self._skipped_result(
                request,
                BeatmapFileWarmupOutcome.SKIPPED_NO_IDENTITY,
                reason="no_beatmap_identity",
            )

        identity = policy_result.identity
        try:
            resolve_result = await self._resolve_identity(identity)
        except Exception as exc:
            return self._failed_result(
                request,
                identity,
                exception_type=type(exc).__name__,
            )

        result = BeatmapFileWarmupResult(
            outcome=_outcome_from_resolve_result(resolve_result),
            entrance=request.entrance,
            user_id=request.user_id,
            beatmap_id=identity.beatmap_id,
            checksum_md5=identity.checksum_md5,
            reason=_reason_from_resolve_result(resolve_result),
        )
        _log_result(result)
        return result

    async def _resolve_identity(
        self,
        identity: _NormalizedWarmupIdentity,
    ) -> BeatmapResolveResult:
        """正規化済み identity に対応する resolver method を呼び出す.

        Args:
            identity (_NormalizedWarmupIdentity):
                正の beatmap ID または lowercase checksum を持つ identity.

        Returns:
            BeatmapResolveResult: file requirement を指定して resolver が返した解決結果.

        Raises:
            RuntimeError: valid identity に beatmap ID と checksum のいずれも含まれない場合.
        """
        if identity.beatmap_id is not None:
            return await self._resolver.resolve_by_beatmap_id(
                identity.beatmap_id,
                _WARMUP_RESOLVE_OPTIONS,
            )
        if identity.checksum_md5 is None:
            msg = "valid warmup identity must include beatmap id or checksum"
            raise RuntimeError(msg)
        return await self._resolver.resolve_by_checksum(
            identity.checksum_md5,
            _WARMUP_RESOLVE_OPTIONS,
        )

    def _failed_result(
        self,
        request: BeatmapFileWarmupRequest,
        identity: _NormalizedWarmupIdentity,
        *,
        exception_type: str,
    ) -> BeatmapFileWarmupResult:
        """Resolver exception を安全な failure result として記録する.

        Args:
            request (BeatmapFileWarmupRequest): failure の入口と user を示す元 request.
            identity (_NormalizedWarmupIdentity): resolver に渡そうとした正規化済み identity.
            exception_type (str): exception 本文を出さずに診断へ記録する exception class 名.

        Returns:
            BeatmapFileWarmupResult: `FAILED` と `"resolver_failure"` を持つ診断結果.
        """
        result = BeatmapFileWarmupResult(
            outcome=BeatmapFileWarmupOutcome.FAILED,
            entrance=request.entrance,
            user_id=request.user_id,
            beatmap_id=identity.beatmap_id,
            checksum_md5=identity.checksum_md5,
            reason="resolver_failure",
        )
        _log_result(result, exception_type=exception_type)
        return result

    def _skipped_result(
        self,
        request: BeatmapFileWarmupRequest,
        outcome: BeatmapFileWarmupOutcome,
        *,
        reason: str,
    ) -> BeatmapFileWarmupResult:
        """Identity policy により resolver を省略した結果を作成する.

        Args:
            request (BeatmapFileWarmupRequest): 入口と user を示す元 request.
            outcome (BeatmapFileWarmupOutcome):
                no identity または malformed identity の skip outcome.
            reason (str): operator と test が区別する skip reason.

        Returns:
            BeatmapFileWarmupResult: normalized beatmap identity を含めない skip result.
        """
        result = BeatmapFileWarmupResult(
            outcome=outcome,
            entrance=request.entrance,
            user_id=request.user_id,
            beatmap_id=None,
            checksum_md5=None,
            reason=reason,
        )
        _log_result(result)
        return result


def _normalize_identity(request: BeatmapFileWarmupRequest) -> _IdentityPolicyResult:
    """Request の beatmap identity を検証し、resolver 用に正規化する.

    Args:
        request (BeatmapFileWarmupRequest):
            beatmap ID と optional MD5 checksum を含む warmup request.

    Returns:
        _IdentityPolicyResult: 正の beatmap ID を優先したVALID、checksumを lowercase
        化したVALID、または skip
        policy outcome.

    Notes:
        beatmap ID が正なら checksum の形式にかかわらず優先する.
        0はidentityなし、負数と32桁hex以外のchecksumはmalformedとして扱う.
    """
    beatmap_id = request.beatmap_id
    checksum_md5 = request.checksum_md5

    valid_beatmap_id = beatmap_id is not None and beatmap_id > 0
    malformed_beatmap_id = beatmap_id is not None and beatmap_id < 0
    if checksum_md5 is None or checksum_md5 == "":
        has_checksum = False
        normalized_checksum = None
    else:
        has_checksum = True
        normalized_checksum = checksum_md5.lower()
    valid_checksum = (
        normalized_checksum is not None
        and _NORMALIZED_MD5_RE.fullmatch(normalized_checksum) is not None
    )
    malformed_checksum = has_checksum and not valid_checksum

    if valid_beatmap_id:
        return _IdentityPolicyResult(
            outcome=_IdentityPolicyOutcome.VALID,
            identity=_NormalizedWarmupIdentity(
                beatmap_id=beatmap_id,
                checksum_md5=None,
            ),
        )

    if valid_checksum:
        return _IdentityPolicyResult(
            outcome=_IdentityPolicyOutcome.VALID,
            identity=_NormalizedWarmupIdentity(
                beatmap_id=None,
                checksum_md5=normalized_checksum,
            ),
        )

    if malformed_beatmap_id or malformed_checksum:
        return _IdentityPolicyResult(
            outcome=_IdentityPolicyOutcome.MALFORMED,
            identity=None,
        )

    return _IdentityPolicyResult(
        outcome=_IdentityPolicyOutcome.NO_IDENTITY,
        identity=None,
    )


def _outcome_from_resolve_result(
    resolve_result: BeatmapResolveResult,
) -> BeatmapFileWarmupOutcome:
    """Resolver result の metadata と file state を warmup outcome へ写像する.

    Args:
        resolve_result (BeatmapResolveResult):
            metadata と file availability を含む resolver result.

    Returns:
        BeatmapFileWarmupOutcome: metadata 未取得なら`METADATA_PENDING`、file
        利用可能なら`ALREADY_AVAILABLE`、それ以外は`REQUESTED`.
    """
    if resolve_result.beatmap is None:
        return BeatmapFileWarmupOutcome.METADATA_PENDING
    if resolve_result.file_status is BeatmapFileState.AVAILABLE:
        return BeatmapFileWarmupOutcome.ALREADY_AVAILABLE
    return BeatmapFileWarmupOutcome.REQUESTED


def _reason_from_resolve_result(resolve_result: BeatmapResolveResult) -> str | None:
    """Resolver result から stable な warmup diagnostic reason を選ぶ.

    Args:
        resolve_result (BeatmapResolveResult): reason と file state を含む resolver result.

    Returns:
        str | None: file 利用可能なら`"file_available"`、それ以外は resolver が返した reason.
    """
    if resolve_result.file_status is BeatmapFileState.AVAILABLE:
        return "file_available"
    return resolve_result.reason


def _log_result(
    result: BeatmapFileWarmupResult,
    *,
    exception_type: str | None = None,
) -> None:
    """Warmup result を機密情報を含めず structured log へ出力する.

    Args:
        result (BeatmapFileWarmupResult):
            outcome、入口、正規化済み identity、reason を含む診断結果.
        exception_type (str | None):
            resolver failure 時に記録する exception class 名. exception 本文は記録しない.

    Returns:
        None: structured diagnostic event を出力して完了し、呼び出し側へ値を返さない.
    """
    logger.info(
        "beatmap_file_warmup",
        outcome=result.outcome.value,
        entrance=result.entrance.value,
        user_id=result.user_id,
        beatmap_id=result.beatmap_id,
        checksum_md5=result.checksum_md5,
        reason=result.reason,
        exception_type=exception_type,
    )


__all__ = [
    "BeatmapFileWarmupEntrance",
    "BeatmapFileWarmupOutcome",
    "BeatmapFileWarmupRequest",
    "BeatmapFileWarmupResolver",
    "BeatmapFileWarmupResult",
    "RequestBeatmapFileWarmupUseCase",
]
