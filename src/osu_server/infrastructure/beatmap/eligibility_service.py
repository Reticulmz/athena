"""Beatmap eligibility service for score ingestion."""

from osu_server.domain.beatmap.eligibility import BeatmapStatus, EligibilityResult


class BeatmapNotFoundError(Exception):
    """Raised when beatmap is not found in mirror."""

    beatmap_id: int

    def __init__(self, beatmap_id: int) -> None:
        self.beatmap_id = beatmap_id
        super().__init__(f"Beatmap {beatmap_id} not found in mirror")


# Mock beatmap mirror data for Wave 1
_MOCK_BEATMAP_MIRROR: dict[int, BeatmapStatus] = {
    1: BeatmapStatus.RANKED,
    2: BeatmapStatus.APPROVED,
    3: BeatmapStatus.LOVED,
    4: BeatmapStatus.QUALIFIED,
    100: BeatmapStatus.PENDING,
    101: BeatmapStatus.WIP,
    102: BeatmapStatus.GRAVEYARD,
    103: BeatmapStatus.NOT_SUBMITTED,
}

_ELIGIBLE_STATUSES = frozenset(
    {
        BeatmapStatus.RANKED,
        BeatmapStatus.APPROVED,
        BeatmapStatus.LOVED,
        BeatmapStatus.QUALIFIED,
    }
)


async def check_eligibility(beatmap_id: int) -> EligibilityResult:
    """
    Check if a beatmap is eligible for score submission.

    Args:
        beatmap_id: Beatmap ID to check

    Returns:
        EligibilityResult with eligibility status

    Raises:
        BeatmapNotFoundError: If beatmap not found in mirror

    Preconditions:
        - beatmap_id > 0

    Postconditions:
        - Returns eligibility status based on beatmap status
        - Eligible: Ranked, Approved, Loved, Qualified
        - Ineligible: Pending, WIP, Graveyard, NotSubmitted, Unknown
    """
    if beatmap_id <= 0:
        raise ValueError(f"Invalid beatmap_id: {beatmap_id}")

    status = _MOCK_BEATMAP_MIRROR.get(beatmap_id)
    if status is None:
        raise BeatmapNotFoundError(beatmap_id)

    eligible = status in _ELIGIBLE_STATUSES
    reason = None if eligible else f"Beatmap status {status.name} is not eligible"

    return EligibilityResult(eligible=eligible, status=status, reason=reason)
