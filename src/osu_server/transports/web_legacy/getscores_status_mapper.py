"""GetscoresStatusMapper — map BeatmapRankStatus to getscores wire values.

Converts a Beatmap's effective_status to the integer wire values the
stable osu! client expects in the getscores response header.
"""

from __future__ import annotations

from osu_server.domain.beatmap import Beatmap, BeatmapRankStatus

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


class GetscoresStatusMapper:
    """Maps Beatmap effective_status to getscores wire values."""

    def map_header_status(self, beatmap: Beatmap) -> int | None:
        """Return the getscores wire value for a beatmap's effective status.

        Returns:
            Integer wire value (0, 2, 3, 4, 5) or None for not-submitted/unknown.
        """
        return _STATUS_TO_WIRE.get(beatmap.effective_status)
