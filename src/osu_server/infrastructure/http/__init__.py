"""HTTP infrastructure - beatmap mirror HTTP client."""

from osu_server.infrastructure.http.beatmap_http_client import (
    BeatmapHttpClient,
    HttpFetchResult,
    is_permanent_error,
)

__all__ = ["BeatmapHttpClient", "HttpFetchResult", "is_permanent_error"]
