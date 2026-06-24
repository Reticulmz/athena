"""HTTP infrastructure - beatmap mirror HTTP client.

BeatmapHttpClient は Protocol (interfaces.py) を re-export します.
具象クラスが必要な場合は beatmap_http_client モジュールから直接 import してください.
"""

from osu_server.infrastructure.http.beatmap_http_client import is_permanent_error
from osu_server.infrastructure.http.interfaces import BeatmapHttpClient, HttpFetchResult

__all__ = ["BeatmapHttpClient", "HttpFetchResult", "is_permanent_error"]
