"""Tests for BeatmapEligibilityService."""

import pytest

from osu_server.domain.beatmap import BeatmapStatus, EligibilityResult
from osu_server.services.beatmap_eligibility_service import (
    BeatmapNotFoundError,
    check_eligibility,
)


@pytest.mark.asyncio
class TestCheckEligibility:
    """Tests for check_eligibility function."""

    async def test_ranked_beatmap_is_eligible(self) -> None:
        """Ranked beatmaps should be eligible."""
        result = await check_eligibility(1)

        assert isinstance(result, EligibilityResult)
        assert result.eligible is True
        assert result.status == BeatmapStatus.RANKED
        assert result.reason is None

    async def test_approved_beatmap_is_eligible(self) -> None:
        """Approved beatmaps should be eligible."""
        result = await check_eligibility(2)

        assert result.eligible is True
        assert result.status == BeatmapStatus.APPROVED
        assert result.reason is None

    async def test_loved_beatmap_is_eligible(self) -> None:
        """Loved beatmaps should be eligible."""
        result = await check_eligibility(3)

        assert result.eligible is True
        assert result.status == BeatmapStatus.LOVED
        assert result.reason is None

    async def test_qualified_beatmap_is_eligible(self) -> None:
        """Qualified beatmaps should be eligible."""
        result = await check_eligibility(4)

        assert result.eligible is True
        assert result.status == BeatmapStatus.QUALIFIED
        assert result.reason is None

    async def test_pending_beatmap_is_ineligible(self) -> None:
        """Pending beatmaps should be ineligible."""
        result = await check_eligibility(100)

        assert result.eligible is False
        assert result.status == BeatmapStatus.PENDING
        assert result.reason == "Beatmap status PENDING is not eligible"

    async def test_wip_beatmap_is_ineligible(self) -> None:
        """WIP beatmaps should be ineligible."""
        result = await check_eligibility(101)

        assert result.eligible is False
        assert result.status == BeatmapStatus.WIP
        assert result.reason == "Beatmap status WIP is not eligible"

    async def test_graveyard_beatmap_is_ineligible(self) -> None:
        """Graveyard beatmaps should be ineligible."""
        result = await check_eligibility(102)

        assert result.eligible is False
        assert result.status == BeatmapStatus.GRAVEYARD
        assert result.reason == "Beatmap status GRAVEYARD is not eligible"

    async def test_not_submitted_beatmap_is_ineligible(self) -> None:
        """Not submitted beatmaps should be ineligible."""
        result = await check_eligibility(103)

        assert result.eligible is False
        assert result.status == BeatmapStatus.NOT_SUBMITTED
        assert result.reason == "Beatmap status NOT_SUBMITTED is not eligible"

    async def test_unknown_beatmap_raises_not_found_error(self) -> None:
        """Unknown beatmap IDs should raise BeatmapNotFoundError."""
        with pytest.raises(BeatmapNotFoundError) as exc_info:
            _ = await check_eligibility(9999)

        assert exc_info.value.beatmap_id == 9999
        assert "Beatmap 9999 not found in mirror" in str(exc_info.value)

    async def test_invalid_beatmap_id_raises_value_error(self) -> None:
        """Invalid beatmap IDs should raise ValueError."""
        with pytest.raises(ValueError, match="Invalid beatmap_id: 0"):
            _ = await check_eligibility(0)

        with pytest.raises(ValueError, match="Invalid beatmap_id: -1"):
            _ = await check_eligibility(-1)
