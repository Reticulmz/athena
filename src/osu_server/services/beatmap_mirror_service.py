"""Cache-first beatmap resolution service.

Provides ``resolve_by_beatmap_id``, ``resolve_by_beatmapset_id``, and
``resolve_by_checksum`` with structured result states for callers like
score submission, leaderboard, and rank management.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from typing import TYPE_CHECKING

from osu_server.domain.beatmap import (
    Beatmap,
    BeatmapFetchState,
    BeatmapFileState,
    BeatmapMetadataSource,
    BeatmapSet,
    BeatmapSourceVerification,
)
from osu_server.repositories.interfaces.beatmap_repository import (
    BeatmapFetchTarget,
    BeatmapRepository,
)

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable

    from osu_server.services.beatmap_eligibility import (
        BeatmapEligibility,
        BeatmapEligibilityService,
    )
    from osu_server.services.beatmap_freshness import (
        BeatmapFreshnessDecision,
        BeatmapFreshnessPolicy,
    )


# ---------------------------------------------------------------------------
# Resolve input / output value objects
# ---------------------------------------------------------------------------


@dataclass(slots=True, frozen=True)
class BeatmapResolveOptions:
    """Options controlling beatmap resolution behavior.

    * ``require_osu_file`` -- when True, missing/absent .osu file is
      reflected in the result's file_status and reason.
    * ``wait_timeout_seconds`` -- maximum time to block waiting for a
      pending fetch before returning PENDING_FETCH (reserved for 5.2).
    * ``force_refresh`` -- when True, treat cached data as requiring
      refresh even when still fresh.
    """

    require_osu_file: bool = False
    wait_timeout_seconds: float = 0.0
    force_refresh: bool = False


@dataclass(slots=True, frozen=True)
class BeatmapResolveResult:
    """Structured result of a beatmap resolution for a single beatmap."""

    beatmap: Beatmap | None
    beatmapset: BeatmapSet | None
    eligibility: BeatmapEligibility | None
    metadata_status: BeatmapFetchState
    file_status: BeatmapFileState
    source: BeatmapMetadataSource | None
    verified: bool
    last_fetched_at: datetime | None
    next_refresh_at: datetime | None
    reason: str | None


@dataclass(slots=True, frozen=True)
class BeatmapSetResolveResult:
    """Structured result of a beatmapset resolution."""

    beatmapset: BeatmapSet | None
    metadata_status: BeatmapFetchState
    source: BeatmapMetadataSource | None
    verified: bool
    last_fetched_at: datetime | None
    next_refresh_at: datetime | None
    reason: str | None


# ---------------------------------------------------------------------------
# Service
# ---------------------------------------------------------------------------


class BeatmapMirrorService:
    """Cache-first beatmap resolver.

    Depends on ``BeatmapRepository`` for persistence lookups,
    ``BeatmapEligibilityService`` for eligibility projection, and
    ``BeatmapFreshnessPolicy`` for staleness decisions.  An optional
    ``enqueue_refresh`` callback can be wired in later (task 5.2) to
    trigger background metadata / file fetches.
    """

    _repository: BeatmapRepository
    _eligibility: BeatmapEligibilityService
    _freshness: BeatmapFreshnessPolicy
    _mirror_trust_enabled: bool
    _official_sources_available: bool
    _enqueue_refresh: Callable[[BeatmapFetchTarget], Awaitable[None]] | None

    def __init__(
        self,
        repository: BeatmapRepository,
        eligibility_service: BeatmapEligibilityService,
        freshness_policy: BeatmapFreshnessPolicy,
        *,
        mirror_trust_enabled: bool = False,
        official_sources_available: bool = True,
        enqueue_refresh: Callable[[BeatmapFetchTarget], Awaitable[None]] | None = None,
    ) -> None:
        self._repository = repository
        self._eligibility = eligibility_service
        self._freshness = freshness_policy
        self._mirror_trust_enabled = mirror_trust_enabled
        self._official_sources_available = official_sources_available
        self._enqueue_refresh = enqueue_refresh  # wired in task 5.2

    # ------------------------------------------------------------------
    # Public resolve methods
    # ------------------------------------------------------------------

    async def resolve_by_beatmap_id(
        self,
        beatmap_id: int,
        options: BeatmapResolveOptions | None = None,
    ) -> BeatmapResolveResult:
        """Resolve a single beatmap by its id."""
        opts = options or BeatmapResolveOptions()
        now = datetime.now(UTC)

        beatmap = await self._repository.get_beatmap(beatmap_id)
        if beatmap is None:
            return await self._unknown_result(
                metadata_target=BeatmapFetchTarget.metadata_by_beatmap_id(beatmap_id),
                file_target=BeatmapFetchTarget.file_by_beatmap_id(beatmap_id),
                opts=opts,
                now=now,
            )

        return await self._known_beatmap_result(beatmap, opts, now)

    async def resolve_by_beatmapset_id(
        self,
        beatmapset_id: int,
        options: BeatmapResolveOptions | None = None,
    ) -> BeatmapSetResolveResult:
        """Resolve a beatmapset by its id."""
        opts = options or BeatmapResolveOptions()
        now = datetime.now(UTC)

        beatmapset = await self._repository.get_beatmapset(beatmapset_id)
        if beatmapset is None:
            return await self._unknown_set_result(
                metadata_target=BeatmapFetchTarget.metadata_by_beatmapset_id(beatmapset_id),
                opts=opts,
                now=now,
            )

        return _set_result(beatmapset)

    async def resolve_by_checksum(
        self,
        checksum_md5: str,
        options: BeatmapResolveOptions | None = None,
    ) -> BeatmapResolveResult:
        """Resolve a beatmap by its MD5 checksum."""
        opts = options or BeatmapResolveOptions()
        now = datetime.now(UTC)

        beatmap = await self._repository.get_beatmap_by_checksum(checksum_md5)
        if beatmap is None:
            return await self._unknown_result(
                metadata_target=BeatmapFetchTarget.metadata_by_checksum(checksum_md5),
                file_target=None,
                opts=opts,
                now=now,
            )

        return await self._known_beatmap_result(beatmap, opts, now)

    # ------------------------------------------------------------------
    # Known beatmap result builder
    # ------------------------------------------------------------------

    async def _known_beatmap_result(
        self,
        beatmap: Beatmap,
        opts: BeatmapResolveOptions,
        now: datetime,
    ) -> BeatmapResolveResult:
        decision = self._freshness.evaluate(
            beatmap,
            now=now,
            official_sources_available=self._official_sources_available,
            force_refresh=opts.force_refresh,
        )
        beatmapset = await self._repository.get_beatmapset(beatmap.beatmapset_id)
        eligibility = self._eligibility.evaluate(
            beatmap, mirror_trust_enabled=self._mirror_trust_enabled
        )

        reason = _result_reason(decision, opts, beatmap)

        return BeatmapResolveResult(
            beatmap=beatmap,
            beatmapset=beatmapset,
            eligibility=eligibility,
            metadata_status=_derive_metadata_status(beatmap, decision),
            file_status=beatmap.file_state,
            source=beatmap.official_status_source,
            verified=beatmap.official_status_verified is BeatmapSourceVerification.VERIFIED,
            last_fetched_at=beatmap.last_fetched_at,
            next_refresh_at=beatmap.next_refresh_at,
            reason=reason,
        )

    # ------------------------------------------------------------------
    # Unknown result builders
    # ------------------------------------------------------------------

    async def _unknown_result(
        self,
        *,
        metadata_target: BeatmapFetchTarget,
        file_target: BeatmapFetchTarget | None,
        opts: BeatmapResolveOptions,  # noqa: ARG002  # pyright: ignore[reportUnusedParameter] -- reserved for task 5.2
        now: datetime,  # noqa: ARG002  # pyright: ignore[reportUnusedParameter] -- reserved for task 5.2
    ) -> BeatmapResolveResult:
        metadata_record = await self._repository.get_fetch_state(metadata_target)

        if metadata_record is None:
            return BeatmapResolveResult(
                beatmap=None,
                beatmapset=None,
                eligibility=None,
                metadata_status=BeatmapFetchState.PENDING_FETCH,
                file_status=BeatmapFileState.MISSING,
                source=None,
                verified=False,
                last_fetched_at=None,
                next_refresh_at=None,
                reason="unsolicited",
            )

        file_state = await self._lookup_file_state(file_target)
        return BeatmapResolveResult(
            beatmap=None,
            beatmapset=None,
            eligibility=None,
            metadata_status=metadata_record.status,
            file_status=file_state,
            source=None,
            verified=False,
            last_fetched_at=None,
            next_refresh_at=None,
            reason=_fetch_record_reason(metadata_record),
        )

    async def _unknown_set_result(
        self,
        *,
        metadata_target: BeatmapFetchTarget,
        opts: BeatmapResolveOptions,  # noqa: ARG002  # pyright: ignore[reportUnusedParameter] -- reserved for task 5.2
        now: datetime,  # noqa: ARG002  # pyright: ignore[reportUnusedParameter] -- reserved for task 5.2
    ) -> BeatmapSetResolveResult:
        metadata_record = await self._repository.get_fetch_state(metadata_target)

        if metadata_record is None:
            return BeatmapSetResolveResult(
                beatmapset=None,
                metadata_status=BeatmapFetchState.PENDING_FETCH,
                source=None,
                verified=False,
                last_fetched_at=None,
                next_refresh_at=None,
                reason="unsolicited",
            )

        return BeatmapSetResolveResult(
            beatmapset=None,
            metadata_status=metadata_record.status,
            source=None,
            verified=False,
            last_fetched_at=None,
            next_refresh_at=None,
            reason=_fetch_record_reason(metadata_record),
        )

    async def _lookup_file_state(
        self,
        file_target: BeatmapFetchTarget | None,
    ) -> BeatmapFileState:
        """Determine file fetch state for unknown beatmap."""
        if file_target is None:
            return BeatmapFileState.MISSING

        record = await self._repository.get_fetch_state(file_target)
        if record is None:
            return BeatmapFileState.MISSING

        return _file_state_from_fetch_status(record.status)


# ---------------------------------------------------------------------------
# Module-level helpers
# ---------------------------------------------------------------------------


def _derive_metadata_status(
    beatmap: Beatmap,
    decision: BeatmapFreshnessDecision,
) -> BeatmapFetchState:
    """Derive metadata status from beatmap fetch state and freshness decision."""
    if beatmap.metadata_fetch_state is BeatmapFetchState.PENDING_FETCH:
        return BeatmapFetchState.PENDING_FETCH
    if beatmap.metadata_fetch_state is BeatmapFetchState.FAILED:
        return BeatmapFetchState.FAILED
    if decision.should_refresh:
        return BeatmapFetchState.STALE
    return BeatmapFetchState.FRESH


def _result_reason(
    decision: BeatmapFreshnessDecision,
    opts: BeatmapResolveOptions,
    beatmap: Beatmap,
) -> str | None:
    """Derive a human-readable reason string."""
    if opts.require_osu_file and beatmap.file_state is not BeatmapFileState.AVAILABLE:
        return "osu_file_required_but_unavailable"
    return decision.reason


def _fetch_record_reason(record: object) -> str | None:
    status: object = getattr(record, "status", None)
    if status is BeatmapFetchState.FAILED:
        error: object = getattr(record, "last_error", None)
        return error if isinstance(error, str) else "fetch_failed"
    if status is BeatmapFetchState.PENDING_FETCH:
        return "pending_fetch"
    return None


def _file_state_from_fetch_status(status: BeatmapFetchState) -> BeatmapFileState:
    if status is BeatmapFetchState.PENDING_FETCH:
        return BeatmapFileState.PENDING_FETCH
    if status is BeatmapFetchState.FAILED:
        return BeatmapFileState.FAILED
    return BeatmapFileState.MISSING


def _set_result(beatmapset: BeatmapSet) -> BeatmapSetResolveResult:
    """Build a resolve result for a known, cached beatmapset."""
    return BeatmapSetResolveResult(
        beatmapset=beatmapset,
        metadata_status=BeatmapFetchState.FRESH,
        source=beatmapset.official_status_source,
        verified=beatmapset.official_status_verified is BeatmapSourceVerification.VERIFIED,
        last_fetched_at=beatmapset.last_fetched_at,
        next_refresh_at=beatmapset.next_refresh_at,
        reason=None,
    )
