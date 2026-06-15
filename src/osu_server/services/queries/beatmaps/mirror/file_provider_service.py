"""Beatmap file provider service with fallback logic."""

from __future__ import annotations

from dataclasses import dataclass, field

import structlog

from osu_server.domain.beatmaps import (
    BeatmapFileSource,
    BeatmapSourceError,
    BeatmapSourceErrorCategory,
    OsuFileFetchResult,
)
from osu_server.infrastructure.http import BeatmapHttpClient, is_permanent_error

logger: structlog.stdlib.BoundLogger = structlog.get_logger(__name__)  # pyright: ignore[reportAny]


class _FoundError(Exception):
    """Signal that a source returned a successful fetch result."""

    result: OsuFileFetchResult

    def __init__(self, result: OsuFileFetchResult) -> None:
        super().__init__()
        self.result = result


@dataclass(slots=True)
class BeatmapFileProviderService:
    """Fetches .osu files with source priority: current > legacy > mirrors.

    Temporary failures (rate limit, timeout, 5xx) trigger fallback to next source.
    Permanent failures (404, 401) do not fall through to mirrors.
    """

    osu_current_url_template: str = "https://osu.ppy.sh/osu/{beatmap_id}"
    osu_legacy_url_template: str = "https://old.ppy.sh/osu/{beatmap_id}"
    mirror_url_templates: list[str] = field(default_factory=list)
    http_client: BeatmapHttpClient = field(default_factory=BeatmapHttpClient)

    async def fetch_osu_file(self, beatmap_id: int) -> OsuFileFetchResult:
        """Fetch .osu file with fallback priority.

        Args:
            beatmap_id: Beatmap ID to fetch

        Returns:
            OsuFileFetchResult with file content and metadata

        Raises:
            BeatmapSourceError: All sources failed or permanent error encountered
        """
        lookup_key = f"beatmap_id={beatmap_id}"

        # Phase 1: try direct sources
        try:
            await self._try_direct_sources(beatmap_id, lookup_key)
        except _FoundError as found:
            return found.result
        except BeatmapSourceError as direct_error:
            if is_permanent_error(direct_error):
                raise
            # temporary: fall through to mirrors

        # Phase 2: try community mirrors
        try:
            await self._try_mirror_sources(beatmap_id, lookup_key)
        except _FoundError as found:
            logger.info(
                "beatmap_mirror_fallback_used",
                source_type="file",
                beatmap_id=beatmap_id,
                source=found.result.source.value,
            )
            return found.result
        except BeatmapSourceError:
            raise

        raise BeatmapSourceError(
            category=BeatmapSourceErrorCategory.TEMPORARY_UNAVAILABLE,
            source="composite",
            lookup_key=lookup_key,
            message=f"All .osu file sources exhausted for beatmap_id={beatmap_id}",
        )

    async def _try_fetch(
        self,
        *,
        url_template: str,
        beatmap_id: int,
        source: BeatmapFileSource,
        source_label: str,
        lookup_key: str,
    ) -> OsuFileFetchResult:
        url = url_template.format(beatmap_id=beatmap_id)
        result = await self.http_client.fetch(url, source=source_label, lookup_key=lookup_key)
        return OsuFileFetchResult(
            beatmap_id=beatmap_id,
            body=result.content,
            source=source,
            original_filename=result.filename,
        )

    async def _try_direct_sources(self, beatmap_id: int, lookup_key: str) -> None:
        """Try osu_current then osu_legacy.

        Raises:
            _FoundError: A source succeeded
            BeatmapSourceError: All failed; permanent errors propagate immediately
        """
        last_error: BeatmapSourceError | None = None

        for url_template, source, label in (
            (self.osu_current_url_template, BeatmapFileSource.OSU_CURRENT, "osu_current"),
            (self.osu_legacy_url_template, BeatmapFileSource.OSU_LEGACY, "osu_legacy"),
        ):
            try:
                result = await self._try_fetch(
                    url_template=url_template,
                    beatmap_id=beatmap_id,
                    source=source,
                    source_label=label,
                    lookup_key=lookup_key,
                )
                raise _FoundError(result)
            except BeatmapSourceError as exc:
                last_error = exc
                if is_permanent_error(exc):
                    raise

        assert last_error is not None
        raise last_error

    async def _try_mirror_sources(self, beatmap_id: int, lookup_key: str) -> None:
        """Try community mirrors in order.

        Raises:
            _FoundError: A mirror succeeded
            BeatmapSourceError: All failed
        """
        last_error: BeatmapSourceError | None = None
        for idx, url_template in enumerate(self.mirror_url_templates):
            label = f"community_mirror[{idx}]"
            try:
                result = await self._try_fetch(
                    url_template=url_template,
                    beatmap_id=beatmap_id,
                    source=BeatmapFileSource.COMMUNITY_MIRROR,
                    source_label=label,
                    lookup_key=lookup_key,
                )
                raise _FoundError(result)
            except BeatmapSourceError as exc:
                last_error = exc
                if is_permanent_error(exc):
                    raise

        if last_error is not None:
            raise last_error
