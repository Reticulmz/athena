"""GetscoresResolver — resolve parsed getscores requests into response outcomes.

Checksum-first resolution with bounded-wait metadata resolution via
BeatmapMirrorService.  Returns HEADER, UNAVAILABLE, or UPDATE_AVAILABLE
outcomes.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import TYPE_CHECKING, cast

from osu_server.domain.beatmap import BeatmapFetchState
from osu_server.services.beatmap_mirror_service import (
    BeatmapResolveOptions,
    BeatmapResolveResult,
)

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable

    from osu_server.domain.beatmap import Beatmap, BeatmapSet
    from osu_server.repositories.interfaces.beatmap_repository import BeatmapRepository
    from osu_server.transports.web_legacy.getscores_query_parser import GetscoresRequest
    from osu_server.transports.web_legacy.getscores_status_mapper import (
        GetscoresStatusMapper,
    )


class GetscoresOutcomeKind(Enum):
    """Kinds of getscores resolution outcomes."""

    HEADER = "header"
    UNAVAILABLE = "unavailable"
    UPDATE_AVAILABLE = "update_available"


class GetscoresResolveReason(Enum):
    """Why the resolver produced a particular outcome."""

    KNOWN_CHECKSUM = "known_checksum"
    KNOWN_FILENAME_IN_SET = "known_filename_in_set"
    NOT_SUBMITTED = "not_submitted"
    NOT_FOUND = "not_found"
    PENDING_FETCH = "pending_fetch"
    FAILED_METADATA = "failed_metadata"
    UPDATE_AVAILABLE = "update_available"


@dataclass(slots=True, frozen=True)
class GetscoresResolvedHeader:
    """Resolved beatmap and beatmapset for a HEADER outcome."""

    beatmap: Beatmap
    beatmapset: BeatmapSet


@dataclass(slots=True, frozen=True)
class GetscoresResolveOutcome:
    """Result of resolving a getscores request."""

    kind: GetscoresOutcomeKind
    header: GetscoresResolvedHeader | None
    reason: GetscoresResolveReason


class GetscoresResolver:
    """Resolves a parsed GetscoresRequest into a GetscoresResolveOutcome.

    Checksum-first: if the checksum is known locally, returns HEADER
    immediately without calling the mirror service.  For unknown checksums,
    delegates to the mirror service's bounded-wait metadata resolution.
    """

    _repo: BeatmapRepository
    _mapper: GetscoresStatusMapper
    _mirror_resolve: Callable[..., Awaitable[object]] | None

    def __init__(
        self,
        *,
        repository: BeatmapRepository,
        status_mapper: GetscoresStatusMapper,
        _mirror_resolve: Callable[..., Awaitable[object]] | None = None,
    ) -> None:
        self._repo = repository
        self._mapper = status_mapper
        self._mirror_resolve = _mirror_resolve

    async def resolve(  # noqa: PLR0911  # decision-tree method with early returns
        self,
        request: GetscoresRequest,
        *,
        wait_timeout_seconds: float = 5.0,
    ) -> GetscoresResolveOutcome:
        """Resolve a GetscoresRequest to a typed outcome.

        Args:
            request: Parsed getscores query fields.
            wait_timeout_seconds: Max time to wait for metadata resolution
                when the checksum is unknown.

        Returns:
            GetscoresResolveOutcome with kind, optional header, and reason.
        """
        # -- Checksum path (highest priority) --------------------------------
        if request.checksum_md5 is not None:
            beatmap = await self._repo.get_beatmap_by_checksum(request.checksum_md5)
            if beatmap is not None:
                return await self._evaluate_known_beatmap(
                    beatmap, reason=GetscoresResolveReason.KNOWN_CHECKSUM
                )

            # Checksum miss — try UpdateAvailable via filename + set hint
            if request.filename is not None and request.beatmapset_id_hint is not None:
                return await self._resolve_update_available(
                    request.checksum_md5,
                    request.beatmapset_id_hint,
                    request.filename,
                    wait_timeout_seconds=wait_timeout_seconds,
                )

            # Unknown checksum -> mirror service with bounded wait
            if self._mirror_resolve is not None:
                return await self._resolve_via_mirror(request.checksum_md5, wait_timeout_seconds)

            return self._unavailable(GetscoresResolveReason.NOT_FOUND)

        # -- Filename + beatmapset id path ------------------------------------
        if request.filename is not None and request.beatmapset_id_hint is not None:
            beatmap = await self._repo.get_beatmap_by_filename_in_beatmapset(
                request.beatmapset_id_hint, request.filename
            )
            if beatmap is not None:
                return await self._evaluate_known_beatmap(
                    beatmap, reason=GetscoresResolveReason.KNOWN_FILENAME_IN_SET
                )

            return self._unavailable(GetscoresResolveReason.NOT_FOUND)

        # -- Insufficient identity --------------------------------------------
        return self._unavailable(GetscoresResolveReason.NOT_FOUND)

    # ------------------------------------------------------------------
    # Internal resolution helpers
    # ------------------------------------------------------------------

    async def _evaluate_known_beatmap(
        self,
        beatmap: Beatmap,
        *,
        reason: GetscoresResolveReason,
    ) -> GetscoresResolveOutcome:
        """Determine outcome for a beatmap we already have in the repository."""
        beatmapset = await self._repo.get_beatmapset(beatmap.beatmapset_id)
        if beatmapset is None:
            return self._unavailable(GetscoresResolveReason.NOT_FOUND)

        wire_status = self._mapper.map_header_status(beatmap)
        if wire_status is None:
            return self._unavailable(GetscoresResolveReason.NOT_SUBMITTED)

        return GetscoresResolveOutcome(
            kind=GetscoresOutcomeKind.HEADER,
            header=GetscoresResolvedHeader(beatmap=beatmap, beatmapset=beatmapset),
            reason=reason,
        )

    async def _resolve_update_available(
        self,
        checksum_md5: str,
        beatmapset_id: int,
        filename: str,
        *,
        wait_timeout_seconds: float = 5.0,
    ) -> GetscoresResolveOutcome:
        """Check for UpdateAvailable when checksum misses and filename+set hint exists.

        If the filename+set lookup finds a submitted beatmap with a different
        checksum, returns UPDATE_AVAILABLE.  Otherwise falls through to mirror
        resolve or returns UNAVAILABLE.
        """
        beatmap = await self._repo.get_beatmap_by_filename_in_beatmapset(beatmapset_id, filename)
        if beatmap is None:
            # No match found — fall through to mirror or UNAVAILABLE
            if self._mirror_resolve is not None:
                return await self._resolve_via_mirror(checksum_md5, wait_timeout_seconds)
            return self._unavailable(GetscoresResolveReason.NOT_FOUND)

        # Found a beatmap by filename+set — check for different checksum
        if beatmap.checksum_md5 == checksum_md5:
            # Same checksum; shouldn't normally reach here (checksum lookup
            # already tried), but evaluate defensively.
            return await self._evaluate_known_beatmap(
                beatmap, reason=GetscoresResolveReason.KNOWN_FILENAME_IN_SET
            )

        # Different checksum — check if the stored beatmap is submitted
        beatmapset = await self._repo.get_beatmapset(beatmap.beatmapset_id)
        if beatmapset is None:
            return self._unavailable(GetscoresResolveReason.NOT_FOUND)

        wire_status = self._mapper.map_header_status(beatmap)
        if wire_status is None:
            return self._unavailable(GetscoresResolveReason.NOT_SUBMITTED)

        # Same set+filename, different checksum, submitted → UPDATE_AVAILABLE
        return GetscoresResolveOutcome(
            kind=GetscoresOutcomeKind.UPDATE_AVAILABLE,
            header=GetscoresResolvedHeader(beatmap=beatmap, beatmapset=beatmapset),
            reason=GetscoresResolveReason.UPDATE_AVAILABLE,
        )

    async def _resolve_via_mirror(
        self,
        checksum_md5: str,
        wait_timeout_seconds: float,
    ) -> GetscoresResolveOutcome:
        """Call the mirror service with bounded wait and interpret the result."""
        assert self._mirror_resolve is not None  # should only be called when set

        options = BeatmapResolveOptions(
            require_osu_file=False,
            wait_timeout_seconds=wait_timeout_seconds,
        )

        raw = await self._mirror_resolve(checksum_md5, options)
        result = cast("BeatmapResolveResult", raw)

        if result.beatmap is not None and result.beatmapset is not None:
            return await self._evaluate_known_beatmap(
                result.beatmap, reason=GetscoresResolveReason.KNOWN_CHECKSUM
            )

        if result.metadata_status is BeatmapFetchState.PENDING_FETCH:
            return self._unavailable(GetscoresResolveReason.PENDING_FETCH)

        return self._unavailable(GetscoresResolveReason.FAILED_METADATA)

    @staticmethod
    def _unavailable(reason: GetscoresResolveReason) -> GetscoresResolveOutcome:
        """Return an UNAVAILABLE outcome with the given reason."""
        return GetscoresResolveOutcome(
            kind=GetscoresOutcomeKind.UNAVAILABLE,
            header=None,
            reason=reason,
        )
