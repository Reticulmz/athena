"""Stable beatmap file warmup command boundary."""

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
    """Stable entrances that may request beatmap file warmup."""

    STABLE_GETSCORES = "stable_getscores"
    STABLE_STATUS_CHANGE = "stable_status_change"
    STABLE_SCORE_SUBMIT_FALLBACK = "stable_score_submit_fallback"


class BeatmapFileWarmupOutcome(Enum):
    """Operator-visible warmup outcome."""

    REQUESTED = "requested"
    ALREADY_AVAILABLE = "already_available"
    METADATA_PENDING = "metadata_pending"
    SKIPPED_NO_IDENTITY = "skipped_no_identity"
    SKIPPED_MALFORMED_IDENTITY = "skipped_malformed_identity"
    FAILED = "failed"


@dataclass(slots=True, frozen=True)
class BeatmapFileWarmupRequest:
    """Authenticated stable activity requesting beatmap file preparation."""

    entrance: BeatmapFileWarmupEntrance
    user_id: int
    beatmap_id: int | None = None
    checksum_md5: str | None = None


@dataclass(slots=True, frozen=True)
class BeatmapFileWarmupResult:
    """Warmup result used for diagnostics and tests."""

    outcome: BeatmapFileWarmupOutcome
    entrance: BeatmapFileWarmupEntrance
    user_id: int
    beatmap_id: int | None
    checksum_md5: str | None
    reason: str | None


class BeatmapFileWarmupResolver(Protocol):
    """Resolver boundary that owns existing beatmap fetch enqueue behavior."""

    async def resolve_by_beatmap_id(
        self,
        beatmap_id: int,
        options: BeatmapResolveOptions | None = None,
    ) -> BeatmapResolveResult: ...

    async def resolve_by_checksum(
        self,
        checksum_md5: str,
        options: BeatmapResolveOptions | None = None,
    ) -> BeatmapResolveResult: ...


@dataclass(slots=True, frozen=True)
class _NormalizedWarmupIdentity:
    beatmap_id: int | None
    checksum_md5: str | None


class _IdentityPolicyOutcome(Enum):
    VALID = "valid"
    NO_IDENTITY = "no_identity"
    MALFORMED = "malformed"


@dataclass(slots=True, frozen=True)
class _IdentityPolicyResult:
    outcome: _IdentityPolicyOutcome
    identity: _NormalizedWarmupIdentity | None


class RequestBeatmapFileWarmupUseCase:
    """Normalize authenticated stable warmup requests before resolver access."""

    def __init__(self, resolver: BeatmapFileWarmupResolver) -> None:
        self._resolver: BeatmapFileWarmupResolver
        self._resolver = resolver

    async def execute(
        self,
        request: BeatmapFileWarmupRequest,
    ) -> BeatmapFileWarmupResult:
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
            reason=resolve_result.reason,
        )
        _log_result(result)
        return result

    async def _resolve_identity(
        self,
        identity: _NormalizedWarmupIdentity,
    ) -> BeatmapResolveResult:
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
    if resolve_result.beatmap is None:
        return BeatmapFileWarmupOutcome.METADATA_PENDING
    if resolve_result.file_status is BeatmapFileState.AVAILABLE:
        return BeatmapFileWarmupOutcome.ALREADY_AVAILABLE
    return BeatmapFileWarmupOutcome.REQUESTED


def _log_result(
    result: BeatmapFileWarmupResult,
    *,
    exception_type: str | None = None,
) -> None:
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
