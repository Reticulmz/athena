"""Legacy web transport mappers."""

from osu_server.transports.stable.web_legacy.mappers.getscores import (
    GetscoresQueryParser,
    GetscoresStatusMapper,
    StableGetscoresLeaderboardMapper,
)
from osu_server.transports.stable.web_legacy.mappers.replay_download import (
    ReplayDownloadMalformedReason,
    ReplayDownloadParseResult,
    ReplayDownloadQueryParser,
    ReplayDownloadRequest,
)
from osu_server.transports.stable.web_legacy.mappers.score_submit import (
    MultipartParseError,
    StableScorePayloadParser,
    StableScoreSubmitCommandMapping,
    StableScoreSubmitMapper,
    StableScoreSubmitOverallStats,
)

__all__ = [
    "GetscoresQueryParser",
    "GetscoresStatusMapper",
    "MultipartParseError",
    "ReplayDownloadMalformedReason",
    "ReplayDownloadParseResult",
    "ReplayDownloadQueryParser",
    "ReplayDownloadRequest",
    "StableGetscoresLeaderboardMapper",
    "StableScorePayloadParser",
    "StableScoreSubmitCommandMapping",
    "StableScoreSubmitMapper",
    "StableScoreSubmitOverallStats",
]
