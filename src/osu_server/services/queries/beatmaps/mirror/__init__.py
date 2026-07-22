"""beatmap mirrorのread-only解決とeligibility判定serviceを公開するpackageを定義する."""

from osu_server.services.queries.beatmaps.mirror.eligibility_service import (
    BeatmapEligibilityService,
    BeatmapStatusResolver,
)
from osu_server.services.queries.beatmaps.mirror.resolution_service import (
    BeatmapMirrorService,
)

__all__ = [
    "BeatmapEligibilityService",
    "BeatmapMirrorService",
    "BeatmapStatusResolver",
]
