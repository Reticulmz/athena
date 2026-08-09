"""Legacy web transportの公開mapperを集約する."""

from osu_server.transports.stable.web_legacy.mappers.direct import (
    StableDirectSearchParseError,
    StableDirectSearchParseResult,
    StableDirectSearchQueryParser,
)
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
    StableScoreSubmitDecodeError,
    StableScoreSubmitDecoder,
    StableScoreSubmitMapper,
    StableScoreSubmitOverallStats,
    StableScoreSubmitRequestMapping,
)

__all__ = [
    "GetscoresQueryParser",
    "GetscoresStatusMapper",
    "MultipartParseError",
    "ReplayDownloadMalformedReason",
    "ReplayDownloadParseResult",
    "ReplayDownloadQueryParser",
    "ReplayDownloadRequest",
    "StableDirectSearchParseError",
    "StableDirectSearchParseResult",
    "StableDirectSearchQueryParser",
    "StableGetscoresLeaderboardMapper",
    "StableScorePayloadParser",
    "StableScoreSubmitCommandMapping",
    "StableScoreSubmitDecodeError",
    "StableScoreSubmitDecoder",
    "StableScoreSubmitMapper",
    "StableScoreSubmitOverallStats",
    "StableScoreSubmitRequestMapping",
]
