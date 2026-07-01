"""In-memory command repository package."""

from osu_server.repositories.memory.commands.beatmap_leaderboards import (
    InMemoryBeatmapLeaderboardCommandRepository,
)
from osu_server.repositories.memory.commands.beatmap_performance_bests import (
    InMemoryBeatmapPerformanceBestCommandRepository,
)
from osu_server.repositories.memory.commands.beatmaps import (
    BeatmapNotFoundError,
    DuplicateBeatmapChecksumError,
    InMemoryBeatmapCommandRepository,
)
from osu_server.repositories.memory.commands.blobs import InMemoryBlobCommandRepository
from osu_server.repositories.memory.commands.channels import InMemoryChannelCommandRepository
from osu_server.repositories.memory.commands.chat import InMemoryChatCommandRepository
from osu_server.repositories.memory.commands.current_user_stats import (
    InMemoryCurrentUserStatsCommandRepository,
)
from osu_server.repositories.memory.commands.friends import (
    InMemoryFriendRelationshipCommandRepository,
)
from osu_server.repositories.memory.commands.personal_bests import (
    InMemoryPersonalBestCommandRepository,
)
from osu_server.repositories.memory.commands.replays import InMemoryReplayCommandRepository
from osu_server.repositories.memory.commands.roles import InMemoryRoleCommandRepository
from osu_server.repositories.memory.commands.score_performance import (
    InMemoryScorePerformanceCommandRepository,
)
from osu_server.repositories.memory.commands.scores import InMemoryScoreCommandRepository
from osu_server.repositories.memory.commands.state import InMemoryCommandRepositoryState
from osu_server.repositories.memory.commands.submissions import (
    InMemoryScoreSubmissionCommandRepository,
)
from osu_server.repositories.memory.commands.users import InMemoryUserCommandRepository

__all__ = [
    "BeatmapNotFoundError",
    "DuplicateBeatmapChecksumError",
    "InMemoryBeatmapCommandRepository",
    "InMemoryBeatmapLeaderboardCommandRepository",
    "InMemoryBeatmapPerformanceBestCommandRepository",
    "InMemoryBlobCommandRepository",
    "InMemoryChannelCommandRepository",
    "InMemoryChatCommandRepository",
    "InMemoryCommandRepositoryState",
    "InMemoryCurrentUserStatsCommandRepository",
    "InMemoryFriendRelationshipCommandRepository",
    "InMemoryPersonalBestCommandRepository",
    "InMemoryReplayCommandRepository",
    "InMemoryRoleCommandRepository",
    "InMemoryScoreCommandRepository",
    "InMemoryScorePerformanceCommandRepository",
    "InMemoryScoreSubmissionCommandRepository",
    "InMemoryUserCommandRepository",
]
