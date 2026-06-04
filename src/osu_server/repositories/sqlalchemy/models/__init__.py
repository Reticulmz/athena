"""SQLAlchemy ORM models.

Import all models here so that Alembic can discover them via Base.metadata.
"""

from osu_server.repositories.sqlalchemy.models.blob import BlobModel
from osu_server.repositories.sqlalchemy.models.channel import (
    ChannelMessageModel,
    ChannelModel,
    ChannelRoleOverrideModel,
    PrivateMessageModel,
)
from osu_server.repositories.sqlalchemy.models.role import RoleModel, UserRoleModel
from osu_server.repositories.sqlalchemy.models.user import (
    DisallowedUsernameModel,
    UserModel,
)

__all__ = [
    "BlobModel",
    "ChannelMessageModel",
    "ChannelModel",
    "ChannelRoleOverrideModel",
    "DisallowedUsernameModel",
    "PrivateMessageModel",
    "RoleModel",
    "UserModel",
    "UserRoleModel",
]
