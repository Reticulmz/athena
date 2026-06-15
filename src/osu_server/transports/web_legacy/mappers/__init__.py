"""Legacy web transport mappers."""

from osu_server.transports.web_legacy.mappers.getscores import (
    GetscoresQueryParser,
    GetscoresStatusMapper,
)

__all__ = [
    "GetscoresQueryParser",
    "GetscoresStatusMapper",
]
