"""Service-level getscores parsing and beatmap resolution."""

from __future__ import annotations

import re
from typing import TYPE_CHECKING, cast

from osu_server.domain.beatmaps import (
    BeatmapFetchState,
    BeatmapRankStatus,
    BeatmapResolveOptions,
    BeatmapResolveResult,
)
from osu_server.domain.legacy_getscores import (
    GetscoresOutcomeKind,
    GetscoresParseError,
    GetscoresParseResult,
    GetscoresParseWarning,
    GetscoresRequest,
    GetscoresResolvedHeader,
    GetscoresResolveOutcome,
    GetscoresResolveReason,
)

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable, Mapping

    from osu_server.domain.beatmaps import Beatmap
    from osu_server.repositories.interfaces.beatmap_repository import BeatmapRepository

_MD5_HEX_PATTERN = re.compile(r"^[0-9a-fA-F]{32}$")
_STATUS_TO_WIRE: dict[BeatmapRankStatus, int | None] = {
    BeatmapRankStatus.NOT_SUBMITTED: None,
    BeatmapRankStatus.UNKNOWN: None,
    BeatmapRankStatus.PENDING: 0,
    BeatmapRankStatus.WIP: 0,
    BeatmapRankStatus.GRAVEYARD: 0,
    BeatmapRankStatus.RANKED: 2,
    BeatmapRankStatus.APPROVED: 3,
    BeatmapRankStatus.QUALIFIED: 4,
    BeatmapRankStatus.LOVED: 5,
}


class LegacyGetscoresService:
    _repo: BeatmapRepository
    _mirror_resolve: Callable[..., Awaitable[object]] | None

    def __init__(
        self,
        *,
        repository: BeatmapRepository,
        mirror_resolve: Callable[..., Awaitable[object]] | None = None,
        status_mapper: object | None = None,
        _mirror_resolve: Callable[..., Awaitable[object]] | None = None,
    ) -> None:
        del status_mapper
        self._repo = repository
        self._mirror_resolve = mirror_resolve or _mirror_resolve

    def parse(self, query: Mapping[str, str]) -> GetscoresParseResult:
        return _parse_query(query)

    async def resolve(  # noqa: PLR0911  # checksum-first resolution decision tree
        self,
        request: GetscoresRequest,
        *,
        wait_timeout_seconds: float = 5.0,
    ) -> GetscoresResolveOutcome:
        if request.checksum_md5 is not None:
            beatmap = await self._repo.get_beatmap_by_checksum(request.checksum_md5)
            if beatmap is not None:
                return await self._evaluate_known_beatmap(
                    beatmap, reason=GetscoresResolveReason.KNOWN_CHECKSUM
                )

            if request.filename is not None and request.beatmapset_id_hint is not None:
                return await self._resolve_update_available(
                    request.checksum_md5,
                    request.beatmapset_id_hint,
                    request.filename,
                    wait_timeout_seconds=wait_timeout_seconds,
                )

            if self._mirror_resolve is not None:
                return await self._resolve_via_mirror(request.checksum_md5, wait_timeout_seconds)

            return _unavailable(GetscoresResolveReason.NOT_FOUND)

        if request.filename is not None and request.beatmapset_id_hint is not None:
            beatmap = await self._repo.get_beatmap_by_filename_in_beatmapset(
                request.beatmapset_id_hint, request.filename
            )
            if beatmap is not None:
                return await self._evaluate_known_beatmap(
                    beatmap, reason=GetscoresResolveReason.KNOWN_FILENAME_IN_SET
                )

            return _unavailable(GetscoresResolveReason.NOT_FOUND)

        return _unavailable(GetscoresResolveReason.NOT_FOUND)

    def map_header_status(self, beatmap: Beatmap) -> int | None:
        return _STATUS_TO_WIRE.get(beatmap.effective_status)

    async def _evaluate_known_beatmap(
        self,
        beatmap: Beatmap,
        *,
        reason: GetscoresResolveReason,
    ) -> GetscoresResolveOutcome:
        beatmapset = await self._repo.get_beatmapset(beatmap.beatmapset_id)
        if beatmapset is None:
            return _unavailable(GetscoresResolveReason.NOT_FOUND)

        if self.map_header_status(beatmap) is None:
            return _unavailable(GetscoresResolveReason.NOT_SUBMITTED)

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
        beatmap = await self._repo.get_beatmap_by_filename_in_beatmapset(beatmapset_id, filename)
        if beatmap is None:
            if self._mirror_resolve is not None:
                return await self._resolve_via_mirror(checksum_md5, wait_timeout_seconds)
            return _unavailable(GetscoresResolveReason.NOT_FOUND)

        if beatmap.checksum_md5 == checksum_md5:
            return await self._evaluate_known_beatmap(
                beatmap, reason=GetscoresResolveReason.KNOWN_FILENAME_IN_SET
            )

        beatmapset = await self._repo.get_beatmapset(beatmap.beatmapset_id)
        if beatmapset is None:
            return _unavailable(GetscoresResolveReason.NOT_FOUND)

        if self.map_header_status(beatmap) is None:
            return _unavailable(GetscoresResolveReason.NOT_SUBMITTED)

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
        assert self._mirror_resolve is not None

        raw = await self._mirror_resolve(
            checksum_md5,
            BeatmapResolveOptions(
                require_osu_file=False,
                wait_timeout_seconds=wait_timeout_seconds,
            ),
        )
        result = cast("BeatmapResolveResult", raw)

        if result.beatmap is not None and result.beatmapset is not None:
            return await self._evaluate_known_beatmap(
                result.beatmap, reason=GetscoresResolveReason.KNOWN_CHECKSUM
            )

        if result.metadata_status is BeatmapFetchState.PENDING_FETCH:
            return _unavailable(GetscoresResolveReason.PENDING_FETCH)

        return _unavailable(GetscoresResolveReason.FAILED_METADATA)


def _parse_int(
    raw: str | None,
    warnings: list[GetscoresParseWarning],
    warning_kind: GetscoresParseWarning,
) -> int | None:
    if raw is None:
        return None
    try:
        return int(raw)
    except ValueError:
        warnings.append(warning_kind)
        return None


def _parse_bool(
    raw: str | None,
    warnings: list[GetscoresParseWarning],
    warning_kind: GetscoresParseWarning,
) -> bool | None:
    if raw is None:
        return None
    try:
        return bool(int(raw))
    except ValueError:
        warnings.append(warning_kind)
        return None


def _parse_query(query: Mapping[str, str]) -> GetscoresParseResult:
    warnings: list[GetscoresParseWarning] = []

    checksum_raw = query.get("c")
    filename = query.get("f") or None
    beatmapset_id_hint = _parse_int(
        query.get("i"), warnings, GetscoresParseWarning.INVALID_BEATMAPSET_ID_HINT
    )

    checksum_md5: str | None = None
    if checksum_raw is not None:
        if _MD5_HEX_PATTERN.match(checksum_raw):
            checksum_md5 = checksum_raw.lower()
        else:
            return GetscoresParseResult(error=GetscoresParseError.INVALID_CHECKSUM)

    mode = _parse_int(query.get("m"), warnings, GetscoresParseWarning.INVALID_MODE)
    mods = _parse_int(query.get("mods"), warnings, GetscoresParseWarning.INVALID_MODS)
    leaderboard_type = _parse_int(
        query.get("v"), warnings, GetscoresParseWarning.INVALID_LEADERBOARD_TYPE
    )
    leaderboard_version = _parse_int(
        query.get("vv"), warnings, GetscoresParseWarning.INVALID_LEADERBOARD_VERSION
    )
    song_select = _parse_bool(
        query.get("s"), warnings, GetscoresParseWarning.INVALID_SONG_SELECT_FLAG
    )

    has_checksum = checksum_md5 is not None
    has_fallback = filename is not None and beatmapset_id_hint is not None
    if not has_checksum and not has_fallback:
        return GetscoresParseResult(error=GetscoresParseError.MISSING_IDENTITY)

    return GetscoresParseResult(
        request=GetscoresRequest(
            checksum_md5=checksum_md5,
            filename=filename,
            beatmapset_id_hint=beatmapset_id_hint,
            mode=mode,
            mods=mods,
            leaderboard_type=leaderboard_type,
            leaderboard_version=leaderboard_version,
            song_select=song_select,
            anti_cheat_signal="a" in query,
            parse_warnings=tuple(warnings),
        )
    )


def _unavailable(reason: GetscoresResolveReason) -> GetscoresResolveOutcome:
    return GetscoresResolveOutcome(
        kind=GetscoresOutcomeKind.UNAVAILABLE,
        header=None,
        reason=reason,
    )


class GetscoresStatusMapper:
    def map_header_status(self, beatmap: Beatmap) -> int | None:
        return _STATUS_TO_WIRE.get(beatmap.effective_status)


class GetscoresQueryParser:
    def parse(self, query: Mapping[str, str]) -> GetscoresParseResult:
        return _parse_query(query)


GetscoresResolver = LegacyGetscoresService
