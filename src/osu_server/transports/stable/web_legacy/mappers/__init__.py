"""Legacy web transport mappers."""

from osu_server.transports.stable.web_legacy.mappers.getscores import (
    GetscoresQueryParser,
    GetscoresStatusMapper,
    StableGetscoresLeaderboardMapper,
)
from osu_server.transports.stable.web_legacy.mappers.score_submit import (
    MultipartParseError,
    StableScorePayloadParser,
    StableScoreSubmitCommandMapping,
    StableScoreSubmitMapper,
)

__all__ = [
    "GetscoresQueryParser",
    "GetscoresStatusMapper",
    "MultipartParseError",
    "StableGetscoresLeaderboardMapper",
    "StableScorePayloadParser",
    "StableScoreSubmitCommandMapping",
    "StableScoreSubmitMapper",
]
