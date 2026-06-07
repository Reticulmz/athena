"""GetscoresFormatter — format stable getscores response bodies.

Produces text/plain; charset=UTF-8 response bodies matching the
wire format expected by the stable osu! client.
"""

from __future__ import annotations

from enum import Enum
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from osu_server.domain.beatmap import Beatmap, BeatmapSet


class GetscoresOutcomeKind(Enum):
    """Kinds of getscores resolution outcomes.

    Full implementation deferred to task 3.1 (metadata resolver).
    """

    UNAVAILABLE = "unavailable"
    UPDATE_AVAILABLE = "update_available"
    HEADER = "header"


class GetscoresResolvedHeader:
    """Resolved header data for a getscores response.

    Full implementation deferred to task 3.1 (metadata resolver).
    """


def _sanitize(text: str) -> str:
    """Replace pipe delimiters and line breaks to protect the wire format."""
    return text.replace("|", " ").replace("\r", " ").replace("\n", " ")


class GetscoresFormatter:
    """Formats getscores response bodies for the stable osu! client."""

    def format_unavailable(self) -> bytes:
        """Format the unavailable short body (-1|false)."""
        return b"-1|false"

    def format_update_available(self) -> bytes:
        """Format the update-available short body (1|false)."""
        return b"1|false"

    def format_header(
        self,
        *,
        status: int,
        beatmap: Beatmap,
        beatmapset: BeatmapSet,
    ) -> bytes:
        """Format a full header response body.

        Returns a 6-line body: status line, beatmap offset, display title,
        rating line, and two blank separator lines, terminated by newline.
        """
        artist = _sanitize(beatmapset.artist)
        title = _sanitize(beatmapset.title)

        return (
            f"{status}|false|{beatmap.id}|{beatmap.beatmapset_id}|0||\n"
            f"0\n"
            f"[bold:0,size:20]{artist}|{title}\n"
            f"0\n"
            f"\n"
            f"\n"
        ).encode()
