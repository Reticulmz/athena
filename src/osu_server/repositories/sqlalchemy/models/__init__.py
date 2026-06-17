"""SQLAlchemy ORM models.

Import all models here so that Alembic can discover them via Base.metadata.
"""

from osu_server.repositories.sqlalchemy.models.beatmap import (
    BeatmapFetchStateModel,
    BeatmapFileAttachmentModel,
    BeatmapModel,
    BeatmapSetModel,
)
from osu_server.repositories.sqlalchemy.models.blob import BlobModel
from osu_server.repositories.sqlalchemy.models.channel import (
    ChannelMessageModel,
    ChannelModel,
    ChannelRoleOverrideModel,
    PrivateMessageModel,
)
from osu_server.repositories.sqlalchemy.models.friend import UserFriendRelationshipModel
from osu_server.repositories.sqlalchemy.models.personal_best import PersonalBestModel
from osu_server.repositories.sqlalchemy.models.role import RoleModel, UserRoleModel
from osu_server.repositories.sqlalchemy.models.score import (
    ReplayModel,
    ScoreModel,
    ScoreSubmissionModel,
)
from osu_server.repositories.sqlalchemy.models.score_performance import (
    PerformanceRecalculationBatchModel,
    PerformanceRecalculationWorkItemModel,
    ScorePerformanceCalculationModel,
)
from osu_server.repositories.sqlalchemy.models.user import (
    DisallowedUsernameModel,
    UserModel,
)

__all__ = [
    "BeatmapFetchStateModel",
    "BeatmapFileAttachmentModel",
    "BeatmapModel",
    "BeatmapSetModel",
    "BlobModel",
    "ChannelMessageModel",
    "ChannelModel",
    "ChannelRoleOverrideModel",
    "DisallowedUsernameModel",
    "PerformanceRecalculationBatchModel",
    "PerformanceRecalculationWorkItemModel",
    "PersonalBestModel",
    "PrivateMessageModel",
    "ReplayModel",
    "RoleModel",
    "ScoreModel",
    "ScorePerformanceCalculationModel",
    "ScoreSubmissionModel",
    "UserFriendRelationshipModel",
    "UserModel",
    "UserRoleModel",
]
