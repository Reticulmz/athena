"""Command repository interface package."""

from osu_server.repositories.interfaces.commands.beatmap_leaderboards import (
    BeatmapLeaderboardCommandRepository,
)
from osu_server.repositories.interfaces.commands.beatmap_performance_bests import (
    BeatmapPerformanceBestCommandRepository,
)
from osu_server.repositories.interfaces.commands.beatmaps import (
    BeatmapCommandRepository,
    BeatmapSubmissionCounts,
)
from osu_server.repositories.interfaces.commands.blobs import BlobCommandRepository
from osu_server.repositories.interfaces.commands.channels import ChannelCommandRepository
from osu_server.repositories.interfaces.commands.chat import ChatCommandRepository
from osu_server.repositories.interfaces.commands.current_user_stats import (
    CurrentUserStatsCommandRepository,
)
from osu_server.repositories.interfaces.commands.friends import (
    FriendRelationshipCommandRepository,
)
from osu_server.repositories.interfaces.commands.personal_bests import (
    PersonalBestCommandRepository,
)
from osu_server.repositories.interfaces.commands.replays import ReplayCommandRepository
from osu_server.repositories.interfaces.commands.roles import RoleCommandRepository
from osu_server.repositories.interfaces.commands.score_performance import (
    ScorePerformanceCalculationLifecycleRepository,
    ScorePerformanceCommandRepository,
    ScorePerformanceRecalculationWorkRepository,
)
from osu_server.repositories.interfaces.commands.scores import ScoreCommandRepository
from osu_server.repositories.interfaces.commands.submissions import (
    ScoreSubmissionCommandRepository,
)
from osu_server.repositories.interfaces.commands.users import UserCommandRepository

__all__ = [
    "BeatmapCommandRepository",
    "BeatmapLeaderboardCommandRepository",
    "BeatmapPerformanceBestCommandRepository",
    "BeatmapSubmissionCounts",
    "BlobCommandRepository",
    "ChannelCommandRepository",
    "ChatCommandRepository",
    "CurrentUserStatsCommandRepository",
    "FriendRelationshipCommandRepository",
    "PersonalBestCommandRepository",
    "ReplayCommandRepository",
    "RoleCommandRepository",
    "ScoreCommandRepository",
    "ScorePerformanceCalculationLifecycleRepository",
    "ScorePerformanceCommandRepository",
    "ScorePerformanceRecalculationWorkRepository",
    "ScoreSubmissionCommandRepository",
    "UserCommandRepository",
]
